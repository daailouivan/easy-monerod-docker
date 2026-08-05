#!/bin/sh
# easy-monerod-docker entrypoint
# Credit for the bulk of this script: cornfeedhobo/docker-monero (MIT)
set -e

# monerod must never prompt inside a container
set -- "monerod" "--non-interactive" "$@"

# Interleave NUMA memory if numactl is available (perf on multi-socket hosts)
if command -v numactl >/dev/null 2>&1; then
    set -- "numactl" "--interleave=all" "$@"
fi

# fixuid remaps the monero user to the host UID/GID of the mounted volume
exec fixuid -q "$@"
