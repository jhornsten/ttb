# Torrent Test Bench (TTB)

Local Docker lab that runs a **shared catalog of synthetic torrents**, **in-compose BitTorrent trackers**, a **headless seeder**, and popular **client UIs** so you can pressure-test list/filter/detail flows and real peer downloads — without touching the public DHT.

**Clients:** Transmission, Deluge, qBittorrent, and optionally Flood + rTorrent.

Payloads are tiny random binaries generated at image build time. Announce URLs point at bench trackers only; DHT / PEX / LPD stay off.

## Requirements

- Docker Engine + Compose v2
- Several GB of disk for images + volumes (a 5k catalog is on the order of a few hundred MB of seed data)
- On Apple Silicon, the default opentracker image runs as `linux/amd64` via qemu

## Quick start

```bash
./scripts/build.sh                       # catalog + seeder + UI images (default 5000 torrents)
./scripts/up.sh transmission deluge qbittorrent
```

Omit clients you do not need. Flood is optional:

```bash
./scripts/up.sh transmission deluge qbittorrent flood
```

First boot publishes the catalog volume, the seeder loads the **full** catalog, then each UI client adds its boot slice (popular + per-client unique). At 5k torrents that is usually a few minutes. Markers in each config volume skip re-seeding on restart.

### Endpoints

| Client | URL | Credentials |
| --- | --- | --- |
| Transmission | http://127.0.0.1:9091 | `ttb` / `ttb` |
| Deluge | http://127.0.0.1:8112 | password `ttb` |
| qBittorrent | http://127.0.0.1:8080 | `ttb` / `ttb` |
| Flood (rTorrent) | http://127.0.0.1:3000 | no login (preconfigured rTorrent socket) |

Override host ports with `TRANSMISSION_PORT`, `DELUGE_WEB_PORT`, `QBITTORRENT_PORT`, `FLOOD_PORT` if something else is already bound (e.g. `QBITTORRENT_PORT=18080`).

Trackers and the headless seeder stay on the internal Compose network (no host ports).

### Stop / reset

```bash
docker compose --profile transmission --profile deluge --profile qbittorrent --profile flood down
# Wipe state (re-seed from catalog on next up):
docker compose --profile transmission --profile deluge --profile qbittorrent --profile flood down -v
```

## How the swarm is laid out

Default `CATALOG_COUNT=5000`, `TRACKER_COUNT=3`:

| Slice | Share | Complete at boot |
| --- | --- | --- |
| Popular | ~20% | Every UI client + seeder |
| Per-client unique | ~60% (split across UI clients) | That client + seeder |
| Download pool | ~20% | Seeder only, until a download batch |

Example with 5k and four UI client ids in the manifest: ~1000 popular, ~750 unique per client, ~1000 pool → each UI boots with ~1750 complete; the seeder holds all 5000.

Torrents are partitioned across trackers (`http://ttb-tracker-{0..N-1}:6969/announce`). Peers discover each other through those trackers only.

```text
  [ttb-catalog] ──► volume /catalog
        │
        ├─► seeder (Transmission, full catalog)
        ├─► transmission / deluge / qbittorrent / flood  (boot slices)
        └─► ttb-tracker-0 … N-1  (opentracker)
```

## Build knobs

```bash
CATALOG_COUNT=5000 TRACKER_COUNT=3 ./scripts/build.sh

# Larger payloads (disk/time scale with count × size):
CATALOG_COUNT=500 PAYLOAD_SIZE_MIN=50MB PAYLOAD_SIZE_MAX=200MB ./scripts/build.sh
./scripts/build.sh transmission deluge   # build only some UI images
```

| Variable | Default | Effect |
| --- | --- | --- |
| `CATALOG_COUNT` | `5000` | Torrents in the shared catalog |
| `TORRENT_SEED` | `42` | Reproducible generator RNG |
| `TRACKER_COUNT` | `3` | Announce targets (1–5); must match running trackers |
| `PAYLOAD_SIZE_MIN` | `1KiB` | Min payload bytes per torrent (`64KiB`, `50MB`, `1GiB`, or raw bytes) |
| `PAYLOAD_SIZE_MAX` | `48KiB` | Max payload bytes per torrent |
| `POPULAR_RATIO` | `0.20` | Shared boot slice |
| `POOL_RATIO` | `0.20` | Reserved for download batches |
| `TTB_CLIENTS` | `transmission,deluge,qbittorrent,flood` | Ids used for unique-role split |
| `TAG` | `local` | Image tag |

Piece length scales with payload size so `.torrent` piece lists stay reasonable. A catalog of hundreds of multi‑hundred‑MB torrents needs correspondingly large disk for `/catalog` and client download volumes.

Changing catalog size, payload range, trackers, or ratios requires a **catalog rebuild** and wiping **config volumes** so seed-once runs again against the new manifest.

## Download batches

After the seeder is up, add incomplete pool torrents to a UI client (it downloads from the seeder over the Compose network):

```bash
./scripts/download-batch.sh --client transmission --count 100
./scripts/download-batch.sh --client deluge --count 50
./scripts/download-batch.sh --client qbittorrent --count 50
# If qBittorrent is published on a non-default port:
./scripts/download-batch.sh --client qbittorrent --count 50 --qbit-url http://127.0.0.1:18080
```

Assignments are recorded in `dist/swarm-state.json` (gitignored) so the same pool infohashes are not re-issued to that client.

## Export images

```bash
./scripts/build.sh
./scripts/export-images.sh
# → dist/ttb-local.tar.gz
```

On another machine: `docker load -i images.tar`, pull `wiltonsr/opentracker:open` (and `jesec/rtorrent` + `jesec/flood` if you use Flood), then `./scripts/up.sh …`.

## Layout

```text
ttb/
  generator/           # catalog factory + slice helpers
  catalog/             # ttb-catalog image (publish into volume)
  clients/seeder/      # headless Transmission (full catalog)
  clients/transmission/
  clients/deluge/
  clients/qbittorrent/
  clients/flood/       # rTorrent config + flood-seed helper
  docker-compose.yml
  scripts/build.sh
  scripts/up.sh
  scripts/download-batch.sh
  scripts/export-images.sh
```

Add another UI client with `clients/<name>/`, a Compose profile, and a matching id in `TTB_CLIENTS`.

## Safety notes

- This is a **local lab**. Credentials are fixed lab defaults (`ttb` / `ttb`), not for exposure beyond localhost.
- Content is **synthetic**; torrents are marked private and only announce to in-bench trackers.
- Do not publish tracker or peer ports to the internet.

## Troubleshooting

| Symptom | What to try |
| --- | --- |
| Port already allocated | Set `QBITTORRENT_PORT` / `TRANSMISSION_PORT` / etc., then `up` again |
| Clients show an old torrent count after rebuild | `docker compose … down -v` and start fresh |
| qBittorrent seed-once never finishes | Check logs for WebUI password; image sets `ttb`/`ttb` on first boot |
| Trackers fail on ARM Macs | Expected to use `linux/amd64` emulation; ensure qemu/binfmt is available via Docker Desktop / OrbStack |

## License

MIT — see [LICENSE](LICENSE).
