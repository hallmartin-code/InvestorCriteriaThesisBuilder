"""Field status, missing-input questions, and consistency checks for an investor profile.

These mirror the live checks in web/index.html. The server's result is the one that is stored:
a field is `provided` only when its value is complete, whatever status the client sent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from icb.profile.models import FIELD_KEYS, ProfileDocument

QUESTIONS: dict[str, str] = {
    "investor_type": "What type of investor is this: angel, family office, fund, or corporate?",
    "capital_available_usd": "How much capital is available to deploy?",
    "check_size": "What is the check size range? Enter both a minimum and a maximum.",
    "follow_on_reserve_policy": "What is the follow-on reserve policy? Or mark it No preference.",
    "return_objective": "What return does the investor need? A target multiple or IRR is optional.",
    "liquidity_objective": "What are the liquidity needs: distributions, timing, appetite for secondaries?",
    "time_horizon_years": "Over how many years can the capital stay invested?",
    "prior_investments": "What prior investments has the investor made, and how did they turn out? Or confirm there are none.",
    "stages": "Which stages does the investor back?",
    "sectors": "Which sectors and subsectors are in scope?",
    "geographies": "Which geographies are in scope?",
    "ownership_target_pct": "What ownership percentage does the investor target?",
    "round_size": "What round sizes fit? Enter both a minimum and a maximum.",
    "instruments_accepted": "Which instruments will the investor accept?",
    "minimum_traction": "What minimum traction must a company show? Choose a metric and enter the threshold.",
    "instant_no_filters": "What conditions are an instant no?",
    "thesis_notes": "Are there thesis notes or materials? Paste or attach them, or mark No thesis notes yet.",
}

PRIOR_REQUIRED = (
    ("company", "company"), ("year", "year"), ("stage", "stage"),
    ("sector", "sector"), ("check_usd", "check size"), ("outcome", "outcome"),
)


def is_empty(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    if isinstance(value, dict):
        return all(is_empty(v) for v in value.values())
    return False


def _both(value: Any) -> bool:
    return bool(value) and value.get("min_usd") is not None and value.get("max_usd") is not None


def _has_text(key: str) -> Callable[[Any], bool]:
    return lambda value: bool(value) and not is_empty(value.get(key))


COMPLETE: dict[str, Callable[[Any], bool]] = {
    "investor_type": lambda v: v is not None,
    "capital_available_usd": lambda v: v is not None,
    "check_size": _both,
    "follow_on_reserve_policy": lambda v: not is_empty(v),
    "return_objective": _has_text("text"),
    "liquidity_objective": lambda v: not is_empty(v),
    "time_horizon_years": lambda v: bool(v) and v.get("min") is not None,
    "stages": bool,
    "sectors": lambda v: bool(v) and all(not is_empty(row.get("sector")) for row in v),
    "geographies": bool,
    "ownership_target_pct": lambda v: v is not None,
    "round_size": _both,
    "instruments_accepted": bool,
    "minimum_traction": lambda v: bool(v) and bool(v.get("metric")) and not is_empty(v.get("threshold")),
    "instant_no_filters": bool,
    "thesis_notes": lambda v: bool(v) and (not is_empty(v.get("text")) or bool(v.get("files"))),
}


def prior_gaps(rows: Iterable[dict[str, Any]] | None) -> list[tuple[int, list[str]]]:
    gaps = []
    for index, row in enumerate(rows or [], start=1):
        missing = [label for key, label in PRIOR_REQUIRED if is_empty(row.get(key))]
        if missing:
            gaps.append((index, missing))
    return gaps


def _question(key: str, value: Any) -> str:
    if key == "prior_investments" and value:
        gaps = prior_gaps(value)
        if gaps:
            return "Complete " + "; ".join(f"investment {i} ({', '.join(m)})" for i, m in gaps) + "."
    if key == "sectors" and value and any(is_empty(row.get("sector")) for row in value):
        return "Name the sector for every sector row."
    return QUESTIONS[key]


def issues(fields: dict[str, dict[str, Any]], today: date | None = None) -> list[str]:
    """Contradictions between answers. They are reported, never corrected, and never block saving."""
    year_now = (today or date.today()).year
    found: list[str] = []

    def value(key: str) -> Any:
        return fields[key]["value"] if fields[key]["status"] != "no_preference" else None

    check, round_, horizon = value("check_size") or {}, value("round_size") or {}, value("time_horizon_years") or {}

    def inverted(r: dict[str, Any], lo: str, hi: str) -> bool:
        return r.get(lo) is not None and r.get(hi) is not None and r[lo] > r[hi]

    if inverted(check, "min_usd", "max_usd"):
        found.append("The minimum check size is larger than the maximum.")
    if inverted(round_, "min_usd", "max_usd"):
        found.append("The minimum round size is larger than the maximum.")
    if inverted(horizon, "min", "max"):
        found.append("The minimum time horizon is longer than the maximum.")
    capital = value("capital_available_usd")
    if capital is not None and check.get("max_usd") is not None and check["max_usd"] > capital:
        found.append("The maximum check size is larger than the capital available.")
    if round_.get("max_usd") is not None and check.get("max_usd") is not None and check["max_usd"] > round_["max_usd"]:
        found.append("The maximum check size is larger than the maximum round size.")
    ownership = value("ownership_target_pct")
    if ownership is not None and (ownership <= 0 or ownership > 100):
        found.append("The ownership target must be above 0% and at most 100%.")
    for index, row in enumerate(value("prior_investments") or [], start=1):
        year = row.get("year")
        if year is not None and (year < 1950 or year > year_now):
            found.append(f"Investment {index}: the year {year} looks wrong.")
    return found


def normalize(document: ProfileDocument, stored_note_files: Iterable[str] = ()) -> dict[str, Any]:
    """Return the fields to store (with server-decided statuses), the open questions, and any issues."""
    has_stored_notes = bool(list(stored_note_files))
    fields: dict[str, dict[str, Any]] = {}
    questions: list[dict[str, str]] = []

    for key in FIELD_KEYS:
        entry = document.fields.get(key)
        source = entry.source if entry else "intake"
        value = entry.value if entry else None

        if entry and entry.status == "no_preference":
            fields[key] = {"status": "no_preference", "value": None, "source": source}
            continue

        record: dict[str, Any] = {"status": "not_provided", "value": value, "source": source}
        if key == "prior_investments":
            if entry and entry.affirmed_none:
                record.update(status="provided", value=[], affirmed_none=True)
            elif value and not prior_gaps(value):
                record["status"] = "provided"
        elif COMPLETE[key](value) or (key == "thesis_notes" and has_stored_notes):
            record["status"] = "provided"

        fields[key] = record
        if record["status"] == "not_provided":
            questions.append({"field": key, "question": _question(key, value)})

    return {"fields": fields, "questions": questions, "issues": issues(fields)}
