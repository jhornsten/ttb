#!/usr/bin/env python3
"""Wait for deluge-web, then add catalog slice torrents once per config volume."""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

CATALOG = Path(os.environ.get("CATALOG_ROOT", "/catalog"))
DOWNLOADS = os.environ.get("DOWNLOADS", "/downloads")
CONFIG = Path(os.environ.get("CONFIG", "/config"))
MARKER = CONFIG / ".ttb-seeded"
CLIENT_ID = os.environ.get("TTB_CLIENT_ID", "deluge")
WEB_URL = os.environ.get("DELUGE_WEB_URL", "http://127.0.0.1:8112").rstrip("/")
PASSWORD = os.environ.get("DELUGE_PASSWORD", "ttb")

sys.path.insert(0, str(CATALOG))
sys.path.insert(0, "/usr/local/lib/ttb")
from slice_lib import boot_entries, torrent_path  # noqa: E402


class DelugeRpc:
    def __init__(self, base: str) -> None:
        self.base = base
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self._id = 0

    def call(self, method: str, params: list | None = None) -> object:
        self._id += 1
        payload = json.dumps({"method": method, "params": params or [], "id": self._id}).encode()
        req = urllib.request.Request(
            f"{self.base}/json",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with self.opener.open(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
        if body.get("error"):
            err = body["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"{method}: {msg}")
        return body.get("result")


def log(msg: str) -> None:
    print(f"[ttb] {msg}", flush=True)


def wait_catalog(attempts: int = 180) -> None:
    for _ in range(attempts):
        if (CATALOG / "manifest.json").is_file():
            return
        time.sleep(1)
    raise RuntimeError(f"catalog never appeared at {CATALOG}")


def wait_web(rpc: DelugeRpc, attempts: int = 120) -> None:
    for _ in range(attempts):
        try:
            rpc.call("auth.check_session")
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("deluge-web never became ready")


def ensure_connected(rpc: DelugeRpc) -> None:
    if rpc.call("auth.login", [PASSWORD]) is not True:
        raise RuntimeError("auth.login failed — check DELUGE_PASSWORD")
    if rpc.call("web.connected"):
        return
    hosts = rpc.call("web.get_hosts") or []
    if not hosts:
        raise RuntimeError("no deluge hosts registered")
    host_id = hosts[0][0]
    rpc.call("web.connect", [host_id])
    for _ in range(30):
        if rpc.call("web.connected"):
            return
        time.sleep(1)
    raise RuntimeError("web.connect did not finish")


def seed() -> int:
    wait_catalog()
    if MARKER.exists():
        log(f"Already seeded ({MARKER.read_text().strip()}) — skip")
        return 0

    manifest = json.loads((CATALOG / "manifest.json").read_text(encoding="utf-8"))
    entries = boot_entries(manifest, CLIENT_ID)
    if not entries:
        log(f"No torrents for client={CLIENT_ID}")
        return 1

    rpc = DelugeRpc(WEB_URL)
    wait_web(rpc)
    ensure_connected(rpc)

    total = len(entries)
    log(f"Adding {total} torrents (client={CLIENT_ID})…")
    options = {
        "download_location": DOWNLOADS,
        "add_paused": False,
        "seed_mode": True,
    }
    for i, entry in enumerate(entries, start=1):
        path = torrent_path(CATALOG, entry)
        filedump = base64.b64encode(path.read_bytes()).decode("ascii")
        try:
            rpc.call("core.add_torrent_file", [path.name, filedump, options])
        except Exception as exc:
            if "already" not in str(exc).lower():
                log(f"warn {path.name}: {exc}")
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
