#!/usr/bin/env python3
"""Validate both compose stacks, with and without the optional Tor block.

Two files, split by host:
    docker-compose.yml            standard Docker host
    docker-compose-synology.yml   Synology NAS

Tor ships commented out in both, which means Compose never sees it and it can
rot silently. So this suite uncomments the Tor block programmatically and runs
the real `docker compose config` validator over the result — the optional path
is tested, not just the default one.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
STACKS = {
    "standard": ROOT / "docker-compose.yml",
    "synology": ROOT / "docker-compose-synology.yml",
}
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


# Every line to uncomment for Tor is tagged `#T` in both compose files, so
# enabling it is mechanical — no heuristics, and `grep -n '#T'` shows a user
# exactly the same set of lines this test flips.
PLAIN_RPC = '- "18089:18089"'


def enable_tor(text):
    """Uncomment every `#T` line, and comment the LAN RPC port it replaces."""
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped.startswith(PLAIN_RPC) and not stripped.startswith("#"):
            out.append(indent + "# " + stripped)
            continue
        if stripped.startswith("#T "):
            out.append(indent + stripped[3:])
            continue
        if stripped.startswith("#T"):
            out.append(indent + stripped[2:])
            continue
        out.append(line)
    return "\n".join(out)


for name, path in STACKS.items():
    print(f"[{name}] {path.name}")
    check(path.exists(), "file exists")
    raw = path.read_text()
    d = yaml.safe_load(raw)
    check("version" not in d, "no obsolete top-level 'version' key")

    svc = d["services"]["monerod"]
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

    r = validate(raw, name)
    if r:
        check(r[0], f"docker compose config{'' if r[0] else ' -> ' + r[1]}")

    # --- the same file with Tor switched on -------------------------------
    tor_text = enable_tor(raw)
    t = yaml.safe_load(tor_text)
    tsvc = t["services"]["monerod"]
    tcmd = tsvc["command"]
    check("tor" in t["services"], "TOR: tor service enabled")
    tor_svc = t["services"]["tor"]
    check("hundehausen/tor-hidden-service" in tor_svc["image"],
          "TOR: maintained tor image")
    check("goldy/" not in raw, "TOR: not the stale goldy image (last built 2023)")

    hs = dict(e.split("=", 1) for e in tor_svc["environment"] if e.startswith("HS_"))
    check(len(hs) == 2, f"TOR: two hidden services: {sorted(hs)}")
    check(hs.get("HS_MONEROD_RPC") == "monerod:18089:18089",
          "TOR: RPC onion -> monerod:18089")
    check(hs.get("HS_MONEROD_P2P") == "monerod:18084:18084",
          "TOR: P2P onion -> monerod:18084")
    check("18080" not in str(hs.get("HS_MONEROD_P2P", "")),
          "TOR: anonymous-inbound on a dedicated port, not 18080 (docs requirement)")

    txp = [c for c in tcmd if c.startswith("--tx-proxy")]
    check(bool(txp) and txp[0].split("=", 1)[1].startswith("tor,"),
          "TOR: --tx-proxy tor, so our own txs broadcast over Tor")
    check(any(c.startswith("--anonymous-inbound") for c in tcmd),
          "TOR: --anonymous-inbound present")
    check("ANONYMOUS_INBOUND" in raw, "TOR: inbound onion via env, not hardcoded")

    tports = [str(p).strip('"') for p in tsvc["ports"]]
    check(any(p.startswith("127.0.0.1:18089") for p in tports),
          "TOR: RPC on loopback only (reached via onion, not the LAN)")
    check("18089:18089" not in tports, "TOR: LAN RPC disabled")
    check(any(p.startswith("18080") for p in tports),
          "TOR: clearnet p2p still published (cannot sync over onion)")
    check(any("tor-keys" in str(v) for v in tor_svc["volumes"]),
          "TOR: onion keys persisted (stable address across restarts)")
    check(tsvc.get("depends_on") == ["tor"], "TOR: monerod waits for the proxy")

    r = validate(tor_text, f"{name}+tor")
    if r:
        check(r[0], f"TOR: docker compose config{'' if r[0] else ' -> ' + r[1]}")
    print()

print("[cross-stack]")
std_raw = STACKS["standard"].read_text()
syn_raw = STACKS["synology"].read_text()
std = yaml.safe_load(std_raw)["services"]["monerod"]
syn = yaml.safe_load(syn_raw)["services"]["monerod"]
check(std["image"] == syn["image"], "both stacks pin the same image expression")
check("user" not in std, "standard relies on fixuid (no hardcoded uid)")
check("user" in syn, "synology sets an explicit uid:gid")
check("FIXUID" in str(syn.get("user")), "synology uid overridable via $FIXUID")
check(str(syn["volumes"][0]).startswith("./"), "synology uses a bind mount")
check(not str(std["volumes"][0]).startswith("./"), "standard uses a named volume")
check("watchtower" in yaml.safe_load(std_raw)["services"], "standard ships watchtower")
check("host_bridge" in yaml.safe_load(syn_raw).get("networks", {}),
      "synology declares the named bridge")

print("\n[naming + docs]")
check(not (ROOT / "docker-compose.tor.yml").exists(),
      "no ambiguous docker-compose.tor.yml (host unclear)")
check(not (ROOT / "docker-compose.synology.yml").exists(),
      "old dotted synology name removed")
readme = (ROOT / "README.md").read_text()
check("docker-compose.tor.yml" not in readme, "README has no ref to the removed tor file")
check("docker-compose.synology.yml" not in readme, "README has no ref to the old synology name")
check("docker-compose-synology.yml" in readme, "README documents the synology stack")
for name, path in STACKS.items():
    check("OPTIONAL: TOR" in path.read_text(), f"{name}: Tor block present and labelled")

print(f"\nTOTAL passed={passed} failed={failed}")
sys.exit(1 if failed else 0)
