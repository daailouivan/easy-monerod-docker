#!/usr/bin/env bash
# check-update.sh — resolve the newest stable monero-project/monero tag and
# rewrite the MONERO_BRANCH / MONERO_COMMIT_HASH pin block in the Dockerfile.
#
# Exit codes:
#   0 = pin was updated (or --check found an update available)
#   1 = hard error
#   2 = already up to date / nothing to do
#
# Usage:
#   scripts/check-update.sh            # rewrite the Dockerfile pin in place
#   scripts/check-update.sh --check    # report only, do not write
#
# Outputs machine-readable lines on stdout (consumed by CI):
#   current=v0.18.5.0
#   latest=v0.18.5.1
#   sha=4f92268d7c16741cfb41e5bbe2aa46cc260a9ea5
#   updated=true|false
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERFILE="${DOCKERFILE:-${REPO_ROOT}/Dockerfile}"
API="${MONERO_API:-https://api.github.com/repos/monero-project/monero}"
CHECK_ONLY=false
[ "${1:-}" = "--check" ] && CHECK_ONLY=true

command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 1; }
[ -f "${DOCKERFILE}" ] || { echo "error: no Dockerfile at ${DOCKERFILE}" >&2; exit 1; }

# curl wrapper: adds auth when GITHUB_TOKEN is present. Written as a function
# rather than a bash array so it works on bash 3.2 (macOS) under `set -u`.
api_get() {
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        curl -fsSL -H "Authorization: Bearer ${GITHUB_TOKEN}" "$1"
    else
        curl -fsSL "$1"
    fi
}

# Portable "highest version" sort: `sort -V` is absent on BSD/macOS.
version_max() {
    awk -F. '{ printf "%05d%05d%05d%05d %s\n", substr($1,2), $2, $3, $4, $0 }' \
        | sort | tail -n1 | cut -d" " -f2
}

# --- current pin -------------------------------------------------------------
current="$(sed -n 's/^ARG MONERO_BRANCH=\(.*\)$/\1/p' "${DOCKERFILE}" | head -n1)"
[ -n "${current}" ] || { echo "error: MONERO_BRANCH pin not found" >&2; exit 1; }

# --- latest stable tag -------------------------------------------------------
# Only vX.Y.Z.W tags; excludes -rc / -beta and any non-release refs.
tags_json="$(api_get "${API}/tags?per_page=100")"
latest="$(printf '%s' "${tags_json}" \
    | jq -r '.[].name | select(test("^v[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$"))' \
    | version_max)"
[ -n "${latest}" ] || { echo "error: could not resolve latest tag" >&2; exit 1; }

# --- commit hash for that tag ------------------------------------------------
# Annotated tags dereference through .object.url -> commit sha.
ref_json="$(api_get "${API}/git/ref/tags/${latest}")"
obj_type="$(printf '%s' "${ref_json}" | jq -r '.object.type')"
sha="$(printf '%s' "${ref_json}" | jq -r '.object.sha')"
if [ "${obj_type}" = "tag" ]; then
    sha="$(api_get "${API}/git/tags/${sha}" | jq -r '.object.sha')"
fi
printf '%s' "${sha}" | grep -Eq '^[0-9a-f]{40}$' \
    || { echo "error: bad commit sha '${sha}'" >&2; exit 1; }

echo "current=${current}"
echo "latest=${latest}"
echo "sha=${sha}"

if [ "${current}" = "${latest}" ]; then
    echo "updated=false"
    echo "Already on the newest monero release (${current})." >&2
    exit 2
fi

if [ "${CHECK_ONLY}" = true ]; then
    echo "updated=false"
    echo "Update available: ${current} -> ${latest}" >&2
    exit 0
fi

# --- rewrite the pin block ---------------------------------------------------
tmp="$(mktemp)"
awk -v br="${latest}" -v sha="${sha}" '
    /^ARG MONERO_BRANCH=/       { print "ARG MONERO_BRANCH=" br; next }
    /^ARG MONERO_COMMIT_HASH=/  { print "ARG MONERO_COMMIT_HASH=" sha; next }
    { print }
' "${DOCKERFILE}" > "${tmp}"
mv "${tmp}" "${DOCKERFILE}"

# verify the write landed
grep -q "^ARG MONERO_BRANCH=${latest}$" "${DOCKERFILE}" \
    && grep -q "^ARG MONERO_COMMIT_HASH=${sha}$" "${DOCKERFILE}" \
    || { echo "error: pin rewrite failed" >&2; exit 1; }

echo "updated=true"
echo "Bumped ${current} -> ${latest} (${sha})" >&2
