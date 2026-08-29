#!/usr/bin/env bash
# Seed Transmission with pre-generated nonsense torrents once per config volume.
set -euo pipefail

SEED_ROOT="${SEED_ROOT:-/seed}"
DOWNLOADS="${DOWNLOADS:-/downloads}"
CONFIG="${CONFIG:-/config}"
MARKER="${CONFIG}/.ttb-seeded"
RPC_USER="${USER:-ttb}"
RPC_PASS="${PASS:-ttb}"
RPC=(transmission-remote 127.0.0.1:9091 --auth "${RPC_USER}:${RPC_PASS}")

log() { echo "[ttb] $*"; }

wait_rpc() {
  local i
  for i in $(seq 1 90); do
    if "${RPC[@]}" --session-info >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  log "RPC never became ready"
  return 1
}

seed_torrents() {
  if [[ -f "${MARKER}" ]]; then
    log "Already seeded ($(cat "${MARKER}")) — skip"
    return 0
  fi

  shopt -s nullglob
  local torrents=("${SEED_ROOT}/torrents"/*.torrent)
  local total=${#torrents[@]}
  if [[ "${total}" -eq 0 ]]; then
    log "No .torrent files under ${SEED_ROOT}/torrents"
    return 1
  fi

  log "Adding ${total} torrents…"
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
  wait_rpc
  seed_torrents
  exec sleep infinity
fi

wait_rpc
seed_torrents
