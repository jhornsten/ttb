# syntax=docker/dockerfile:1
# TTB qBittorrent UI client — boots popular + unique:qbittorrent from shared catalog.

FROM linuxserver/qbittorrent:latest

COPY clients/qbittorrent/qBittorrent.conf /defaults/qBittorrent.conf
COPY clients/qbittorrent/05-ttb-defaults /custom-cont-init.d/05-ttb-defaults
COPY scripts/link-slice.sh /usr/local/bin/ttb-link-slice
COPY clients/qbittorrent/10-link-catalog /custom-cont-init.d/10-link-catalog
COPY clients/qbittorrent/seed-once.py /usr/local/bin/ttb-seed-once.py
COPY clients/qbittorrent/ttb-seed /custom-services.d/ttb-seed
COPY generator/slice_lib.py /usr/local/lib/ttb/slice_lib.py
RUN chmod +x \
      /usr/local/bin/ttb-link-slice \
      /custom-cont-init.d/05-ttb-defaults \
      /custom-cont-init.d/10-link-catalog \
      /custom-services.d/ttb-seed \
 && chmod 644 /usr/local/bin/ttb-seed-once.py \
 && mkdir -p /usr/local/lib/ttb

ENV PUID=1000 \
    PGID=1000 \
    TZ=UTC \
    WEBUI_PORT=8080 \
    TORRENTING_PORT=6881 \
    CATALOG_ROOT=/catalog \
    TTB_CLIENT_ID=qbittorrent \
    QBIT_USER=ttb \
    QBIT_PASS=ttb \
    PYTHONPATH=/usr/local/lib/ttb

EXPOSE 8080 6881 6881/udp
VOLUME ["/config", "/downloads", "/catalog"]

LABEL org.opencontainers.image.title="ttb-qbittorrent" \
      org.opencontainers.image.description="qBittorrent UI client for Torrent Test Bench"
