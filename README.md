# easy-monerod-docker

A simple, statically-built `monerod` Docker image on Alpine — **that keeps itself on the newest Monero release.**

This is a rewrite of [`sethsimmons/simple-monerod`](https://hub.docker.com/r/sethsimmons/simple-monerod)
using the same build logic, pinned to the latest tag from
[monero-project/monero](https://github.com/monero-project/monero/tags), plus an
automatic update pipeline the original doesn't ship.

```
ghcr.io/daailouivan/easy-monerod:latest
```

| | |
|---|---|
| **Image** | `ghcr.io/daailouivan/easy-monerod` |
| **Monero** | v0.18.5.1 (`4f92268d`) |
| **Platforms** | `linux/amd64`, `linux/arm64` |
| **Size** | ~17 MB |

Published to the GitHub Container Registry. Public — no login needed to pull.

---

## Install

### 1. Pull

```bash
docker pull ghcr.io/daailouivan/easy-monerod:latest
```

### 2. Run

```bash
docker run -d --restart unless-stopped --name monerod \
  -v bitmonero:/home/monero/.bitmonero \
  -p 18080:18080 -p 18089:18089 \
  ghcr.io/daailouivan/easy-monerod:latest
```

### 3. Verify it's syncing

```bash
docker logs -f monerod                      # follow startup
docker inspect --format='{{.State.Health.Status}}' monerod   # -> healthy
curl -s http://127.0.0.1:18089/get_height   # -> {"height":...,"status":"OK"}
```

The container reports `starting` until the first healthcheck passes, then
`healthy`. Initial sync takes hours to days; `--prune-blockchain` cuts the
storage roughly in half.

### Migrating from `sethsimmons/simple-monerod`

Drop-in — same `monero` user, same `/home/monero/.bitmonero` data path, same
`fixuid` UID remapping. Point the new image at your existing volume; **no
resync**:

```bash
docker stop monerod && docker rm monerod
# then run the command above with your existing -v volume
```

Keep whatever flags you were already passing; the defaults below are identical
to upstream's apart from the added `--ban-list`.

---

## Usage

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
  ghcr.io/daailouivan/easy-monerod:latest \
  --rpc-restricted-bind-ip=0.0.0.0 --rpc-restricted-bind-port=18089 \
  --public-node --no-igd --no-zmq --enable-dns-blocklist \
  --ban-list=/home/monero/ban_list.txt
```

### Pruned

Append `--prune-blockchain` to either form above.

### Compose

Two stacks are provided — pick the one that matches your host.

```bash
git clone https://github.com/daailouivan/easy-monerod-docker
cd easy-monerod-docker
```

One `docker-compose.yml` covers every setup — the variants ship commented out,
each labelled with a marker you can search for.

**Standard Docker host** — named volume, Watchtower included. No edits needed:

```bash
docker compose up -d
```

**Synology NAS** — uncomment the `(A) SYNOLOGY` lines: `user:`, the
`./bitmonero` bind mount (and comment the named volume above it), and the
`networks:` / `host_bridge` blocks.

```bash
mkdir -p bitmonero
chown -R 1026:100 bitmonero          # match your DSM user; check with: id <user>
docker compose up -d
```

DSM accounts start at uid 1026 (group `users` = gid 100), so the container
needs an explicit `user:`; the bind mount puts the blockchain in a Shared
Folder you can browse and back up from DSM.

**Tor** — uncomment the `(B) TOR` lines: the `tor:` service, `--tx-proxy`,
`--anonymous-inbound`, `depends_on`, the loopback RPC port (comment the plain
`18089:18089` above it), and the `tor-keys` volume.

```bash
docker compose up -d tor
sleep 20 && ./scripts/tor-address.sh
docker compose up -d
```

| Marker | Enables |
|---|---|
| *(default)* | named volume, RPC on the LAN, Watchtower |
| `(A) SYNOLOGY` | bind mount, explicit uid:gid, named bridge |
| `(B) TOR` | onion RPC, Tor tx broadcast, inbound onion peers |
| `(C) COMMON OPTIONS` | `--public-node`, `--prune-blockchain` |

A and B combine: apply both sets of lines, and also uncomment the tor
service's own `networks:` block.

Override the image on either stack without editing the file:

```bash
MONEROD_IMAGE=ghcr.io/daailouivan/easy-monerod:v0.18.5.1 docker compose up -d
```

### Tor

The `(B) TOR` block implements all three capabilities described in
[`docs/ANONYMITY_NETWORKS.md`](https://github.com/monero-project/monero/blob/master/docs/ANONYMITY_NETWORKS.md):

| Capability | Mechanism |
|---|---|
| Wallets reach the node over Tor | RPC hidden service -> `<onion>:18089` |
| Your transactions broadcast over Tor | `--tx-proxy=tor,tor:9050,10` |
| Accept inbound onion peers | `--anonymous-inbound` on port **18084** |

Two details the docs are explicit about, and that a bare hidden-service
container does **not** give you:

- **An onion address alone does not anonymise your transactions.** That needs
  `--tx-proxy`, which routes your own broadcasts through the Tor SOCKS proxy.
- **`--anonymous-inbound` must use a dedicated port** (18084 here), never the
  clearnet p2p port 18080.

**The blockchain still syncs over clearnet IPv4.** monerod does not support
syncing over hidden services — it relies on IPv4 to make Sybil attacks harder.
Tor anonymises *transaction origin*, not the fact that you run a node.

Get your addresses:

```bash
./scripts/tor-address.sh
```

To advertise your onion to peers, put the P2P address in `.env` beside the
compose file and re-create monerod:

```bash
echo "ANONYMOUS_INBOUND=<p2p-onion>.onion:18084,127.0.0.1:18084,25" > .env
docker compose up -d
```

Optional — without it you still get the RPC onion and Tor tx broadcast, you
just do not accept inbound onion peers. The `tor-keys` volume holds your onion
keys: back it up to keep the same address, and never share it.

---

## Tags

All tags live under `ghcr.io/daailouivan/easy-monerod`.

| Tag         | Contents                                                     |
|-------------|--------------------------------------------------------------|
| `latest`    | Newest tagged Monero release, Alpine base                    |
| `alpine`    | Same as `latest`                                             |
| `vX.Y.Z.W`  | That specific Monero release (e.g. `v0.18.5.1`), Alpine base |

Pin to `vX.Y.Z.W` if you want to control exactly when your node upgrades;
use `latest` if you want it to follow releases.

Every tag is a multi-arch manifest covering `linux/amd64` and `linux/arm64`,
so the same reference works on x86 servers and ARM boards alike.

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

**No secrets required.** Publishing uses GHCR with the per-run `GITHUB_TOKEN`,
which GitHub mints for each run, scopes to this repository, and expires when the
run ends — so no long-lived registry credential is stored in this repo.

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
