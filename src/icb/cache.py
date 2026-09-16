"""Content-hash cache for model results (CLAUDE.md §8).

Keyed by everything that steers the answer, so a re-screen of the same deck against the same
pack is free and identical, and any change to the model, prompt or schema misses on its own.
A cache failure is never fatal: the run simply pays for a fresh call.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def cache_dir() -> Path:
    configured = os.getenv("ICB_CACHE_DIR")
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "icb-cache"


def key(*parts: object) -> str:
    joined = "|".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def read(name: str) -> dict[str, Any] | None:
    path = cache_dir() / f"{name}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(name: str, payload: dict[str, Any]) -> None:
    directory = cache_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, directory / f"{name}.json")
    except OSError:
        return  # caching is an optimization, never a requirement
