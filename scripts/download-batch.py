#!/usr/bin/env python3
"""Add N incomplete torrents from the catalog pool to a UI client (download batch).

Requires the bench to be up (catalog published, seeder holding full catalog).
Talks to client RPC/Web APIs on localhost published ports.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "generator"))
from slice_lib import pool_entries  # noqa: E402

STATE_DEFAULT = ROOT / "dist" / "swarm-state.json"


def log(msg: str) -> None:
    print(f"[ttb-batch] {msg}", flush=True)


def load_state(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"assigned": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def read_manifest_from_catalog_container() -> dict:
    """Prefer live catalog volume via docker exec; fall back to local path."""
    import subprocess

    try:
        out = subprocess.check_output(
            [
                "docker",
                "exec",
                "ttb-catalog",
                "cat",
                "/catalog/manifest.json",
            ],
            text=True,
        )
        return json.loads(out)
    except Exception as exc:
        local = os.environ.get("CATALOG_MANIFEST")
        if local and Path(local).is_file():
            return json.loads(Path(local).read_text(encoding="utf-8"))
        raise RuntimeError(
            "Could not read catalog manifest from ttb-catalog container. "
            f"Is the bench up? ({exc})"
        ) from exc


def copy_torrent_from_catalog(rel_name: str, dest: Path) -> Path:
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["docker", "cp", f"ttb-catalog:/catalog/torrents/{rel_name}", str(dest)]
    )
    return dest


class TransmissionClient:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url.rstrip("/") + "/transmission/rpc"
        self.session_id = ""
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._auth_header = f"Basic {token}"

    def call(self, method: str, arguments: dict | None = None) -> dict:
        payload = json.dumps({"method": method, "arguments": arguments or {}}).encode()
        for _ in range(3):
            req = urllib.request.Request(
                self.url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": self._auth_header,
                    "X-Transmission-Session-Id": self.session_id,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    self.session_id = exc.headers.get("X-Transmission-Session-Id", "")
                    continue
                raise
        raise RuntimeError("transmission RPC session failed")

    def add_incomplete(self, torrent_file: Path) -> None:
        filedump = base64.b64encode(torrent_file.read_bytes()).decode("ascii")
        result = self.call(
            "torrent-add",
            {
                "metainfo": filedump,
                "paused": False,
            },
        )
        if result.get("result") not in ("success",):
            # duplicate is ok
            if "duplicate" not in json.dumps(result).lower():
                raise RuntimeError(str(result))


class DelugeClient:
    def __init__(self, url: str, password: str) -> None:
        self.base = url.rstrip("/")
        self.password = password
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self._id = 0

    def call(self, method: str, params: list | None = None) -> object:
        self._id += 1
        payload = json.dumps({"method": method, "params": params or [], "id": self._id}).encode()
        req = urllib.request.Request(
            f"{self.base}/json",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
        if body.get("error"):
            raise RuntimeError(str(body["error"]))
        return body.get("result")

    def connect(self) -> None:
        if self.call("auth.login", [self.password]) is not True:
            raise RuntimeError("deluge login failed")
        if not self.call("web.connected"):
            hosts = self.call("web.get_hosts") or []
            self.call("web.connect", [hosts[0][0]])
            for _ in range(30):
                if self.call("web.connected"):
                    break
                time.sleep(1)

    def add_incomplete(self, torrent_file: Path) -> None:
        filedump = base64.b64encode(torrent_file.read_bytes()).decode("ascii")
        options = {
            "download_location": "/downloads",
            "add_paused": False,
            "seed_mode": False,
        }
        try:
            self.call("core.add_torrent_file", [torrent_file.name, filedump, options])
        except Exception as exc:
            if "already" not in str(exc).lower():
                raise


class QBitClient:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.base = url.rstrip("/")
        self.user = user
        self.password = password
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def login(self) -> None:
        body = urllib.parse.urlencode(
            {"username": self.user, "password": self.password}
        ).encode()
        req = urllib.request.Request(
            f"{self.base}/api/v2/auth/login",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with self.opener.open(req, timeout=60) as resp:
            text = resp.read().decode().strip()
            code = getattr(resp, "status", 200)
        if text not in ("Ok.", "Ok") and not (not text and code in (200, 204)):
            raise RuntimeError(f"qBittorrent login failed: {text!r} http={code}")

    def add_incomplete(self, torrent_file: Path) -> None:
        boundary = "----ttbbatch"
        raw = torrent_file.read_bytes()
        parts = [
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="torrents"; filename="{torrent_file.name}"\r\n'
                f"Content-Type: application/x-bittorrent\r\n\r\n"
            ).encode()
            + raw
            + b"\r\n"
        ]
        for name, value in (
            ("savepath", "/downloads"),
            ("skip_checking", "false"),
            ("paused", "false"),
            ("autoTMM", "false"),
        ):
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode()
            )
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        req = urllib.request.Request(
            f"{self.base}/api/v2/torrents/add",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with self.opener.open(req, timeout=60) as resp:
            resp.read()


def add_flood_via_docker(torrent_file: Path) -> None:
    """Copy torrent into rtorrent downloads and load via flood-seed container RPC."""
    import subprocess

    remote = f"/downloads/.batch/{torrent_file.name}"
    subprocess.check_call(
        ["docker", "exec", "ttb-rtorrent", "mkdir", "-p", "/downloads/.batch"]
    )
    subprocess.check_call(
        ["docker", "cp", str(torrent_file), f"ttb-rtorrent:{remote}"]
    )
    # Use flood-seed's python to call load.start
    script = f"""
import socket, xmlrpc.client
class T(xmlrpc.client.Transport):
    def request(self, host, handler, request_body, verbose=False):
        header = f"CONTENT_LENGTH\\x00{{len(request_body)}}\\x00SCGI\\x001\\x00".encode()
        payload = f"{{len(header)}}:".encode() + header + b"," + (request_body if isinstance(request_body, bytes) else request_body.encode())
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect("/run/rtorrent/rtorrent.sock")
        s.sendall(payload)
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk: break
            data += chunk
        s.close()
        body = data.split(b"\\r\\n\\r\\n", 1)[-1]
        p, u = xmlrpc.client.getparser()
        p.feed(body); p.close(); return u.close()
proxy = xmlrpc.client.ServerProxy("http://localhost/RPC2", transport=T())
try:
    proxy.load.start("", "{remote}")
except Exception:
    proxy.load.start_verbose("", "{remote}")
"""
    subprocess.check_call(
        ["docker", "exec", "ttb-flood-seed", "python3", "-c", script]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        required=True,
        choices=["transmission", "deluge", "qbittorrent", "flood"],
    )
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--from", dest="source", default="pool", choices=["pool"])
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(os.environ.get("SWARM_STATE", str(STATE_DEFAULT))),
    )
    parser.add_argument("--transmission-url", default="http://127.0.0.1:9091")
    parser.add_argument("--deluge-url", default="http://127.0.0.1:8112")
    parser.add_argument("--qbit-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    if args.count < 1:
        print("count must be >= 1", file=sys.stderr)
        return 2

    manifest = read_manifest_from_catalog_container()
    state = load_state(args.state)
    assigned = set(state.setdefault("assigned", {}).get(args.client, []))

    candidates = [
        e for e in pool_entries(manifest) if e["infohash"] not in assigned
    ]
    if len(candidates) < args.count:
        log(f"only {len(candidates)} unassigned pool torrents left (requested {args.count})")
    selected = candidates[: args.count]
    if not selected:
        log("nothing to assign")
        return 1

    tmp = ROOT / "dist" / "batch-tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    client = None
    if args.client == "transmission":
        client = TransmissionClient(args.transmission_url, "ttb", "ttb")
    elif args.client == "deluge":
        client = DelugeClient(args.deluge_url, "ttb")
        client.connect()
    elif args.client == "qbittorrent":
        client = QBitClient(args.qbit_url, "ttb", "ttb")
        client.login()

    log(f"assigning {len(selected)} pool torrents → {args.client}")
    for i, entry in enumerate(selected, start=1):
        local = tmp / entry["torrent"]
        copy_torrent_from_catalog(entry["torrent"], local)
        if args.client == "flood":
            add_flood_via_docker(local)
        else:
            assert client is not None
            client.add_incomplete(local)
        assigned.add(entry["infohash"])
        if i % 10 == 0 or i == len(selected):
            log(f"  {i}/{len(selected)}")

    state["assigned"][args.client] = sorted(assigned)
    save_state(args.state, state)
    log(f"done; state → {args.state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
