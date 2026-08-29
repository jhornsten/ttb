#!/usr/bin/env bash
# Seed Transmission with the full catalog (or a client slice) once per config volume.
set -euo pipefail

CATALOG="${CATALOG_ROOT:-/catalog}"
DOWNLOADS="${DOWNLOADS:-/downloads}"
CONFIG="${CONFIG:-/config}"
MARKER="${CONFIG}/.ttb-seeded"
CLIENT_ID="${TTB_CLIENT_ID:-all}"
RPC_USER="${USER:-ttb}"
RPC_PASS="${PASS:-ttb}"
RPC=(transmission-remote 127.0.0.1:9091 --auth "${RPC_USER}:${RPC_PASS}")
export PYTHONPATH="${PYTHONPATH:-/usr/local/lib/ttb}:${CATALOG}"

log() { echo "[ttb] $*"; }

wait_rpc() {
  local i
  for i in $(seq 1 120); do
    if "${RPC[@]}" --session-info >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  log "RPC never became ready"
  return 1
}

wait_catalog() {
  local i
  for i in $(seq 1 180); do
    if [[ -f "${CATALOG}/manifest.json" ]]; then
      return 0
    fi
    sleep 1
  done
  log "catalog never appeared at ${CATALOG}"
  return 1
}

list_torrents() {
  python3 - "${CATALOG}" "${CLIENT_ID}" <<'PY'
import json, sys
from pathlib import Path
catalog = Path(sys.argv[1])
client = sys.argv[2]
sys.path.insert(0, str(catalog))
sys.path.insert(0, "/usr/local/lib/ttb")
from slice_lib import all_entries, boot_entries, torrent_path
manifest = json.loads((catalog / "manifest.json").read_text())
entries = all_entries(manifest) if client == "all" else boot_entries(manifest, client)
for e in entries:
    print(torrent_path(catalog, e))
PY
}

seed_torrents() {
  if [[ -f "${MARKER}" ]]; then
    log "Already seeded ($(cat "${MARKER}")) — skip"
    return 0
  fi

  mapfile -t torrents < <(list_torrents)
  local total=${#torrents[@]}
  if [[ "${total}" -eq 0 ]]; then
    log "No torrents selected for client=${CLIENT_ID}"
    return 1
  fi

  log "Adding ${total} torrents (client=${CLIENT_ID})…"
  local i=0
  local f
  for f in "${torrents[@]}"; do
    "${RPC[@]}" --add "${f}" --download-dir "${DOWNLOADS}" >/dev/null 2>&1 || true
    i=$((i + 1))
    if (( i % 100 == 0 )) || (( i == total )); then
      log "  ${i}/${total}"
    fi
  done

  sleep 2
  "${RPC[@]}" --torrent all --verify >/dev/null 2>&1 || true
  echo "${total}" >"${MARKER}"
  log "Seed complete (${total} torrents)"
}

if [[ "${1:-}" == "--sidecar" ]]; then
  wait_catalog
  wait_rpc
  seed_torrents
  exec sleep infinity
fi

wait_catalog
wait_rpc
seed_torrents
