# syntax=docker/dockerfile:1
# Headless Transmission seeder — full catalog, no host Web UI publish.

FROM linuxserver/transmission:latest

COPY clients/transmission/settings.json /defaults/settings.json
COPY clients/seeder/settings-overrides.sh /custom-cont-init.d/05-ttb-seeder-settings
COPY scripts/link-slice.sh /usr/local/bin/ttb-link-slice
COPY clients/seeder/10-link-catalog /custom-cont-init.d/10-link-catalog
COPY clients/seeder/seed-once.sh /usr/local/bin/ttb-seed-once
COPY clients/seeder/ttb-seed /custom-services.d/ttb-seed
COPY generator/slice_lib.py /usr/local/lib/ttb/slice_lib.py
RUN chmod +x \
      /usr/local/bin/ttb-link-slice \
      /usr/local/bin/ttb-seed-once \
      /custom-cont-init.d/05-ttb-seeder-settings \
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
    TTB_CLIENT_ID=all \
    PYTHONPATH=/usr/local/lib/ttb

EXPOSE 9091 51413 51413/udp
VOLUME ["/config", "/downloads", "/catalog"]

LABEL org.opencontainers.image.title="ttb-seeder" \
      org.opencontainers.image.description="Headless Transmission seeder for TTB catalog"
