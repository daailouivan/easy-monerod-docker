#!/usr/bin/env python3
"""Validate the single compose file, default and with each variant enabled.

The Synology and Tor variants ship commented out, which means Compose never
sees them and they can rot silently. So this suite uncomments each block
programmatically and runs the real `docker compose config` validator over the
result — the commented options are tested, not just the default path.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
IMAGE = "ghcr.io/daailouivan/easy-monerod"
DATA = "/home/monero/.bitmonero"

KNOWN_FLAGS = {
    "--rpc-restricted-bind-ip", "--rpc-restricted-bind-port", "--no-igd",
    "--no-zmq", "--enable-dns-blocklist", "--ban-list", "--public-node",
    "--prune-blockchain", "--rpc-bind-port", "--rpc-login", "--non-interactive",
    "--data-dir", "--log-level", "--out-peers", "--in-peers",
    # Tor/I2P, per docs/ANONYMITY_NETWORKS.md
    "--tx-proxy", "--anonymous-inbound", "--proxy", "--p2p-bind-ip",
    "--add-exclusive-node", "--add-priority-node", "--add-peer",
}

passed = failed = 0


def check(cond, msg):
    global passed, failed
    print(("  PASS " if cond else "  FAIL ") + msg)
    if cond:
        passed += 1
    else:
        failed += 1


def compose_cmd():
    """Compose CLI, falling back to the plugin binary when it isn't linked."""
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "compose", "version"],
                           capture_output=True, check=True)
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, OSError):
            pass
    for p in ("/opt/homebrew/lib/docker/cli-plugins/docker-compose",
              "/usr/local/lib/docker/cli-plugins/docker-compose",
              os.path.expanduser("~/.docker/cli-plugins/docker-compose")):
        if os.access(p, os.X_OK):
            return [p]
    found = shutil.which("docker-compose")
    return [found] if found else None


CC = compose_cmd()


def validate(text, label):
    """Run the real compose schema validator over `text`."""
    if not CC:
        print(f"  SKIP compose CLI not found ({label})")
        return None
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "docker-compose.yml"
        f.write_text(text)
        r = subprocess.run(CC + ["-f", str(f), "config", "--quiet"],
                           capture_output=True, text=True)
        return r.returncode == 0, r.stderr.strip()[:140]


def uncomment(text, markers, drop=(), skip_nested=False):
    """Uncomment lines whose comment body starts with one of `markers`.

    Mirrors what a user does by hand: strip the leading '# ' from the option
    lines, and comment out any default lines the variant replaces.

    skip_nested leaves doubly-commented lines ('# # foo') alone — those belong
    to a different variant's block and uncommenting them one level would strand
    keys under a service that is still commented out.
    """
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped.startswith("#"):
            body = stripped[1:]
            body = body[1:] if body.startswith(" ") else body
            if skip_nested and body.lstrip().startswith("#"):
                out.append(line)
                continue
            if any(body.lstrip().startswith(m) for m in markers):
                out.append(indent + body)
                continue
        if any(d in line for d in drop) and not stripped.startswith("#"):
            out.append(indent + "# " + stripped)
            continue
        out.append(line)
    return "\n".join(out)


raw = COMPOSE.read_text()
doc = yaml.safe_load(raw)
svc = doc["services"]["monerod"]

print("[default stack]")
check(COMPOSE.exists(), "single docker-compose.yml exists")
check("version" not in doc, "no obsolete top-level 'version' key")
check(IMAGE in svc["image"], f"image is {IMAGE}")
check("MONEROD_IMAGE" in svc["image"], "image overridable via $MONEROD_IMAGE")
check(any(DATA in v for v in svc["volumes"]), f"blockchain mounted at {DATA}")
ports = [str(p).strip('"') for p in svc["ports"]]
check(any(p.startswith("18080") for p in ports), "p2p 18080 published")
check(any(p.startswith("18089") for p in ports), "restricted RPC 18089 published")
cmd = svc["command"]
unknown = {c.split("=")[0] for c in cmd} - KNOWN_FLAGS
check(not unknown, f"all flags recognised{'' if not unknown else ': ' + str(unknown)}")
check("--rpc-restricted-bind-port=18089" in cmd,
      "RPC port restated (custom command replaces the image CMD)")
check("watchtower" in doc["services"], "watchtower included by default")
check(svc["labels"]["com.centurylinklabs.watchtower.enable"] == "true",
      "monerod opted in to watchtower")
r = validate(raw, "default")
if r:
    check(r[0], f"docker compose config{'' if r[0] else ' -> ' + r[1]}")
print()

print("[variant A: Synology — uncommented programmatically]")
syn_text = uncomment(
    raw,
    markers=("user: ${FIXUID", "hostname: monerod", "- ./bitmonero:",
             "networks:", "- host_bridge", "host_bridge:",
             "name: host_bridge", "driver: bridge"),
    drop=("- bitmonero:/home/monero/.bitmonero",),
    skip_nested=True,
)
syn = yaml.safe_load(syn_text)
ssvc = syn["services"]["monerod"]
check("user" in ssvc, "explicit uid:gid set")
check("FIXUID" in str(ssvc.get("user")), "uid overridable via $FIXUID")
check(any(str(v).startswith("./bitmonero") for v in ssvc["volumes"]),
      "bind mount into a DSM-browsable folder")
check(not any(str(v).startswith("bitmonero:") for v in ssvc["volumes"]),
      "named volume disabled when the bind mount is used")
check("host_bridge" in syn.get("networks", {}), "named bridge declared")
r = validate(syn_text, "synology")
if r:
    check(r[0], f"docker compose config{'' if r[0] else ' -> ' + r[1]}")
print()

print("[variant B: Tor — uncommented programmatically]")
tor_text = uncomment(
    raw,
    markers=('- "127.0.0.1:18089:18089"', "- --tx-proxy", "- --anonymous-inbound",
             "depends_on:", "- tor", "tor:", "image: ghcr.io/hundehausen",
             "container_name: tor", "restart: unless-stopped",
             "- tor-keys:/var/lib/tor", "environment:", "- HS_MONEROD",
             "tor-keys:", "volumes:"),
    drop=('- "18089:18089"',),
)
tor = yaml.safe_load(tor_text)
tsvc = tor["services"]["monerod"]
tcmd = tsvc["command"]
check("tor" in tor["services"], "tor service enabled")
tor_svc = tor["services"]["tor"]
check("hundehausen/tor-hidden-service" in tor_svc["image"], "maintained tor image")
check("goldy/" not in raw, "not the stale goldy image (last built 2023)")

hs = dict(e.split("=", 1) for e in tor_svc["environment"] if e.startswith("HS_"))
check(len(hs) == 2, f"two hidden services: {sorted(hs)}")
check(hs.get("HS_MONEROD_RPC") == "monerod:18089:18089", "RPC onion -> monerod:18089")
check(hs.get("HS_MONEROD_P2P") == "monerod:18084:18084", "P2P onion -> monerod:18084")
check("18080" not in str(hs.get("HS_MONEROD_P2P", "")),
      "anonymous-inbound on a dedicated port, not 18080 (docs requirement)")

txp = [c for c in tcmd if c.startswith("--tx-proxy")]
check(bool(txp) and txp[0].split("=", 1)[1].startswith("tor,"),
      f"--tx-proxy tor — our own txs broadcast over Tor: {txp}")
check(any(c.startswith("--anonymous-inbound") for c in tcmd),
      "--anonymous-inbound present")
check("ANONYMOUS_INBOUND" in raw, "inbound onion supplied via env, not hardcoded")
tports = [str(p).strip('"') for p in tsvc["ports"]]
check(any(p.startswith("127.0.0.1:18089") for p in tports),
      "RPC on loopback only (reached via onion, not the LAN)")
check(not any(p == "18089:18089" for p in tports), "LAN RPC disabled")
check(any(p.startswith("18080") for p in tports),
      "clearnet p2p still published (monerod cannot sync over onion)")
check("tor-keys" in tor.get("volumes", {}), "tor-keys volume declared")
check(any("tor-keys" in str(v) for v in tor_svc["volumes"]),
      "onion keys persisted (stable address across restarts)")
r = validate(tor_text, "tor")
if r:
    check(r[0], f"docker compose config{'' if r[0] else ' -> ' + r[1]}")
print()

print("[docs stay in sync with the file]")
readme = (ROOT / "README.md").read_text()
check("docker-compose.synology.yml" not in readme,
      "README does not reference the removed synology file")
check("docker-compose.tor.yml" not in readme,
      "README does not reference the removed tor file")
check(not (ROOT / "docker-compose.synology.yml").exists(), "synology file removed")
check(not (ROOT / "docker-compose.tor.yml").exists(), "tor file removed")
for marker in ("(A) SYNOLOGY", "(B) TOR", "(C) COMMON OPTIONS"):
    check(marker in raw, f"variant block labelled: {marker}")

print(f"\nTOTAL passed={passed} failed={failed}")
sys.exit(1 if failed else 0)
