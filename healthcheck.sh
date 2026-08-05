#!/bin/sh
# Healthcheck for monerod that supports --rpc-login.
# RPC port and credentials are read from the running daemon's cmdline (PID 1),
# so the check follows the container's own configuration with no overrides.
set -eu

# Print the value of a daemon argument, handling "--flag=value" and "--flag value".
get_arg() {
    tr '\0' '\n' < /proc/1/cmdline | awk -v flag="$1" '
        prev == flag { print; exit }
        index($0, flag "=") == 1 { print substr($0, length(flag) + 2); exit }
        { prev = $0 }
    '
}

RPC_LOGIN="$(get_arg --rpc-login)"
RPC_PORT="$(get_arg --rpc-bind-port)"
RPC_URL="http://127.0.0.1:${RPC_PORT:-18081}/get_height"

if [ -n "${RPC_LOGIN}" ]; then
    curl --fail --silent --digest --user "${RPC_LOGIN}" "${RPC_URL}"
else
    # Credentials may be set via --config-file, which is not readable here;
    # a 401 still proves the RPC server is alive.
    status="$(curl --silent --output /dev/null --write-out '%{http_code}' "${RPC_URL}")"
    [ "${status}" = "200" ] || [ "${status}" = "401" ]
fi
