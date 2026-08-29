# syntax=docker/dockerfile:1
# TTB Transmission UI client — boots popular + unique:transmission from shared catalog.

FROM linuxserver/transmission:latest

COPY clients/transmission/settings.json /defaults/settings.json
COPY scripts/link-slice.sh /usr/local/bin/ttb-link-slice
COPY clients/transmission/10-link-catalog /custom-cont-init.d/10-link-catalog
COPY clients/seeder/seed-once.sh /usr/local/bin/ttb-seed-once
COPY clients/transmission/ttb-seed /custom-services.d/ttb-seed
COPY generator/slice_lib.py /usr/local/lib/ttb/slice_lib.py
RUN chmod +x \
      /usr/local/bin/ttb-link-slice \
      /usr/local/bin/ttb-seed-once \
      /custom-cont-init.d/10-link-catalog \
      /custom-services.d/ttb-seed \
 && mkdir -p /usr/local/lib/ttb

ENV PUID=1000 \
    PGID=1000 \
    TZ=UTC \
    USER=ttb \
    PASS=ttb \
    PEERPORT=51413 \
    CATALOG_ROOT=/catalog \
    TTB_CLIENT_ID=transmission \
    PYTHONPATH=/usr/local/lib/ttb

EXPOSE 9091 51413 51413/udp
VOLUME ["/config", "/downloads", "/catalog"]

LABEL org.opencontainers.image.title="ttb-transmission" \
      org.opencontainers.image.description="Transmission UI client for Torrent Test Bench"
