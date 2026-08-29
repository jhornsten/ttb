# syntax=docker/dockerfile:1
# Flood UI + rTorrent seed sidecar helpers for TTB.

FROM python:3.12-alpine

RUN apk add --no-cache bash
COPY generator/slice_lib.py /usr/local/lib/ttb/slice_lib.py
COPY scripts/link-slice.sh /usr/local/bin/ttb-link-slice
COPY clients/flood/seed-once.py /usr/local/bin/ttb-seed-once.py
COPY clients/flood/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/ttb-link-slice /usr/local/bin/docker-entrypoint.sh \
 && chmod 644 /usr/local/bin/ttb-seed-once.py \
 && mkdir -p /usr/local/lib/ttb

ENV CATALOG_ROOT=/catalog \
    TTB_CLIENT_ID=flood \
    DOWNLOADS=/downloads \
    CONFIG=/config \
    RTORRENT_SOCKET=/run/rtorrent/rtorrent.sock \
    PYTHONPATH=/usr/local/lib/ttb \
    FLOOD_PASSWORD=ttb

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["seed"]

LABEL org.opencontainers.image.title="ttb-flood" \
      org.opencontainers.image.description="Flood/rTorrent seed helper for Torrent Test Bench"
