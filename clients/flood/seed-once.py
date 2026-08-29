#!/usr/bin/env python3
"""Load catalog slice into rTorrent via SCGI XML-RPC; keep Flood seed sidecar alive."""

from __future__ import annotations

import os
import socket
import sys
import time
import xmlrpc.client
from pathlib import Path

CATALOG = Path(os.environ.get("CATALOG_ROOT", "/catalog"))
DOWNLOADS = Path(os.environ.get("DOWNLOADS", "/downloads"))
CONFIG = Path(os.environ.get("CONFIG", "/config"))
MARKER = CONFIG / ".ttb-seeded"
CLIENT_ID = os.environ.get("TTB_CLIENT_ID", "flood")
SOCKET = os.environ.get("RTORRENT_SOCKET", "/run/rtorrent/rtorrent.sock")

sys.path.insert(0, str(CATALOG))
sys.path.insert(0, "/usr/local/lib/ttb")
from slice_lib import boot_entries, torrent_path  # noqa: E402


def log(msg: str) -> None:
    print(f"[ttb] {msg}", flush=True)


class SCGITransport(xmlrpc.client.Transport):
    def __init__(self, socket_path: str) -> None:
        super().__init__()
        self.socket_path = socket_path

    def request(self, host, handler, request_body, verbose=False):
        header = (
            f"CONTENT_LENGTH\x00{len(request_body)}\x00"
            f"SCGI\x001\x00"
            f"REQUEST_METHOD\x00POST\x00"
            f"REQUEST_URI\x00{handler}\x00"
        ).encode()
        payload = f"{len(header)}:".encode() + header + b"," + (
            request_body if isinstance(request_body, bytes) else request_body.encode()
        )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(120)
            sock.connect(self.socket_path)
            sock.sendall(payload)
            chunks = []
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                chunks.append(data)
        raw = b"".join(chunks)
        # Response is HTTP-like: headers\r\n\r\nbody
        if b"\r\n\r\n" in raw:
            body = raw.split(b"\r\n\r\n", 1)[1]
        else:
            body = raw
        p, u = xmlrpc.client.getparser()
        p.feed(body)
        p.close()
        return u.close()


def rpc(method: str, *params):
    proxy = xmlrpc.client.ServerProxy(
        "http://localhost/RPC2",
        transport=SCGITransport(SOCKET),
        allow_none=True,
    )
    return getattr(proxy, method)(*params)


def wait_catalog(attempts: int = 180) -> None:
    for _ in range(attempts):
        if (CATALOG / "manifest.json").is_file():
            return
        time.sleep(1)
    raise RuntimeError(f"catalog never appeared at {CATALOG}")


def wait_socket(attempts: int = 180) -> None:
    for _ in range(attempts):
        if Path(SOCKET).exists():
            try:
                rpc("system.listMethods")
                return
            except Exception:
                pass
        time.sleep(1)
    raise RuntimeError(f"rTorrent SCGI never ready at {SOCKET}")


def link_slice() -> None:
    marker = DOWNLOADS / ".seed-linked"
    if marker.exists():
        return
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    import json

    from slice_lib import content_path

    manifest = json.loads((CATALOG / "manifest.json").read_text(encoding="utf-8"))
    entries = boot_entries(manifest, CLIENT_ID)
    for e in entries:
        src = content_path(CATALOG, e)
        dst = DOWNLOADS / e["content"]
        if src.exists() and not dst.exists():
            dst.symlink_to(src)
    marker.touch()
    log(f"linked {len(entries)} content paths")


def seed() -> int:
    wait_catalog()
    CONFIG.mkdir(parents=True, exist_ok=True)
    (CONFIG / "session").mkdir(parents=True, exist_ok=True)
    Path(SOCKET).parent.mkdir(parents=True, exist_ok=True)
    link_slice()
    if MARKER.exists():
        log(f"Already seeded ({MARKER.read_text().strip()}) — skip")
        return 0

    import json

    manifest = json.loads((CATALOG / "manifest.json").read_text(encoding="utf-8"))
    entries = boot_entries(manifest, CLIENT_ID)
    if not entries:
        log(f"No torrents for client={CLIENT_ID}")
        return 1

    wait_socket()
    total = len(entries)
    log(f"Adding {total} torrents (client={CLIENT_ID})…")
    for i, entry in enumerate(entries, start=1):
        path = str(torrent_path(CATALOG, entry))
        try:
            # load.raw_start with base64 is awkward; load.start takes a URL/path.
            rpc("load.start_verbose", "", path)
        except Exception as exc:
            # Some builds use load.start
            try:
                rpc("load.start", "", path)
            except Exception as exc2:
                log(f"warn {path}: {exc} / {exc2}")
        if i % 100 == 0 or i == total:
            log(f"  {i}/{total}")

    MARKER.write_text(str(total) + "\n", encoding="utf-8")
    log(f"Seed complete ({total} torrents)")
    return 0


def main() -> int:
    sidecar = "--sidecar" in sys.argv
    try:
        code = seed()
    except Exception as exc:
        log(f"seed failed: {exc}")
        code = 1
        if not sidecar:
            return code
    if sidecar:
        while True:
            time.sleep(3600)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
