#!/usr/bin/env bash
# test-check-update.sh — verifies scripts/check-update.sh against a stubbed
# GitHub API (no network), covering: stale pin -> bump, current pin -> exit 2,
# --check mode leaves the file untouched, and rc-tag filtering.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok(){ echo "PASS: $1"; pass=$((pass+1)); }
no(){ echo "FAIL: $1"; fail=$((fail+1)); }

SHA_NEW=4f92268d7c16741cfb41e5bbe2aa46cc260a9ea5
SHA_TAGOBJ=1111111111111111111111111111111111111111

# --- fake curl: serves canned API responses -----------------------------------
mkdir -p "$TMP/bin"
cat > "$TMP/bin/curl" <<EOF
#!/usr/bin/env bash
url="\${@: -1}"
case "\$url" in
  *"/tags?per_page=100")
    cat <<'JSON'
[{"name":"v0.18.5.1"},{"name":"v0.18.6.0-rc1"},{"name":"v0.18.5.0"},{"name":"v0.18.4.6"},{"name":"release-v0.18"}]
JSON
    ;;
  *"/git/ref/tags/v0.18.5.1")
    echo '{"object":{"type":"tag","sha":"$SHA_TAGOBJ"}}' ;;
  *"/git/tags/$SHA_TAGOBJ")
    echo '{"object":{"type":"commit","sha":"$SHA_NEW"}}' ;;
  *) echo "unexpected url: \$url" >&2; exit 22 ;;
esac
EOF
chmod +x "$TMP/bin/curl"
export PATH="$TMP/bin:$PATH"

mkdf(){ # $1 = version pin
  printf 'FROM alpine\nARG MONERO_BRANCH=%s\nARG MONERO_COMMIT_HASH=deadbeef\nRUN true\n' "$1" > "$TMP/Dockerfile"
}

run(){ DOCKERFILE="$TMP/Dockerfile" "$ROOT/scripts/check-update.sh" "$@" 2>"$TMP/err"; }

echo "--- case 1: stale pin should bump to newest stable tag"
mkdf v0.18.4.6
out="$(run)"; rc=$?
echo "$out"
[ "$rc" = 0 ] && ok "exit 0" || no "exit 0 (got $rc)"
grep -q '^latest=v0.18.5.1$' <<<"$out" && ok "picked v0.18.5.1 (rc tag ignored)" || no "latest wrong"
grep -q "^sha=$SHA_NEW$" <<<"$out" && ok "dereferenced annotated tag -> commit sha" || no "sha wrong"
grep -q '^updated=true$' <<<"$out" && ok "updated=true" || no "updated flag"
grep -q "^ARG MONERO_BRANCH=v0.18.5.1$" "$TMP/Dockerfile" && ok "Dockerfile branch rewritten" || no "branch not written"
grep -q "^ARG MONERO_COMMIT_HASH=$SHA_NEW$" "$TMP/Dockerfile" && ok "Dockerfile sha rewritten" || no "sha not written"

echo "--- case 2: already current -> exit 2, no write"
before="$(cat "$TMP/Dockerfile")"
out="$(run)"; rc=$?
[ "$rc" = 2 ] && ok "exit 2 when up to date" || no "exit 2 (got $rc)"
grep -q '^updated=false$' <<<"$out" && ok "updated=false" || no "updated flag"
[ "$before" = "$(cat "$TMP/Dockerfile")" ] && ok "file untouched" || no "file mutated"

echo "--- case 3: --check reports without writing"
mkdf v0.18.4.6
out="$(run --check)"; rc=$?
[ "$rc" = 0 ] && ok "--check exit 0 when update available" || no "--check exit (got $rc)"
grep -q '^ARG MONERO_BRANCH=v0.18.4.6$' "$TMP/Dockerfile" && ok "--check left pin alone" || no "--check wrote file"

echo "--- case 4: missing pin is a hard error"
printf 'FROM alpine\n' > "$TMP/Dockerfile"
run >/dev/null; rc=$?
[ "$rc" = 1 ] && ok "exit 1 on missing pin" || no "exit 1 (got $rc)"

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
