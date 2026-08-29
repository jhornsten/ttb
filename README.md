# Torrent Test Bench (TTB)

Docker swarm bench: a shared nonsense-torrent **catalog**, **N opentracker** instances,
a headless **seeder**, and popular BitTorrent **UI clients** (Transmission, Deluge,
qBittorrent, Flood+rTorrent). Point remote UIs/automation at the Web/RPC endpoints
and pressure-test list/filter/detail flows — plus real peer downloads via download batches.

## Quick start

```bash
./scripts/build.sh                  # catalog + seeder + all UI clients
./scripts/up.sh transmission deluge # or: qbittorrent flood …
```

First boot publishes the catalog volume, the seeder loads the full set, then each UI
client adds its boot slice (popular + per-client unique). That can take several minutes
at 5k torrents. A marker in each config volume skips re-seeding on restart.

### Endpoints

| Client | URL | Credentials |
| --- | --- | --- |
| Transmission | `http://127.0.0.1:9091` | user `ttb` / password `ttb` |
| Deluge | `http://127.0.0.1:8112` | password `ttb` |
| qBittorrent | `http://127.0.0.1:8080` | user `ttb` / password `ttb` |
| Flood | `http://127.0.0.1:3000` | create a local account on first visit |

Trackers and the headless seeder stay on the internal Docker network (no host ports).
The default opentracker image is `linux/amd64` (runs via qemu on Apple Silicon).

## Catalog layout

Default `CATALOG_COUNT=5000`, `TRACKER_COUNT=3`:

| Slice | Share | Who has it complete at boot |
| --- | --- | --- |
| Popular | ~20% | Every UI client + seeder |
| Per-client unique | ~60% split across UI clients | That client + seeder |
| Download pool | ~20% | Seeder only until a batch |

Torrents are partitioned across trackers (`http://ttb-tracker-{0..N-1}:6969/announce`).
DHT / PEX / LPD stay disabled — peers meet via trackers only.

### Build knobs

```bash
CATALOG_COUNT=5000 TRACKER_COUNT=3 ./scripts/build.sh
```

| Variable | Default | Effect |
| --- | --- | --- |
| `CATALOG_COUNT` | `5000` | Torrents in the shared catalog |
| `TORRENT_SEED` | `42` | Reproducible RNG |
| `TRACKER_COUNT` | `3` | 1–5 opentracker announce targets |
| `POPULAR_RATIO` | `0.20` | Shared boot slice |
| `POOL_RATIO` | `0.20` | Reserved for download batches |
| `TTB_CLIENTS` | `transmission,deluge,qbittorrent,flood` | Unique-role split |

Rebuild the catalog image when changing these. Wipe client/seeder **config volumes**
so seed-once runs again against the new manifest.

## Download batches

After the seeder is up, push incomplete pool torrents onto a UI client:

```bash
./scripts/download-batch.sh --client deluge --count 50
./scripts/download-batch.sh --client transmission --count 100
```

The seeder already has the bytes; the leecher announces, finds peers, and downloads
inside the compose network. Assignments are recorded in `dist/swarm-state.json`.

## Ship without the repo

```bash
./scripts/build.sh
./scripts/export-images.sh
# → dist/ttb-local.tar.gz
```

On another machine: `docker load`, pull `wiltonsr/opentracker`, `jesec/rtorrent`,
`jesec/flood`, then `./scripts/up.sh …`.

## Layout

```
ttb/
  generator/generate.py       # catalog factory + roles/trackers
  generator/slice_lib.py      # manifest helpers
  catalog/                    # ttb-catalog image
  clients/seeder/             # headless Transmission (full catalog)
  clients/transmission/
  clients/deluge/
  clients/qbittorrent/
  clients/flood/              # rTorrent config + flood-seed helper
  docker-compose.yml
  scripts/build.sh
  scripts/up.sh
  scripts/download-batch.sh
  scripts/export-images.sh
```

Add another UI client later with `clients/<name>/`, a compose profile, and a matching
id in `TTB_CLIENTS`.
