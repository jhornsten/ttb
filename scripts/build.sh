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
export TAG="${TAG:-local}"

if [[ $# -eq 0 ]]; then
  CLIENTS=(transmission deluge qbittorrent flood)
else
  CLIENTS=("$@")
fi

echo "Building ttb-*:${TAG}"
echo "  CATALOG_COUNT=${CATALOG_COUNT} TRACKER_COUNT=${TRACKER_COUNT}"
echo "  clients=${CLIENTS[*]}"

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
