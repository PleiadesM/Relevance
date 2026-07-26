"""Deterministic, atomic JSON output. Stable key order keeps the Actions
data commits small and reviewable."""

from __future__ import annotations

import json
import os
from pathlib import Path


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, sort_keys=True, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def read_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_json_or_none(path: Path):
    """read_json for callers reading the *previous* build's output, where
    absent or corrupt simply means "no previous state" rather than an error."""
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


def remove_if_exists(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
