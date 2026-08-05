#!/usr/bin/env python3
"""Validate both compose stacks.

Guards the standard and Synology variants: they must stay parseable, point at
the same GHCR image, keep the ports and data path the image expects, and pass
only flags monerod actually accepts.
"""
import os
import pathlib
import shutil
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
STACKS = {
    "standard": ROOT / "docker-compose.yml",
    "synology": ROOT / "docker-compose.synology.yml",
    "tor": ROOT / "docker-compose.tor.yml",
}
IMAGE = "ghcr.io/daailouivan/easy-monerod"
DATA = "/home/monero/.bitmonero"

# Flags the Dockerfile's own CMD uses, i.e. known-good against this monerod.
KNOWN = {
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


for name, path in STACKS.items():
    print(f"[{name}] {path.name}")
    check(path.exists(), "file exists")
    d = yaml.safe_load(path.read_text())
    check(isinstance(d, dict) and "services" in d, "parses with a services block")
    check("version" not in d, "no obsolete top-level 'version' key")

    svc = d["services"]["monerod"]
    check(IMAGE in svc["image"], f"image is {IMAGE}")
    check("MONEROD_IMAGE" in svc["image"], "image overridable via $MONEROD_IMAGE")

    mounts = [v.split(":")[1] for v in svc["volumes"]]
    check(DATA in mounts, f"blockchain mounted at {DATA}")

    ports = [str(p).strip('"') for p in svc["ports"]]
    check(any(p.startswith("18080") for p in ports), "p2p 18080 published")
    # The tor stack deliberately binds RPC to loopback (reachable via the
    # onion service, not the LAN), so accept either form.
    check(
        any(p.endswith("18089:18089") or p.startswith("18089") for p in ports),
        "restricted RPC 18089 mapped",
    )

    cmd = svc["command"]
    flags = {c.split("=")[0] for c in cmd}
    unknown = flags - KNOWN
    check(not unknown, f"all flags recognised{'' if not unknown else ': ' + str(unknown)}")
    check(all(c.startswith("--") for c in cmd), "every command entry is a flag")
    check(
        "--rpc-restricted-bind-ip=0.0.0.0" in cmd,
        "restricted RPC bound for container networking",
    )
    # Overriding CMD drops the image default, so the port must be restated.
    check(
        "--rpc-restricted-bind-port=18089" in cmd,
        "RPC port restated (custom command replaces the image CMD)",
    )
    print()

# Compose's own schema validator, when available. `config` needs no daemon.
# The plugin is sometimes installed but not linked into the docker CLI, so
# fall back to invoking the binary directly.
def compose_cmd():
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "compose", "version"], capture_output=True, check=True)
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, OSError):
            pass
    for p in (
        "/opt/homebrew/lib/docker/cli-plugins/docker-compose",
        "/usr/local/lib/docker/cli-plugins/docker-compose",
        os.path.expanduser("~/.docker/cli-plugins/docker-compose"),
    ):
        if os.access(p, os.X_OK):
            return [p]
    return shutil.which("docker-compose") and [shutil.which("docker-compose")]


print("[compose schema]")
cc = compose_cmd()
if cc:
    for name, path in STACKS.items():
        r = subprocess.run(
            cc + ["-f", str(path), "config", "--quiet"],
            capture_output=True, text=True,
        )
        check(r.returncode == 0, f"{name}: docker compose config{'' if r.returncode == 0 else ' -> ' + r.stderr.strip()[:90]}")
else:
    print("  SKIP compose CLI not found on this host")
print()

print("[tor stack — per monero-project/monero docs/ANONYMITY_NETWORKS.md]")
tor_doc = yaml.safe_load(STACKS["tor"].read_text())
tsvc = tor_doc["services"]["tor"]
tmon = tor_doc["services"]["monerod"]
tcmd = tmon["command"]
traw = STACKS["tor"].read_text()

check("hundehausen/tor-hidden-service" in tsvc["image"], "maintained tor image")
check("goldy/" not in traw, "not the stale goldy image (last built 2023)")

hs = dict(e.split("=", 1) for e in tsvc["environment"] if e.startswith("HS_"))
check(len(hs) == 2, f"two hidden services declared: {sorted(hs)}")
rpc = [v for k, v in hs.items() if "RPC" in k]
p2p = [v for k, v in hs.items() if "P2P" in k]
check(bool(rpc) and rpc[0] == "monerod:18089:18089", "RPC onion -> monerod:18089")
check(bool(p2p) and p2p[0] == "monerod:18084:18084", "P2P onion -> monerod:18084")

# Official requirement: anonymous-inbound port must NOT be the clearnet p2p port.
check(
    bool(p2p) and not p2p[0].split(":")[1] == "18080",
    "anonymous-inbound uses a dedicated port, not 18080 (docs requirement)",
)

# 2 of the 3 official capabilities are monerod flags, not container config.
txp = [c for c in tcmd if c.startswith("--tx-proxy")]
check(bool(txp), f"--tx-proxy set, so our own txs broadcast over Tor: {txp}")
check(
    bool(txp) and txp[0].split("=", 1)[1].startswith("tor,"),
    "tx-proxy declares the tor network type",
)
check(
    any(c.startswith("--anonymous-inbound") for c in tcmd),
    "--anonymous-inbound present (accepts inbound onion peers)",
)
check("ANONYMOUS_INBOUND" in traw, "inbound onion address supplied via env, not hardcoded")

check(
    any("tor-keys" in v for v in tsvc["volumes"]),
    "onion keys persisted (stable addresses across restarts)",
)
check("tor-keys" in tor_doc["volumes"], "tor-keys volume declared")
check(
    any(str(p).strip('"').startswith("127.0.0.1:18089") for p in tmon["ports"]),
    "RPC on loopback only (reachable via onion, not the LAN)",
)
check(
    any(str(p).strip('"').startswith("18080") for p in tmon["ports"]),
    "clearnet p2p still published (monerod cannot sync over onion)",
)
check(tmon.get("depends_on") == ["tor"], "monerod waits for the tor proxy")
print()

print("[cross-stack]")
std = yaml.safe_load(STACKS["standard"].read_text())["services"]["monerod"]
syn = yaml.safe_load(STACKS["synology"].read_text())["services"]["monerod"]
check(std["image"] == syn["image"], "both stacks pin the same image expression")
check("user" not in std, "standard relies on fixuid (no hardcoded uid)")
check("user" in syn, "synology sets an explicit uid:gid")
check(
    syn["volumes"][0].startswith("./"),
    "synology uses a bind mount (DSM-browsable)",
)
check(
    not std["volumes"][0].startswith("./"),
    "standard uses a named volume",
)
check(
    "watchtower" in yaml.safe_load(STACKS["standard"].read_text())["services"],
    "standard ships watchtower",
)

print(f"\nTOTAL passed={passed} failed={failed}")
sys.exit(1 if failed else 0)
