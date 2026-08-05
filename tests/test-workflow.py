#!/usr/bin/env python3
"""Structural checks on .github/workflows/auto-update.yml.

Guards the parallel-native-build + manifest-merge topology so a future edit
can't silently reintroduce QEMU emulation, drop an arch, or tag in the wrong
job (which would leave :latest pointing at a single-arch image).
"""
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/auto-update.yml"

raw = WF.read_text()
d = yaml.safe_load(raw)
# PyYAML parses the bare `on:` key as boolean True
triggers = d.get("on", d.get(True))
jobs = d["jobs"]

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        print(f"  PASS {msg}")
        passed += 1
    else:
        print(f"  FAIL {msg}")
        failed += 1


print("[triggers]")
check("schedule" in triggers, "runs on a schedule")
check(triggers["schedule"][0]["cron"] == "0 6 * * *", "daily at 06:00 UTC")
check("force" in triggers["workflow_dispatch"]["inputs"], "manual force input exists")

print("[topology]")
check(set(jobs) == {"update", "build", "merge"}, f"three jobs: {sorted(jobs)}")
check(jobs["build"]["needs"] == "update", "build depends on update")
check(sorted(jobs["merge"]["needs"]) == ["build", "update"], "merge depends on build+update")
check(
    jobs["build"]["if"] == "needs.update.outputs.updated == 'true'",
    "build gated on an actual update",
)

print("[parallel native matrix]")
inc = jobs["build"]["strategy"]["matrix"]["include"]
by_arch = {e["arch"]: e for e in inc}
check(set(by_arch) == {"amd64", "arm64"}, f"both arches present: {sorted(by_arch)}")
check(by_arch["amd64"]["runner"] == "ubuntu-latest", "amd64 on x86 runner")
check("arm" in by_arch["arm64"]["runner"], f"arm64 on NATIVE arm runner ({by_arch['arm64']['runner']})")
check(jobs["build"]["strategy"].get("fail-fast") is False, "fail-fast off (see both arch failures)")
check("setup-qemu-action" not in raw, "no QEMU emulation anywhere")

print("[digest-only build, tagging deferred to merge]")
bsteps = {s.get("name", ""): s for s in jobs["build"]["steps"]}
push = next(s for n, s in bsteps.items() if n.startswith("Build and push by digest"))
out = push["with"]["outputs"]
check("push-by-digest=true" in out, "build pushes by digest")
check("push=true" in out, "build pushes")
check("tags" not in push["with"], "build job sets NO tags (avoids single-arch :latest)")
check(
    push["with"]["platforms"] == "${{ matrix.platform }}",
    "each job builds exactly one platform",
)
check(
    "scope=${{ matrix.arch }}" in push["with"]["cache-from"],
    "per-arch cache scope (no cross-arch cache poisoning)",
)

print("[merge + verification]")
msteps = [s.get("name", "") for s in jobs["merge"]["steps"]]
for s in msteps:
    if s:
        print(f"    - {s}")
mtext = yaml.dump(jobs["merge"])
check("imagetools create" in mtext, "merges digests into a manifest")
for tag in ("latest", "alpine", "${{ needs.update.outputs.version }}"):
    check(tag in mtext, f"tags :{tag}")
check(any("Verify" in s for s in msteps), "verifies the pushed manifest")
check("imagetools inspect" in mtext, "inspects the manifest after push")
check(mtext.count("linux/amd64") and mtext.count("linux/arm64"), "asserts both arches post-push")
check(any("public" in s.lower() for s in msteps), "makes the GHCR package public")
check(any("Summary" in s for s in msteps), "writes a run summary with the pull command")

print("[registry: GHCR, no stored credential]")
check("ghcr.io" in d["env"]["IMAGE"], f'publishes to GHCR ({d["env"]["IMAGE"]})')
check(d["permissions"].get("packages") == "write", "packages:write granted")
check("DOCKERHUB" not in raw, "no Docker Hub secret referenced anywhere")
check("dckr_pat_" not in raw, "no hardcoded token")
check(
    raw.count("secrets.GITHUB_TOKEN") >= 2,
    "auths with the per-run GITHUB_TOKEN (build + merge)",
)
check(
    all(
        "ghcr.io" in s.get("with", {}).get("registry", "")
        for j in ("build", "merge")
        for s in jobs[j]["steps"]
        if s.get("uses", "").startswith("docker/login-action")
    ),
    "every login targets ghcr.io",
)
check("github.repository_owner" in d["env"]["IMAGE"], "namespace derived from the repo, not hardcoded")

print(f"\nTOTAL passed={passed} failed={failed}")
sys.exit(1 if failed else 0)
