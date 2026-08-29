#!/bin/sh
set -eu
mode="${1:-seed}"
case "$mode" in
  seed)
    exec python3 /usr/local/bin/ttb-seed-once.py --sidecar
    ;;
  *)
    exec "$@"
    ;;
esac
