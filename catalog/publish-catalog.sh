#!/bin/sh
# Copy baked /seed into the mounted catalog volume once, then idle.
set -eu

if [ ! -f /catalog/manifest.json ]; then
  echo "[ttb] publishing catalog into /catalog"
  mkdir -p /catalog
  cp -a /seed/. /catalog/
  echo "[ttb] catalog ready ($(wc -l < /catalog/manifest.txt | tr -d ' ') summary lines)"
else
  echo "[ttb] catalog volume already populated — skip"
fi

exec sleep infinity
