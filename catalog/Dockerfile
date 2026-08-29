# syntax=docker/dockerfile:1
# Shared TTB catalog: payloads, .torrent files, manifest.json

ARG CATALOG_COUNT=5000
ARG TORRENT_SEED=42
ARG TRACKER_COUNT=3
ARG POPULAR_RATIO=0.20
ARG POOL_RATIO=0.20
ARG TTB_CLIENTS=transmission,deluge,qbittorrent,flood
ARG PAYLOAD_SIZE_MIN=1KiB
ARG PAYLOAD_SIZE_MAX=48KiB

FROM python:3.12-alpine AS generate
ARG CATALOG_COUNT
ARG TORRENT_SEED
ARG TRACKER_COUNT
ARG POPULAR_RATIO
ARG POOL_RATIO
ARG TTB_CLIENTS
ARG PAYLOAD_SIZE_MIN
ARG PAYLOAD_SIZE_MAX
WORKDIR /build
COPY generator/generate.py /build/generate.py
COPY generator/slice_lib.py /build/slice_lib.py
RUN python /build/generate.py \
      --count "${CATALOG_COUNT}" \
      --seed "${TORRENT_SEED}" \
      --tracker-count "${TRACKER_COUNT}" \
      --popular-ratio "${POPULAR_RATIO}" \
      --pool-ratio "${POOL_RATIO}" \
      --clients "${TTB_CLIENTS}" \
      --size-min "${PAYLOAD_SIZE_MIN}" \
      --size-max "${PAYLOAD_SIZE_MAX}" \
      --out /seed \
 && du -sh /seed/content /seed/torrents \
 && python -c "import json; m=json.load(open('/seed/manifest.json')); print('roles', m['role_counts']); print('size', m['size_min'], m['size_max'])"

FROM alpine:3.20
COPY --from=generate /seed /seed
COPY generator/slice_lib.py /seed/slice_lib.py
COPY catalog/publish-catalog.sh /usr/local/bin/publish-catalog
RUN chmod +x /usr/local/bin/publish-catalog
VOLUME ["/catalog"]
ENTRYPOINT ["/usr/local/bin/publish-catalog"]
LABEL org.opencontainers.image.title="ttb-catalog" \
      org.opencontainers.image.description="Shared torrent catalog for Torrent Test Bench"
