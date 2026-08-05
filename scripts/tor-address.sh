#!/usr/bin/env bash
# tor-address.sh — print the onion addresses published by the tor container.
#
# The hidden-service keys live in the tor-keys volume, so the addresses are
# stable across restarts. Run after `docker compose -f docker-compose.tor.yml
# up -d tor` and give Tor ~20s to bootstrap.
set -euo pipefail

FILE="${COMPOSE_FILE:-docker-compose.tor.yml}"
SVC="${TOR_SERVICE:-tor}"

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose -f "$FILE" "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose -f "$FILE" "$@"
    else
        echo "error: docker compose not found" >&2; exit 1
    fi
}

# Hidden service dirs are named after the HS_* env vars (HS_MONEROD_RPC ->
# MONEROD_RPC). List whatever the container actually created rather than
# assuming names.
dirs="$(compose exec -T "$SVC" sh -c 'ls -1 /var/lib/tor 2>/dev/null' | tr -d '\r' || true)"
if [ -z "${dirs}" ]; then
    echo "No hidden services yet. Is the tor container running?" >&2
    echo "  docker compose -f ${FILE} up -d ${SVC}" >&2
    exit 1
fi

found=0
for d in ${dirs}; do
    host="$(compose exec -T "$SVC" sh -c "cat /var/lib/tor/${d}/hostname 2>/dev/null" | tr -d '\r' || true)"
    case "${host}" in
        *.onion)
            found=1
            printf '%-16s %s\n' "${d}" "${host}"
            ;;
    esac
done

if [ "${found}" -eq 0 ]; then
    echo "Tor is still bootstrapping — no hostname files yet. Wait ~20s and retry." >&2
    exit 1
fi

cat <<'EOF'

Use them like this:

  RPC  (wallet):   monero-wallet-cli --proxy 127.0.0.1:9050 \
                     --daemon-address <MONEROD_RPC>.onion:18089

  P2P  (inbound):  add to a .env file next to the compose file, then
                   re-create monerod so it advertises the address:

                     ANONYMOUS_INBOUND=<MONEROD_P2P>.onion:18084,127.0.0.1:18084,25

Back up the tor-keys volume to keep these addresses; never share the keys.
EOF
