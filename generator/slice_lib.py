#!/usr/bin/env python3
"""Helpers for selecting catalog torrents by client role / pool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_manifest(catalog: Path) -> dict[str, Any]:
    path = catalog / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def boot_entries(manifest: dict[str, Any], client_id: str) -> list[dict[str, Any]]:
    """Torrents a UI client should have complete at boot (popular + unique)."""
    want = {"popular", f"unique:{client_id}"}
    return [t for t in manifest["torrents"] if t["role"] in want]


def pool_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in manifest["torrents"] if t["role"] == "pool"]


def entries_for_roles(manifest: dict[str, Any], roles: set[str]) -> list[dict[str, Any]]:
    return [t for t in manifest["torrents"] if t["role"] in roles]


def all_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return list(manifest["torrents"])


def torrent_path(catalog: Path, entry: dict[str, Any]) -> Path:
    return catalog / "torrents" / entry["torrent"]


def content_path(catalog: Path, entry: dict[str, Any]) -> Path:
    return catalog / "content" / entry["content"]
