# syntax=docker/dockerfile:1
# TTB Deluge UI client — boots popular + unique:deluge from shared catalog.

FROM linuxserver/deluge:latest

COPY clients/deluge/core.conf /defaults/core.conf
COPY clients/deluge/web.conf.template /defaults/web.conf.template
COPY scripts/link-slice.sh /usr/local/bin/ttb-link-slice
COPY clients/deluge/10-link-catalog /custom-cont-init.d/10-link-catalog
COPY clients/deluge/seed-once.py /usr/local/bin/ttb-seed-once.py
COPY clients/deluge/ttb-seed /custom-services.d/ttb-seed
COPY clients/deluge/install-defaults.sh /custom-cont-init.d/05-ttb-defaults
COPY generator/slice_lib.py /usr/local/lib/ttb/slice_lib.py
RUN chmod +x \
      /usr/local/bin/ttb-link-slice \
      /custom-cont-init.d/10-link-catalog \
      /custom-services.d/ttb-seed \
      /custom-cont-init.d/05-ttb-defaults \
 && chmod 644 /usr/local/bin/ttb-seed-once.py \
 && mkdir -p /usr/local/lib/ttb

ENV PUID=1000 \
    PGID=1000 \
    TZ=UTC \
    DELUGE_PASSWORD=ttb \
    CATALOG_ROOT=/catalog \
    TTB_CLIENT_ID=deluge \
    PYTHONPATH=/usr/local/lib/ttb

EXPOSE 8112 58846 6881 6881/udp
VOLUME ["/config", "/downloads", "/catalog"]

LABEL org.opencontainers.image.title="ttb-deluge" \
      org.opencontainers.image.description="Deluge UI client for Torrent Test Bench"
