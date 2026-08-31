#!/usr/bin/env bash
# Export TTB images + prebuilt compose as a portable tarball.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${TAG:-local}"
OUT="${1:-$ROOT/dist/ttb-${TAG}.tar.gz}"

mkdir -p "$(dirname "$OUT")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

IMAGES=()
for name in ttb-catalog ttb-seeder ttb-transmission ttb-deluge ttb-qbittorrent ttb-flood; do
  if docker image inspect "${name}:${TAG}" >/dev/null 2>&1; then
    IMAGES+=("${name}:${TAG}")
  fi
done

if [[ ${#IMAGES[@]} -eq 0 ]]; then
  echo "No ttb-*:${TAG} images found. Run ./scripts/build.sh first." >&2
  exit 1
fi

echo "Saving ${IMAGES[*]}…"
docker save "${IMAGES[@]}" -o "${TMP}/images.tar"

cp "$ROOT/docker-compose.prebuilt.yml" "${TMP}/docker-compose.yml"
mkdir -p "${TMP}/scripts" "${TMP}/clients/flood"
cp "$ROOT/scripts/up.sh" "${TMP}/scripts/up.sh"
cp "$ROOT/scripts/download-batch.sh" "${TMP}/scripts/download-batch.sh"
cp "$ROOT/scripts/download-batch.py" "${TMP}/scripts/download-batch.py"
cp "$ROOT/generator/slice_lib.py" "${TMP}/scripts/slice_lib.py"
cp "$ROOT/clients/flood/rtorrent.rc" "${TMP}/clients/flood/rtorrent.rc"
chmod +x "${TMP}/scripts/up.sh" "${TMP}/scripts/download-batch.sh"

# download-batch imports generator/slice_lib — provide a tiny shim layout
mkdir -p "${TMP}/generator"
cp "$ROOT/generator/slice_lib.py" "${TMP}/generator/slice_lib.py"

cat >"${TMP}/README.txt" <<EOF
Torrent Test Bench (TTB) — prebuilt shared-catalog swarm
=======================================================

1. docker load -i images.tar
2. Pull runtime images if needed:
     docker pull wiltonsr/opentracker:open
     docker pull jesec/rtorrent:latest   # only if using flood
     docker pull jesec/flood:latest      # only if using flood
3. ./scripts/up.sh transmission deluge qbittorrent
   (add "flood" if desired)

Endpoints (defaults):
  Transmission  http://127.0.0.1:9091   ttb / ttb
  Deluge        http://127.0.0.1:8112   password ttb
  qBittorrent   http://127.0.0.1:8080   ttb / ttb
  Flood         http://127.0.0.1:3000   no login (preconfigured rTorrent socket)

Download batch (after seeder is up):
  ./scripts/download-batch.sh --client transmission --count 50

Wipe client/seeder config volumes when loading a new catalog image.
Lab-only credentials; keep bound to localhost.
EOF

echo "Packing ${OUT}…"
tar -C "$TMP" -czf "$OUT" images.tar docker-compose.yml scripts generator clients README.txt
ls -lh "$OUT"
echo "Done."
