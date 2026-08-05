#!/usr/bin/env python3
"""Validate both compose stacks.

Guards the standard and Synology variants: they must stay parseable, point at
the same GHCR image, keep the ports and data path the image expects, and pass
only flags monerod actually accepts.
"""
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
STACKS = {
    "standard": ROOT / "docker-compose.yml",
    "synology": ROOT / "docker-compose.synology.yml",
}
IMAGE = "ghcr.io/daailouivan/easy-monerod"
DATA = "/home/monero/.bitmonero"

# Flags the Dockerfile's own CMD uses, i.e. known-good against this monerod.
KNOWN = {
    "--rpc-restricted-bind-ip", "--rpc-restricted-bind-port", "--no-igd",
    "--no-zmq", "--enable-dns-blocklist", "--ban-list", "--public-node",
    "--prune-blockchain", "--rpc-bind-port", "--rpc-login", "--non-interactive",
    "--data-dir", "--log-level", "--out-peers", "--in-peers",
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
    check(any(p.startswith("18089") for p in ports), "restricted RPC 18089 published")

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
