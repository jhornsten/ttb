#!/usr/bin/env bash
# Build TTB catalog + client/seeder images.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export CATALOG_COUNT="${CATALOG_COUNT:-${TORRENT_COUNT:-5000}}"
export TORRENT_SEED="${TORRENT_SEED:-42}"
export TRACKER_COUNT="${TRACKER_COUNT:-3}"
export POPULAR_RATIO="${POPULAR_RATIO:-0.20}"
export POOL_RATIO="${POOL_RATIO:-0.20}"
export TTB_CLIENTS="${TTB_CLIENTS:-transmission,deluge,qbittorrent,flood}"
export PAYLOAD_SIZE_MIN="${PAYLOAD_SIZE_MIN:-1KiB}"
export PAYLOAD_SIZE_MAX="${PAYLOAD_SIZE_MAX:-48KiB}"
export TAG="${TAG:-local}"

if [[ $# -eq 0 ]]; then
  CLIENTS=(transmission deluge qbittorrent flood)
else
  CLIENTS=("$@")
fi

echo "Building ttb-*:${TAG}"
echo "  CATALOG_COUNT=${CATALOG_COUNT} TRACKER_COUNT=${TRACKER_COUNT}"
echo "  PAYLOAD_SIZE=${PAYLOAD_SIZE_MIN}..${PAYLOAD_SIZE_MAX}"
echo "  clients=${CLIENTS[*]}"

# Abort before Docker build if the catalog cannot fit (worst-case + headroom).
python3 "$ROOT/generator/generate.py" \
  --check-disk \
  --count "${CATALOG_COUNT}" \
  --size-min "${PAYLOAD_SIZE_MIN}" \
  --size-max "${PAYLOAD_SIZE_MAX}" \
  --out "$ROOT"

docker compose build catalog
docker compose build seeder

for c in "${CLIENTS[@]}"; do
  case "$c" in
    flood)
      docker compose --profile flood build flood-seed
      ;;
    *)
      docker compose --profile "$c" build "$c"
      ;;
  esac
done

echo "Start with: ./scripts/up.sh ${CLIENTS[*]}"
