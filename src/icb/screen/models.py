"""The screening document (templates/one_pager.md §5).

The model returns a `ScreeningExtraction`: deck facts only, every one carrying slides and a
verbatim excerpt. Code then copies the pack's labels, weights, floors and walk-away conditions
onto it and computes the `Decision`, so the model never decides anything.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Short = Annotated[str, Field(max_length=200)]
Text = Annotated[str, Field(max_length=2_000)]
Quote = Annotated[str, Field(max_length=400)]
Slides = Annotated[list[Annotated[int, Field(ge=1)]], Field(max_length=20)]

Classification = Literal["FACT", "INFERENCE", "NOT PROVIDED"]
CriterionResult = Literal["MET", "NOT MET", "UNVERIFIED"]
Severity = Literal["HIGH", "MEDIUM", "LOW"]
BiasType = Literal["Momentum", "Social proof", "Overconfidence"]
Audience = Literal["Founder", "Investor", "Legal counsel", "Financial advisor", "Technical advisor"]
EvidenceType = Literal["deck_statement", "financials", "cap_table", "customer_reference",
                       "third_party_data", "legal_doc"]
ValuationBasis = Literal["pre-money", "post-money", "not stated"]
DECISIONS = ("ADVANCE", "PASS", "HOLD — REQUEST EVIDENCE")
EVIDENCE_TYPES = frozenset(get_args(EvidenceType))
BIAS_TYPES = frozenset(get_args(BiasType))
AUDIENCES = frozenset(get_args(Audience))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _blank_to_none(value: Any) -> Any:
    """The extraction schema carries no nullable types (an API limit): "" and 0 mean "not stated"."""
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value == 0:
        return None
    return value


class SnapshotField(_Strict):
    value: Short | None = None
    classification: Classification = "NOT PROVIDED"
    confidence: Annotated[float, Field(ge=0, le=1)] = 0.0
    slides: Slides = []
    excerpt: Quote = ""
    amount_usd: Annotated[int, Field(ge=0, le=10**13)] | None = None

    _empty = field_validator("value", "amount_usd", mode="before")(_blank_to_none)

    @field_validator("confidence", mode="before")
    @classmethod
    def _percent_to_fraction(cls, value: Any) -> Any:
        """The schema asks for 0-100 (integers keep the compiled grammar small)."""
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 1:
            return float(value) / 100
        return value


class CompanySnapshot(_Strict):
    name: SnapshotField = SnapshotField()
    sector: SnapshotField = SnapshotField()
    subsector: SnapshotField = SnapshotField()
    stage: SnapshotField = SnapshotField()
    geography: SnapshotField = SnapshotField()
    revenue: SnapshotField = SnapshotField()
    key_traction: SnapshotField = SnapshotField()
    raise_amount: SnapshotField = SnapshotField()
    instrument: SnapshotField = SnapshotField()
    valuation: SnapshotField = SnapshotField()
    valuation_basis: ValuationBasis = "not stated"
    amount_committed: SnapshotField = SnapshotField()
    lead_investor: SnapshotField = SnapshotField()


def _parts(line: str, count: int) -> list[str]:
    pieces = [piece.strip() for piece in str(line).split("|")]
    pieces += [""] * (count - len(pieces))
    return pieces[:count - 1] + ["|".join(pieces[count - 1:]).strip()] if len(pieces) > count else pieces


def _slide_numbers(text: str) -> list[int]:
    return [int(number) for number in re.findall(r"\d+", text or "")][:20]


def _evidence_from_line(line: str) -> dict[str, Any]:
    """"S12 | deck_statement | quote" -> the structured form."""
    slide, kind, quote = _parts(line, 3)
    numbers = _slide_numbers(slide)
    return {"quote": quote or line.strip(), "slide": numbers[0] if numbers else None,
            "evidence_type": kind if kind in EVIDENCE_TYPES else "deck_statement"}


def _bias_from_line(line: str) -> dict[str, Any]:
    """"Momentum | signal | S4" -> the structured form."""
    kind, signal, slides = _parts(line, 3)
    return {"type": kind if kind in BIAS_TYPES else "Momentum",
            "signal": signal or line.strip(), "slides": _slide_numbers(slides), "affected_factor_id": None}


def _request_from_line(line: str) -> dict[str, Any]:
    """"Founder | request | reason | linked_to" -> the structured form."""
    audience, request, reason, linked = _parts(line, 4)
    return {"audience": audience if audience in AUDIENCES else "Founder",
            "request": request or line.strip(), "reason": reason, "linked_to": linked, "priority": 1}


class Evidence(_Strict):
    quote: Quote = ""
    slide: Annotated[int, Field(ge=1)] | None = None
    evidence_type: EvidenceType = "deck_statement"

    _empty = field_validator("slide", mode="before")(_blank_to_none)

    @model_validator(mode="before")
    @classmethod
    def _from_line(cls, data: Any) -> Any:
        return _evidence_from_line(data) if isinstance(data, str) else data


class HardCriterionResult(_Strict):
    criterion_id: Short
    result: CriterionResult = "UNVERIFIED"
    deck_evidence: Text = ""
    classification: Classification = "NOT PROVIDED"
    slides: Slides = []
    excerpt: Quote = ""
    # filled from the pack after the call
    label: Short = ""
    requirement: Short = ""


class FactorResult(_Strict):
    factor_id: Short
    score: Annotated[int, Field(ge=1, le=5)] | None = None
    rubric_level_matched: Annotated[int, Field(ge=1, le=5)] | None = None
    evidence_summary: Text = ""
    evidence: Annotated[list[Evidence], Field(max_length=10)] = []
    evidence_standard_met: bool = False
    gap: Text = ""
    # filled from the pack after the call
    label: Short = ""
    short_label: Short = ""
    weight: Annotated[int, Field(ge=0, le=100)] = 0
    floor: Annotated[int, Field(ge=1, le=5)] | None = None

    _empty = field_validator("score", "rubric_level_matched", "floor", mode="before")(_blank_to_none)


class TriggeredDealBreaker(_Strict):
    deal_breaker_id: Short
    issue: Short = ""
    classification: Classification = "FACT"
    slides: Slides = []
    excerpt: Quote = ""
    resolution: Text = ""
    walk_away_condition: Short = ""  # filled from the pack


class ConcernResult(_Strict):
    factor_id: Short = ""
    severity: Severity = "MEDIUM"
    issue: Short = ""
    consequence: Text = ""
    resolution: Text = ""
    classification: Classification = "FACT"
    slides: Slides = []
    excerpt: Quote = ""
    factor_label: Short = ""  # filled from the pack


class BiasFlag(_Strict):
    type: BiasType
    signal: Short
    slides: Slides = []
    affected_factor_id: Short | None = None

    _empty = field_validator("affected_factor_id", mode="before")(_blank_to_none)


class EvidenceRequest(_Strict):
    request: Short
    audience: Audience = "Founder"
    reason: Text = ""
    linked_to: Short = ""
    priority: Annotated[int, Field(ge=1)] = 1


class ScreeningExtraction(_Strict):
    """Exactly what the model returns."""

    company: CompanySnapshot = CompanySnapshot()
    valuation_basis: ValuationBasis = "not stated"
    hard_criteria: Annotated[list[HardCriterionResult], Field(max_length=30)] = []
    factors: Annotated[list[FactorResult], Field(max_length=10)] = []
    deal_breakers_triggered: Annotated[list[TriggeredDealBreaker], Field(max_length=20)] = []
    concerns: Annotated[list[ConcernResult], Field(max_length=30)] = []
    bias_flags: Annotated[list[BiasFlag], Field(max_length=20)] = []
    evidence_requests: Annotated[list[EvidenceRequest], Field(max_length=20)] = []
    screening_summary: Text = ""
    thesis_fit: Annotated[str, Field(max_length=160)] = ""

    @model_validator(mode="before")
    @classmethod
    def _decode_compact_lists(cls, data: Any) -> Any:
        """The schema keeps arrays-of-objects few (a grammar limit), so some lists arrive as text."""
        if not isinstance(data, dict):
            return data
        data = dict(data)

        if isinstance(data.get("findings"), list):
            breakers, concerns = [], []
            for finding in data.pop("findings"):
                if not isinstance(finding, dict):
                    continue
                common = {key: finding.get(key, "") for key in ("issue", "resolution", "classification", "excerpt")}
                common["slides"] = finding.get("slides", [])
                if finding.get("kind") == "deal_breaker" or finding.get("severity") == "DEAL-BREAKER":
                    breakers.append({"deal_breaker_id": finding.get("id", ""), **common})
                else:
                    severity = finding.get("severity", "MEDIUM")
                    concerns.append({"factor_id": finding.get("id", ""),
                                     "severity": severity if severity in {"HIGH", "MEDIUM", "LOW"} else "MEDIUM",
                                     "consequence": finding.get("consequence", ""), **common})
            data.setdefault("deal_breakers_triggered", breakers)
            data.setdefault("concerns", concerns)

        for key, decode in (("bias_flags", _bias_from_line), ("evidence_requests", _request_from_line)):
            values = data.get(key)
            if isinstance(values, list) and any(isinstance(item, str) for item in values):
                data[key] = [decode(item) if isinstance(item, str) else item for item in values]
        return data

    @model_validator(mode="before")
    @classmethod
    def _snapshot_from_entries(cls, data: Any) -> Any:
        """The model returns the snapshot as a list of {field, ...} entries; fold it into the object."""
        if not isinstance(data, dict) or not isinstance(data.get("company"), list):
            return data
        data = dict(data)
        known = set(CompanySnapshot.model_fields)
        snapshot: dict[str, Any] = {}
        for entry in data["company"]:
            if isinstance(entry, dict) and entry.get("field") in known:
                snapshot[entry["field"]] = {k: v for k, v in entry.items() if k != "field"}
        if "valuation_basis" in data:
            snapshot["valuation_basis"] = data["valuation_basis"]
        data["company"] = snapshot
        return data


class Decision(_Strict):
    decision: Literal["ADVANCE", "PASS", "HOLD — REQUEST EVIDENCE"]
    rule: Annotated[int, Field(ge=1, le=5)]
    rule_label: Short
    rule_sentence: Text
    weighted_score: float | None = None
    advance_threshold: float = 0.0
    evidence_coverage: int = 0
    unscored_weight_pct: int = 0
    max_unscored_weight_pct: int = 0
    floor_breaches: list[Short] = []
    criteria_counts: dict[str, int] = {}


class Provenance(_Strict):
    source_filename: Short = ""
    slide_count: int = 0
    parse_warnings: list[Short] = []
    model: Short = ""
    effort: Short = ""
    criteria_pack: dict[str, Any] = {}
    generated_at: Short = ""
    truncations: list[Short] = []
    warnings: list[Short] = []
    cached: bool = False


class Screening(_Strict):
    """The full document: extraction + pack labels + computed decision."""

    schema_version: Literal[1] = 1
    slug: Short
    investor_name: Short
    extraction: ScreeningExtraction
    decision: Decision
    provenance: Provenance
    review: dict[str, Any] | None = None

    def company_name(self) -> str:
        return self.extraction.company.name.value or "Unnamed company"
