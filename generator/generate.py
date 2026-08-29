#!/usr/bin/env python3
"""Generate a shared TTB catalog: payloads, .torrent metainfo, and role manifest.

No third-party deps. Torrents are partitioned across in-bench opentracker
instances and assigned popular / per-client-unique / pool roles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import struct
import sys
import time
from pathlib import Path


# --- minimal bencode ---------------------------------------------------------

def bencode(value: object) -> bytes:
    if isinstance(value, int):
        return f"i{value}e".encode()
    if isinstance(value, bytes):
        return f"{len(value)}:".encode() + value
    if isinstance(value, str):
        raw = value.encode()
        return f"{len(raw)}:".encode() + raw
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items = sorted(
            value.items(),
            key=lambda kv: kv[0] if isinstance(kv[0], bytes) else kv[0].encode(),
        )
        out = b"d"
        for k, v in items:
            key = k if isinstance(k, bytes) else str(k).encode()
            out += bencode(key) + bencode(v)
        return out + b"e"
    raise TypeError(f"cannot bencode {type(value)!r}")


# --- torrent construction ----------------------------------------------------

ADJECTIVES = (
    "amber", "brittle", "copper", "dusty", "echo", "frost", "granite", "hollow",
    "ivory", "jade", "kepler", "lunar", "marble", "neon", "onyx", "prism",
    "quartz", "rusty", "solar", "tundra", "umbra", "violet", "woven", "xenon",
    "yellow", "zinc",
)
NOUNS = (
    "archive", "bundle", "cache", "dump", "export", "fragment", "gadget", "heap",
    "image", "journal", "kernel", "ledger", "mirror", "noise", "object", "packet",
    "queue", "record", "sample", "tape", "unit", "vector", "wafer", "yard", "zone",
)
EXTS = ("bin", "dat", "raw", "blob", "img", "pak", "chk", "seed")

DEFAULT_CLIENTS = ("transmission", "deluge", "qbittorrent", "flood")


def rng_for(index: int, seed: int) -> random.Random:
    return random.Random((seed << 20) ^ (index * 0x9E3779B1) & 0xFFFFFFFF)


def random_name(rng: random.Random, index: int, multi: bool) -> str:
    base = f"{rng.choice(ADJECTIVES)}_{rng.choice(NOUNS)}_{index:05d}"
    if multi:
        return base
    return f"{base}.{rng.choice(EXTS)}"


def write_random_file(path: Path, size: int, rng: random.Random) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    remaining = size
    with path.open("wb") as fh:
        while remaining > 0:
            chunk = min(remaining, 4096)
            block = bytearray(rng.getrandbits(8) for _ in range(chunk))
            if remaining == size and chunk >= 16:
                block[0:8] = b"TTBSEED\0"
                block[8:12] = struct.pack(">I", size)
            fh.write(block)
            remaining -= chunk


def piece_hashes(paths: list[tuple[Path, int]], piece_length: int) -> bytes:
    digest = hashlib.sha1()
    filled = 0
    pieces = bytearray()

    for path, size in paths:
        with path.open("rb") as fh:
            left = size
            while left > 0:
                buf = fh.read(min(left, piece_length - filled))
                if not buf:
                    break
                digest.update(buf)
                filled += len(buf)
                left -= len(buf)
                if filled == piece_length:
                    pieces.extend(digest.digest())
                    digest = hashlib.sha1()
                    filled = 0
    if filled:
        pieces.extend(digest.digest())
    return bytes(pieces)


def tracker_announce(tracker_index: int) -> str:
    return f"http://ttb-tracker-{tracker_index}:6969/announce"


def assign_roles(
    count: int,
    clients: list[str],
    popular_ratio: float,
    pool_ratio: float,
) -> list[str]:
    """Return role string per torrent index: popular | unique:<client> | pool."""
    if not clients:
        raise ValueError("at least one client id is required")
    n_popular = int(count * popular_ratio)
    n_pool = int(count * pool_ratio)
    if n_popular + n_pool > count:
        raise ValueError("popular_ratio + pool_ratio must be <= 1")
    n_unique = count - n_popular - n_pool

    roles: list[str] = ["popular"] * n_popular

    # Split unique evenly; remainder goes to earlier clients.
    base, rem = divmod(n_unique, len(clients))
    for i, client in enumerate(clients):
        n = base + (1 if i < rem else 0)
        roles.extend([f"unique:{client}"] * n)

    roles.extend(["pool"] * n_pool)
    assert len(roles) == count
    return roles


def build_torrent(
    *,
    name: str,
    files: list[tuple[list[str], Path, int]],
    piece_length: int,
    comment: str,
    announce: str,
) -> tuple[bytes, str]:
    """Return (bencoded torrent bytes, infohash hex)."""
    path_sizes = [(p, length) for _, p, length in files]
    pieces = piece_hashes(path_sizes, piece_length)

    info: dict[str, object] = {
        "name": name,
        "piece length": piece_length,
        "pieces": pieces,
        "private": 1,
    }
    if len(files) == 1 and files[0][0] == [name]:
        info["length"] = files[0][2]
    else:
        info["files"] = [
            {"length": length, "path": comps}
            for comps, _, length in files
        ]

    info_hash = hashlib.sha1(bencode(info)).hexdigest()
    meta = {
        "announce": announce,
        "comment": comment,
        "created by": "ttb",
        "creation date": int(time.time()),
        "info": info,
    }
    return bencode(meta), info_hash


def generate_one(
    out_content: Path,
    out_torrents: Path,
    index: int,
    seed: int,
    announce: str,
    role: str,
    tracker_index: int,
) -> dict:
    rng = rng_for(index, seed)
    multi = rng.random() < 0.35
    name = random_name(rng, index, multi)
    piece_length = 16 * 1024

    files_spec: list[tuple[list[str], Path, int]] = []
    if multi:
        n_files = rng.randint(2, 5)
        root = out_content / name
        for i in range(n_files):
            rel = [f"part-{i:02d}.{rng.choice(EXTS)}"]
            size = rng.randint(512, 24_576)
            abs_path = root.joinpath(*rel)
            write_random_file(abs_path, size, rng)
            files_spec.append((rel, abs_path, size))
    else:
        size = rng.randint(1024, 48_576)
        abs_path = out_content / name
        write_random_file(abs_path, size, rng)
        files_spec.append(([name], abs_path, size))

    torrent_bytes, info_hash = build_torrent(
        name=name,
        files=files_spec,
        piece_length=piece_length,
        comment=f"ttb #{index} ({role})",
        announce=announce,
    )
    safe = name.replace("/", "_")
    torrent_name = f"{index:05d}_{safe}.torrent"
    torrent_path = out_torrents / torrent_name
    torrent_path.write_bytes(torrent_bytes)

    total = sum(s for _, _, s in files_spec)
    return {
        "index": index,
        "name": name,
        "files": len(files_spec),
        "bytes": total,
        "torrent": torrent_name,
        "content": name,
        "infohash": info_hash,
        "tracker": tracker_index,
        "announce": announce,
        "role": role,
    }


def clear_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink()
        else:
            for sub in child.rglob("*"):
                if sub.is_file() or sub.is_symlink():
                    sub.unlink()
            for sub in sorted(child.rglob("*"), reverse=True):
                if sub.is_dir():
                    sub.rmdir()
            child.rmdir()


def main() -> int:
    default_count = int(os.environ.get("CATALOG_COUNT", os.environ.get("TORRENT_COUNT", "5000")))
    default_trackers = int(os.environ.get("TRACKER_COUNT", "3"))
    default_clients = os.environ.get(
        "TTB_CLIENTS",
        ",".join(DEFAULT_CLIENTS),
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=default_count)
    parser.add_argument("--seed", type=int, default=int(os.environ.get("TORRENT_SEED", "42")))
    parser.add_argument("--out", type=Path, default=Path(os.environ.get("OUTPUT_DIR", "/data")))
    parser.add_argument("--tracker-count", type=int, default=default_trackers)
    parser.add_argument(
        "--popular-ratio",
        type=float,
        default=float(os.environ.get("POPULAR_RATIO", "0.20")),
    )
    parser.add_argument(
        "--pool-ratio",
        type=float,
        default=float(os.environ.get("POOL_RATIO", "0.20")),
    )
    parser.add_argument(
        "--clients",
        type=str,
        default=default_clients,
        help="Comma-separated UI client ids for unique-role split",
    )
    args = parser.parse_args()

    if args.count < 1:
        print("count must be >= 1", file=sys.stderr)
        return 2
    if not 1 <= args.tracker_count <= 5:
        print("tracker-count must be 1..5", file=sys.stderr)
        return 2
    if not 0 <= args.popular_ratio <= 1 or not 0 <= args.pool_ratio <= 1:
        print("ratios must be in [0, 1]", file=sys.stderr)
        return 2
    if args.popular_ratio + args.pool_ratio > 1:
        print("popular_ratio + pool_ratio must be <= 1", file=sys.stderr)
        return 2

    clients = [c.strip() for c in args.clients.split(",") if c.strip()]
    if not clients:
        print("at least one client is required", file=sys.stderr)
        return 2

    content = args.out / "content"
    torrents = args.out / "torrents"
    content.mkdir(parents=True, exist_ok=True)
    torrents.mkdir(parents=True, exist_ok=True)
    clear_dir(torrents)
    clear_dir(content)

    roles = assign_roles(args.count, clients, args.popular_ratio, args.pool_ratio)

    print(
        f"Generating {args.count} torrents (seed={args.seed}, "
        f"trackers={args.tracker_count}, clients={clients}) → {args.out}",
        flush=True,
    )
    t0 = time.time()
    total_bytes = 0
    entries: list[dict] = []
    for i in range(args.count):
        tracker_index = i % args.tracker_count
        meta = generate_one(
            content,
            torrents,
            i,
            args.seed,
            announce=tracker_announce(tracker_index),
            role=roles[i],
            tracker_index=tracker_index,
        )
        entries.append(meta)
        total_bytes += meta["bytes"]
        if (i + 1) % 100 == 0 or i + 1 == args.count:
            elapsed = time.time() - t0
            print(f"  {i + 1}/{args.count}  ({elapsed:.1f}s)", flush=True)

    role_counts: dict[str, int] = {}
    for e in entries:
        role_counts[e["role"]] = role_counts.get(e["role"], 0) + 1

    manifest = {
        "version": 1,
        "count": args.count,
        "seed": args.seed,
        "bytes": total_bytes,
        "tracker_count": args.tracker_count,
        "popular_ratio": args.popular_ratio,
        "pool_ratio": args.pool_ratio,
        "clients": clients,
        "role_counts": role_counts,
        "torrents": entries,
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.out / "manifest.txt").write_text(
        f"count={args.count}\nseed={args.seed}\nbytes={total_bytes}\n"
        f"tracker_count={args.tracker_count}\nclients={','.join(clients)}\n"
        f"role_counts={json.dumps(role_counts)}\n"
        f"content={content}\ntorrents={torrents}\n",
        encoding="utf-8",
    )
    print(
        f"Done: {args.count} torrents, {total_bytes / 1024:.1f} KiB payload, "
        f"{time.time() - t0:.1f}s, roles={role_counts}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
