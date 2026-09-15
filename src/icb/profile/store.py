"""Investor records on disk: <ICB_DATA_DIR>/<slug>/{investor.json, profile.yaml, notes/}.

Writes are atomic (temp file + rename), so a crash or a concurrent save never leaves a
half-written profile. Slugs are validated before any path is built, and uploaded note files
are checked by extension and content before anything is written.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from icb.profile.models import SLUG_PATTERN

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SLUG_RE = re.compile(SLUG_PATTERN)
MAX_NOTE_FILES = 20
NOTE_SIGNATURES: dict[str, bytes | None] = {".pdf": b"%PDF", ".docx": b"PK\x03\x04", ".md": None, ".txt": None}


class StoreError(Exception):
    status_code = 400


class InvestorNotFound(StoreError):
    status_code = 404


class InvestorExists(StoreError):
    status_code = 409


class InvalidInput(StoreError):
    status_code = 422


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def data_dir() -> Path:
    configured = os.getenv("ICB_DATA_DIR")
    return Path(configured) if configured else PROJECT_ROOT / "investors"


def investor_path(slug: str) -> Path:
    """The investor's directory; raises InvestorNotFound for a bad slug or an unknown investor."""
    if not SLUG_RE.fullmatch(slug or ""):
        raise InvestorNotFound("No investor has that profile ID.")
    path = data_dir() / slug
    if not (path / "investor.json").is_file():
        raise InvestorNotFound("No investor has that profile ID.")
    return path


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_investor(slug: str) -> dict[str, Any]:
    return json.loads((investor_path(slug) / "investor.json").read_text(encoding="utf-8"))


def list_investors() -> list[dict[str, Any]]:
    base = data_dir()
    if not base.is_dir():
        return []
    investors = []
    for meta in base.glob("*/investor.json"):
        try:
            record = json.loads(meta.read_text(encoding="utf-8"))
            investors.append({"slug": record["slug"], "name": record["name"], "approved_pack": None})
        except (OSError, ValueError, KeyError, TypeError):
            continue  # a damaged record must not hide every other investor
    return sorted(investors, key=lambda r: r["name"].lower())


def create_investor(slug: str, name: str) -> dict[str, Any]:
    if not SLUG_RE.fullmatch(slug or ""):
        raise InvalidInput("Profile IDs use lowercase letters, digits and hyphens, up to 60 characters.")
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise InvalidInput("Enter an investor name of up to 120 characters.")
    path = data_dir() / slug
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise InvestorExists(f"An investor with the profile ID '{slug}' already exists. Choose it from the list to edit it.") from None
    record = {"slug": slug, "name": name, "created_at": now_iso()}
    _atomic_write(path / "investor.json", (json.dumps(record, indent=2) + "\n").encode("utf-8"))
    return {"slug": slug, "name": name, "approved_pack": None}


def read_profile(slug: str) -> dict[str, Any] | None:
    path = investor_path(slug) / "profile.yaml"
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_profile(slug: str, document: dict[str, Any]) -> None:
    path = investor_path(slug)
    _atomic_write(path / "profile.yaml", yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode("utf-8"))
    record = json.loads((path / "investor.json").read_text(encoding="utf-8"))
    if record.get("name") != document["display_name"]:
        record["name"] = document["display_name"]
        _atomic_write(path / "investor.json", (json.dumps(record, indent=2) + "\n").encode("utf-8"))


def note_files(slug: str) -> list[str]:
    notes = investor_path(slug) / "notes"
    if not notes.is_dir():
        return []
    return sorted(p.name for p in notes.iterdir() if p.is_file() and not p.name.startswith("."))


def _safe_filename(original: str) -> str:
    base = (original or "").replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return cleaned[-120:] or "notes"


def save_notes(slug: str, uploads: list[tuple[str, bytes]], max_bytes: int) -> list[str]:
    """Check every upload first, then write them all; one bad file saves nothing."""
    notes = investor_path(slug) / "notes"
    if not uploads:
        raise InvalidInput("Attach at least one file.")
    prepared: list[tuple[str, bytes]] = []
    for original, data in uploads:
        name = _safe_filename(original)
        ext = Path(name).suffix.lower()
        if ext not in NOTE_SIGNATURES:
            raise InvalidInput(f"{original} is not a .pdf, .docx, .md or .txt file.")
        if len(data) > max_bytes:
            raise InvalidInput(f"{original} is larger than the {max_bytes // (1024 * 1024)} MB limit.")
        signature = NOTE_SIGNATURES[ext]
        if signature is not None and not data.startswith(signature):
            raise InvalidInput(f"{original} does not look like a real {ext} file.")
        if signature is None:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                raise InvalidInput(f"{original} is not a UTF-8 text file.") from None
        prepared.append((name, data))
    if len(set(note_files(slug)) | {name for name, _ in prepared}) > MAX_NOTE_FILES:
        raise InvalidInput(f"An investor can have at most {MAX_NOTE_FILES} note files.")
    for name, data in prepared:
        _atomic_write(notes / name, data)
    return [name for name, _ in prepared]
