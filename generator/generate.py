#!/usr/bin/env python3
"""Generate a shared TTB catalog: payloads, .torrent metainfo, and role manifest.

No third-party deps. Torrents are partitioned across in-bench opentracker
instances and assigned popular / per-client-unique / pool roles.

Payload size per torrent is configurable (`--size-min` / `--size-max` or
PAYLOAD_SIZE_MIN / PAYLOAD_SIZE_MAX), e.g. 50MB..200MB for heavier benches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
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


def parse_size(value: str | int) -> int:
    """Parse a byte count or human size like 64KiB, 50MB, 1G (binary units)."""
    if isinstance(value, int):
        return value
    raw = value.strip().upper().replace(" ", "")
    if not raw:
        raise ValueError("empty size")
    units = {
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "KI": 1024,
        "KIB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "MI": 1024**2,
        "MIB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "GI": 1024**3,
        "GIB": 1024**3,
    }
    for suffix in sorted(units, key=len, reverse=True):
        if raw.endswith(suffix):
            number = raw[: -len(suffix)]
            return int(float(number) * units[suffix])
    return int(raw)


def format_bytes(n: int) -> str:
    if n >= 1024**3:
        if n % (1024**3) == 0:
            return f"{n // (1024**3)}GiB"
        return f"{n / (1024**3):.1f}GiB"
    if n >= 1024**2:
        return f"{n / (1024**2):.1f}MiB"
    if n >= 1024:
        return f"{n / 1024:.1f}KiB"
    return f"{n}B"


def required_disk_bytes(count: int, size_max: int) -> int:
    """Worst-case payload plus headroom: max(1GiB, 10% of payload)."""
    payload = count * size_max
    headroom = max(1024**3, payload // 10)
    return payload + headroom


def free_disk_bytes(path: Path) -> int:
    check = path.resolve()
    while not check.exists() and check != check.parent:
        check = check.parent
    return shutil.disk_usage(check).free


def ensure_disk_space(path: Path, count: int, size_max: int) -> str | None:
    """Return an error message if free space is insufficient, else None."""
    required = required_disk_bytes(count, size_max)
    free = free_disk_bytes(path)
    if free >= required:
        return None
    payload = count * size_max
    headroom = required - payload
    return (
        f"insufficient disk space for catalog build: need "
        f"{format_bytes(required)} free "
        f"(worst-case {format_bytes(payload)} payload + "
        f"{format_bytes(headroom)} headroom), have {format_bytes(free)} "
        f"on {path}"
    )


def choose_piece_length(total_bytes: int) -> int:
    """Pick a power-of-two piece length so piece count stays manageable."""
    # Target roughly 1000–2000 pieces; clamp to common BitTorrent bounds.
    target_pieces = 1500
    raw = max(total_bytes // target_pieces, 16 * 1024)
    # Round up to next power of two.
    power = 1 << (raw - 1).bit_length()
    return min(max(power, 16 * 1024), 16 * 1024 * 1024)


def write_random_file(path: Path, size: int, rng: random.Random) -> None:
    """Write `size` random bytes. `rng` seeds a small header; body uses os.urandom."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Touch rng so per-torrent streams stay deterministic in call order.
    rng.randbytes(1)
    remaining = size
    first = True
    with path.open("wb") as fh:
        while remaining > 0:
            chunk = min(remaining, 1024 * 1024)
            block = bytearray(os.urandom(chunk))
            if first and chunk >= 16:
                block[0:8] = b"TTBSEED\0"
                block[8:16] = struct.pack(">Q", size)
                first = False
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
    size_min: int,
    size_max: int,
) -> dict:
    rng = rng_for(index, seed)
    multi = rng.random() < 0.35
    name = random_name(rng, index, multi)
    total_size = rng.randint(size_min, size_max)
    piece_length = choose_piece_length(total_size)

    files_spec: list[tuple[list[str], Path, int]] = []
    if multi:
        n_files = rng.randint(2, 5)
        # Split total_size across parts (at least 1 byte each).
        weights = [rng.random() + 0.05 for _ in range(n_files)]
        weight_sum = sum(weights)
        sizes = [max(1, int(total_size * w / weight_sum)) for w in weights]
        # Fix rounding so sum == total_size.
        sizes[-1] = max(1, total_size - sum(sizes[:-1]))
        root = out_content / name
        for i, size in enumerate(sizes):
            rel = [f"part-{i:02d}.{rng.choice(EXTS)}"]
            abs_path = root.joinpath(*rel)
            write_random_file(abs_path, size, rng)
            files_spec.append((rel, abs_path, size))
    else:
        abs_path = out_content / name
        write_random_file(abs_path, total_size, rng)
        files_spec.append(([name], abs_path, total_size))

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
        "piece_length": piece_length,
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
    default_size_min = os.environ.get("PAYLOAD_SIZE_MIN", "1KiB")
    default_size_max = os.environ.get("PAYLOAD_SIZE_MAX", "48KiB")
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
    parser.add_argument(
        "--size-min",
        type=str,
        default=default_size_min,
        help="Min payload size per torrent (bytes or 64KiB/50MB/1GiB)",
    )
    parser.add_argument(
        "--size-max",
        type=str,
        default=default_size_max,
        help="Max payload size per torrent (bytes or 64KiB/50MB/1GiB)",
    )
    parser.add_argument(
        "--check-disk",
        action="store_true",
        help="Estimate required disk and exit without generating",
    )
    args = parser.parse_args()

    try:
        size_min = parse_size(args.size_min)
        size_max = parse_size(args.size_max)
    except ValueError as exc:
        print(f"invalid size: {exc}", file=sys.stderr)
        return 2

    if args.count < 1:
        print("count must be >= 1", file=sys.stderr)
        return 2
    if not 1 <= args.tracker_count <= 5:
        print("tracker-count must be 1..5", file=sys.stderr)
        return 2
    if size_min < 16:
        print("size-min must be >= 16 bytes (header marker)", file=sys.stderr)
        return 2
    if size_max < size_min:
        print("size-max must be >= size-min", file=sys.stderr)
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

    required = required_disk_bytes(args.count, size_max)
    disk_err = ensure_disk_space(args.out, args.count, size_max)
    if args.check_disk:
        free = free_disk_bytes(args.out)
        print(
            f"catalog disk check: need {format_bytes(required)}, "
            f"have {format_bytes(free)} on {args.out.resolve()}",
            flush=True,
        )
        if disk_err:
            print(disk_err, file=sys.stderr)
            return 1
        return 0
    if disk_err:
        print(disk_err, file=sys.stderr)
        return 1

    content = args.out / "content"
    torrents = args.out / "torrents"
    content.mkdir(parents=True, exist_ok=True)
    torrents.mkdir(parents=True, exist_ok=True)
    clear_dir(torrents)
    clear_dir(content)

    roles = assign_roles(args.count, clients, args.popular_ratio, args.pool_ratio)

    print(
        f"Generating {args.count} torrents (seed={args.seed}, "
        f"size={format_bytes(size_min)}..{format_bytes(size_max)}, "
        f"need≈{format_bytes(required)}, "
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
            size_min=size_min,
            size_max=size_max,
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
        "size_min": size_min,
        "size_max": size_max,
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
        f"size_min={size_min}\nsize_max={size_max}\n"
        f"tracker_count={args.tracker_count}\nclients={','.join(clients)}\n"
        f"role_counts={json.dumps(role_counts)}\n"
        f"content={content}\ntorrents={torrents}\n",
        encoding="utf-8",
    )
    print(
        f"Done: {args.count} torrents, {format_bytes(total_bytes)} payload, "
        f"{time.time() - t0:.1f}s, roles={role_counts}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
