#!/usr/bin/env python3
"""Add catalog slice torrents to qBittorrent once per config volume."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

CATALOG = Path(os.environ.get("CATALOG_ROOT", "/catalog"))
DOWNLOADS = os.environ.get("DOWNLOADS", "/downloads")
CONFIG = Path(os.environ.get("CONFIG", "/config"))
MARKER = CONFIG / ".ttb-seeded"
CLIENT_ID = os.environ.get("TTB_CLIENT_ID", "qbittorrent")
BASE = os.environ.get("QBIT_URL", "http://127.0.0.1:8080").rstrip("/")
USER = os.environ.get("QBIT_USER", "ttb")
PASSWORD = os.environ.get("QBIT_PASS", "ttb")

sys.path.insert(0, str(CATALOG))
sys.path.insert(0, "/usr/local/lib/ttb")
from slice_lib import boot_entries, torrent_path  # noqa: E402


def log(msg: str) -> None:
    print(f"[ttb] {msg}", flush=True)


class QBit:
    def __init__(self, base: str) -> None:
        self.base = base
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def request(self, path: str, data: bytes | None = None, headers: dict | None = None):
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            headers=headers or {},
            method="POST" if data is not None else "GET",
        )
        return self.opener.open(req, timeout=120)

    def login(self) -> None:
        candidates = [
            (USER, PASSWORD),
            ("admin", "adminadmin"),
            ("ttb", "ttb"),
        ]
        last = ""
        for user, password in candidates:
            body = urllib.parse.urlencode({"username": user, "password": password}).encode()
            try:
                with self.request(
                    "/api/v2/auth/login",
                    data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ) as resp:
                    text = resp.read().decode().strip()
                    code = getattr(resp, "status", 200)
            except Exception as exc:
                last = str(exc)
                continue
            # qBittorrent 4.x returns "Ok."; 5.x often returns empty 200/204.
            if text in ("Ok.", "Ok") or (not text and code in (200, 204)):
                if (user, password) != (USER, PASSWORD):
                    self.set_prefs()
                return
            last = repr(text) or f"http {code}"
        raise RuntimeError(f"qBittorrent login failed: {last}")

    def set_prefs(self) -> None:
        prefs = {
            "dht": False,
            "pex": False,
            "lsd": False,
            "queueing_enabled": False,
            "max_connec": 2000,
            "listen_port": 6881,
            "save_path": DOWNLOADS,
            "web_ui_username": USER,
            "web_ui_password": PASSWORD,
        }
        body = urllib.parse.urlencode({"json": json.dumps(prefs)}).encode()
        try:
            self.request(
                "/api/v2/app/setPreferences",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ).read()
        except Exception as exc:
            log(f"warn setPreferences: {exc}")

    def add_torrent(self, path: Path) -> None:
        # multipart/form-data
        boundary = "----ttbboundary"
        filename = path.name
        raw = path.read_bytes()
        parts = []
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="torrents"; filename="{filename}"\r\n'
            f"Content-Type: application/x-bittorrent\r\n\r\n".encode()
            + raw
            + b"\r\n"
        )
        for name, value in (
            ("savepath", DOWNLOADS),
            ("skip_checking", "true"),
            ("paused", "false"),
            ("autoTMM", "false"),
        ):
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode()
            )
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        try:
            self.request(
                "/api/v2/torrents/add",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            ).read()
        except urllib.error.HTTPError as exc:
            # Already present is fine
            if exc.code not in (200, 409):
                raise


def wait_catalog(attempts: int = 180) -> None:
    for _ in range(attempts):
        if (CATALOG / "manifest.json").is_file():
            return
        time.sleep(1)
    raise RuntimeError(f"catalog never appeared at {CATALOG}")


def wait_api(qbit: QBit, attempts: int = 180) -> None:
    for _ in range(attempts):
        try:
            qbit.login()
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("qBittorrent API never became ready")


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

    qbit = QBit(BASE)
    wait_api(qbit)
    qbit.set_prefs()

    total = len(entries)
    log(f"Adding {total} torrents (client={CLIENT_ID})…")
    for i, entry in enumerate(entries, start=1):
        path = torrent_path(CATALOG, entry)
        try:
            qbit.add_torrent(path)
        except Exception as exc:
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
