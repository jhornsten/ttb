#!/usr/bin/env bash
# Start TTB infrastructure + requested UI client profiles.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ $# -eq 0 ]]; then
  set -- transmission deluge qbittorrent flood
fi

PROFILES=()
for c in "$@"; do
  PROFILES+=(--profile "$c")
done

docker compose "${PROFILES[@]}" up -d
docker compose "${PROFILES[@]}" ps

echo
echo "Web UIs (when started):"
echo "  Transmission  http://127.0.0.1:${TRANSMISSION_PORT:-9091}  ttb / ttb"
echo "  Deluge        http://127.0.0.1:${DELUGE_WEB_PORT:-8112}     password ttb"
echo "  qBittorrent   http://127.0.0.1:${QBITTORRENT_PORT:-8080}    ttb / ttb"
echo "  Flood         http://127.0.0.1:${FLOOD_PORT:-3000}          no login (rTorrent via socket)"
echo
echo "First boot: wait for catalog publish, then seeder/UI seed-once (can take several minutes)."
