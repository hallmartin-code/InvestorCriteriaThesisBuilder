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

from icb.profile.models import FIELD_KEYS, SLUG_PATTERN

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


def profile_progress(path: Path) -> tuple[bool, int]:
    """(inputs_complete, open_questions) for a stored profile. Screening stays closed until complete."""
    profile: Any = None
    stored = path / "profile.yaml"
    if stored.is_file():
        try:
            profile = yaml.safe_load(stored.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            profile = None
    fields = (profile or {}).get("fields") or {} if isinstance(profile, dict) else {}
    open_questions = sum(
        1 for key in FIELD_KEYS
        if (fields.get(key) or {}).get("status", "not_provided") == "not_provided"
    )
    return open_questions == 0, open_questions


def list_investors() -> list[dict[str, Any]]:
    base = data_dir()
    if not base.is_dir():
        return []
    investors = []
    for meta in base.glob("*/investor.json"):
        try:
            record = json.loads(meta.read_text(encoding="utf-8"))
            complete, open_questions = profile_progress(meta.parent)
            investors.append({
                "slug": record["slug"], "name": record["name"],
                "approved_pack": approved_pack_summary(meta.parent),
                "inputs_complete": complete, "open_questions": open_questions,
            })
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
    return {"slug": slug, "name": name, "approved_pack": None,
            "inputs_complete": False, "open_questions": len(FIELD_KEYS)}


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


def note_texts(slug: str) -> list[tuple[str, str]]:
    """Thesis materials as (filename, text). Unreadable files are skipped, not fatal."""
    notes = investor_path(slug) / "notes"
    out: list[tuple[str, str]] = []
    for name in note_files(slug):
        try:
            out.append((name, _extract_text(notes / name)))
        except Exception:  # a damaged attachment must not block a build
            continue
    return [(name, text) for name, text in out if text.strip()]


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        import pymupdf  # imported lazily: only note ingestion needs it

        with pymupdf.open(path) as document:
            return "\n\n".join(page.get_text() for page in document)
    if suffix == ".docx":
        import docx  # python-docx

        return "\n".join(paragraph.text for paragraph in docx.Document(str(path)).paragraphs)
    return ""


# --- criteria packs -------------------------------------------------------------------------

CRITERIA_STATUSES = ("draft", "approved")


def criteria_dir(slug: str) -> Path:
    return investor_path(slug) / "criteria"


def _criteria_file(slug: str, version: int, status: str) -> Path:
    if status not in CRITERIA_STATUSES:
        raise InvalidInput("A Criteria Pack is either a draft or approved.")
    return criteria_dir(slug) / f"v{version}.{status}.json"


def criteria_versions(slug: str, status: str = "draft") -> list[int]:
    directory = criteria_dir(slug)
    if not directory.is_dir():
        return []
    versions = []
    for path in directory.glob(f"v*.{status}.json"):
        try:
            versions.append(int(path.name.split(".")[0][1:]))
        except ValueError:
            continue
    return sorted(versions)


def next_criteria_version(slug: str) -> int:
    seen = criteria_versions(slug, "draft") + criteria_versions(slug, "approved")
    return (max(seen) + 1) if seen else 1


def write_criteria(slug: str, pack: dict[str, Any]) -> None:
    """Approved packs are immutable: an existing approved file is never overwritten."""
    version, status = int(pack["version"]), str(pack["status"])
    path = _criteria_file(slug, version, status)
    if status == "approved" and path.is_file():
        raise InvalidInput(f"Criteria Pack v{version} is already approved and cannot be changed.")
    _atomic_write(path, (json.dumps(pack, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def read_criteria(slug: str, version: int | None = None, status: str = "draft") -> dict[str, Any] | None:
    if version is None:
        versions = criteria_versions(slug, status)
        if not versions:
            return None
        version = versions[-1]
    path = _criteria_file(slug, version, status)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def approved_pack_summary(path: Path) -> dict[str, Any] | None:
    """{version, hash} of the newest approved pack, for the investor list. None when there is none."""
    directory = path / "criteria"
    if not directory.is_dir():
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for file in directory.glob("v*.approved.json"):
        try:
            version = int(file.name.split(".")[0][1:])
            pack = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if best is None or version > best[0]:
            best = (version, pack)
    if best is None:
        return None
    version, pack = best
    return {"version": version, "hash": pack.get("content_hash", ""), "approved_at": pack.get("approved_at")}


def write_scorecard(slug: str, stem: str, pdf: bytes, payload: dict[str, Any]) -> dict[str, str]:
    """Store one screening's artifacts; returns their paths."""
    directory = investor_path(slug) / "scorecards"
    name = _safe_filename(stem) or "scorecard"
    _atomic_write(directory / f"{name}.pdf", pdf)
    _atomic_write(directory / f"{name}.json", (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return {"pdf": str(directory / f"{name}.pdf"), "json": str(directory / f"{name}.json")}


def read_scorecard(slug: str, name: str, suffix: str) -> Path:
    path = investor_path(slug) / "scorecards" / f"{_safe_filename(name)}.{suffix}"
    if not path.is_file():
        raise InvestorNotFound("That scorecard is no longer available.")
    return path


def append_decision(slug: str, entry: dict[str, Any]) -> None:
    """The decision log is append-only; earlier lines are never rewritten."""
    path = investor_path(slug) / "decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def read_decisions(slug: str) -> list[dict[str, Any]]:
    path = investor_path(slug) / "decisions.jsonl"
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


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
