#!/usr/bin/env bash
# Wrapper: ./scripts/download-batch.sh --client deluge --count 50
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/download-batch.py" "$@"
