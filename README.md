# easy-monerod-docker

A simple, statically-built `monerod` Docker image on Alpine — **that keeps itself on the newest Monero release.**

This is a rewrite of [`sethsimmons/simple-monerod`](https://hub.docker.com/r/sethsimmons/simple-monerod)
using the same build logic, pinned to the latest tag from
[monero-project/monero](https://github.com/monero-project/monero/tags), plus an
automatic update pipeline the original doesn't ship.

Current pin: **v0.18.5.1** (`4f92268d`)

---

## Quick start

```bash
docker run -d --restart unless-stopped --name monerod \
  -v bitmonero:/home/monero/.bitmonero \
  -p 18080:18080 -p 18089:18089 \
  daailouivan/easy-monerod:latest
```

The baked-in `CMD` already sets sane defaults:

```
--rpc-restricted-bind-ip=0.0.0.0 --rpc-restricted-bind-port=18089
--no-igd --no-zmq --enable-dns-blocklist --ban-list=/home/monero/ban_list.txt
```

Anything you append replaces them, so pass the full set when overriding.

### Public node

```bash
docker run -d --restart unless-stopped --name monerod \
  -v bitmonero:/home/monero/.bitmonero -p 18080:18080 -p 18089:18089 \
  daailouivan/easy-monerod:latest \
  --rpc-restricted-bind-ip=0.0.0.0 --rpc-restricted-bind-port=18089 \
  --public-node --no-igd --no-zmq --enable-dns-blocklist \
  --ban-list=/home/monero/ban_list.txt
```

### Pruned

Append `--prune-blockchain` to either form above.

### Compose (recommended — includes runtime auto-update)

```bash
docker compose up -d
```

---

## Tags

| Tag         | Contents                                                    |
|-------------|-------------------------------------------------------------|
| `latest`    | Newest tagged Monero release, Alpine base                    |
| `alpine`    | Same as `latest`                                             |
| `vX.Y.Z.W`  | That specific Monero release, Alpine base                    |

Multi-arch: `linux/amd64` and `linux/arm64`.

---

## Automatic updates

Two independent halves — use either or both.

### 1. Image side (CI) — `.github/workflows/auto-update.yml`

Runs daily at 06:00 UTC (and on demand):

1. `scripts/check-update.sh` queries the GitHub API for the newest **stable**
   `vX.Y.Z.W` tag (release candidates and `release-v*` branches are filtered out).
2. It dereferences the annotated tag to its real commit SHA and rewrites the
   pin block in the `Dockerfile`.
3. If the pin changed, the bump is committed to `main` and a multi-arch image is
   built and pushed as `latest`, `alpine` and `vX.Y.Z.W`.

The Dockerfile still hard-verifies the checkout:

```dockerfile
test "$(git rev-parse HEAD)" = "${MONERO_COMMIT_HASH}" || exit 1
```

so a bump that resolves to an unexpected commit fails the build rather than
shipping it.

**Required repo secrets:** `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.
Optional repo variable: `DOCKERHUB_USERNAME` (image namespace, defaults to `daailouivan`).

### 2. Container side (runtime) — Watchtower

`docker-compose.yml` ships an opt-in Watchtower that polls the registry every 6h
and recreates `monerod` when a new image is published. It is label-scoped
(`WATCHTOWER_LABEL_ENABLE=true`), so it only ever touches the monerod container —
nothing else on your host.

Drop the `watchtower` service if you'd rather pull manually.

### Running the check by hand

```bash
scripts/check-update.sh --check   # report only, never writes
scripts/check-update.sh           # rewrite the Dockerfile pin
```

Exit codes: `0` update applied/available · `2` already current · `1` error.
Stdout is machine-readable (`current=` / `latest=` / `sha=` / `updated=`).

---

## What's in the image

- **Statically linked `monerod`**, built from source against a static
  expat + libunbound, so the final layer is a bare Alpine with no build toolchain.
- **PGP-verified ban list** — [Boog900/monero-ban-list](https://github.com/Boog900/monero-ban-list),
  checked against boog900, Rucknium and jeffro256 signatures at build time, and
  wired in via `--ban-list`.
- **`fixuid`** so the bind-mounted blockchain directory gets the host's UID/GID
  instead of root-owned files.
- **Healthcheck** that reads the daemon's own cmdline from PID 1, so it follows
  your `--rpc-bind-port` / `--rpc-login` without any compose-file duplication.
- Runs as the unprivileged `monero` user.

## Ports

| Port    | Purpose            |
|---------|--------------------|
| `18080` | p2p                |
| `18089` | restricted RPC     |

## Building locally

```bash
docker build -t easy-monerod:local .
# limit parallelism on small machines:
docker build --build-arg NPROC=4 -t easy-monerod:local .
```

## Tests

```bash
bash tests/test-check-update.sh
```

Stubs the GitHub API (no network) and asserts the updater's full contract:
tag selection with RC filtering, annotated-tag dereferencing, in-place pin
rewrite, `--check` being read-only, up-to-date exit code, and hard failure on a
missing pin.

---

## Credits

- [sethsimmons/simple-monerod-docker](https://github.com/sethsimmons/simple-monerod-docker) — the build logic this rewrites
- [leonardochaia/docker-monerod](https://github.com/leonardochaia/docker-monerod) — original Dockerfile base
- [cornfeedhobo/docker-monero](https://github.com/cornfeedhobo/docker-monero) — Alpine migration and entrypoint
- [Boog900/monero-ban-list](https://github.com/Boog900/monero-ban-list) — ban list

## License

MIT — see [LICENSE](LICENSE). Monero itself is licensed
[here](https://github.com/monero-project/monero/blob/master/LICENSE).
