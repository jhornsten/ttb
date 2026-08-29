#!/usr/bin/env bash
# Link catalog content entries into DOWNLOADS for a client slice (or all).
# Usage: link-slice.sh <client_id|all> [catalog_root] [downloads]
set -euo pipefail

CLIENT_ID="${1:?client id or all}"
CATALOG="${2:-${CATALOG_ROOT:-/catalog}}"
DOWNLOADS="${3:-${DOWNLOADS:-/downloads}}"

mkdir -p "${DOWNLOADS}" "${DOWNLOADS}/complete" "${DOWNLOADS}/incomplete"
MARKER="${DOWNLOADS}/.seed-linked"

if [[ -e "${MARKER}" ]]; then
  exit 0
fi

if [[ ! -f "${CATALOG}/manifest.json" ]]; then
  echo "[ttb] no manifest at ${CATALOG}/manifest.json" >&2
  exit 1
fi

echo "[ttb] linking catalog content for ${CLIENT_ID} into ${DOWNLOADS}"
python3 - "${CATALOG}" "${CLIENT_ID}" "${DOWNLOADS}" <<'PY'
import json, os, sys
from pathlib import Path

catalog = Path(sys.argv[1])
client = sys.argv[2]
downloads = Path(sys.argv[3])
manifest = json.loads((catalog / "manifest.json").read_text())
sys.path.insert(0, str(catalog))
try:
    from slice_lib import all_entries, boot_entries
except ImportError:
    sys.path.insert(0, "/seed")
    from slice_lib import all_entries, boot_entries

entries = all_entries(manifest) if client == "all" else boot_entries(manifest, client)
for e in entries:
    src = catalog / "content" / e["content"]
    dst = downloads / e["content"]
    if src.exists() and not dst.exists():
        dst.symlink_to(src)
print(f"[ttb] linked {len(entries)} content paths")
PY

touch "${MARKER}"
