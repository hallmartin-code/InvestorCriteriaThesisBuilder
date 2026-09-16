"""The screening document (templates/one_pager.md §5).

The model returns a `ScreeningExtraction`: deck facts only, every one carrying slides and a
verbatim excerpt. Code then copies the pack's labels, weights, floors and walk-away conditions
onto it and computes the `Decision`, so the model never decides anything.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SnapshotField(_Strict):
    value: Short | None = None
    classification: Classification = "NOT PROVIDED"
    confidence: Annotated[float, Field(ge=0, le=1)] = 0.0
    slides: Slides = []
    excerpt: Quote = ""
    amount_usd: Annotated[int, Field(ge=0, le=10**13)] | None = None


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


class Evidence(_Strict):
    quote: Quote = ""
    slide: Annotated[int, Field(ge=1)] | None = None
    evidence_type: EvidenceType = "deck_statement"


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


class EvidenceRequest(_Strict):
    request: Short
    audience: Audience = "Founder"
    reason: Text = ""
    linked_to: Short = ""
    priority: Annotated[int, Field(ge=1)] = 1


class ScreeningExtraction(_Strict):
    """Exactly what the model returns."""

    company: CompanySnapshot = CompanySnapshot()
    hard_criteria: Annotated[list[HardCriterionResult], Field(max_length=30)] = []
    factors: Annotated[list[FactorResult], Field(max_length=10)] = []
    deal_breakers_triggered: Annotated[list[TriggeredDealBreaker], Field(max_length=20)] = []
    concerns: Annotated[list[ConcernResult], Field(max_length=30)] = []
    bias_flags: Annotated[list[BiasFlag], Field(max_length=20)] = []
    evidence_requests: Annotated[list[EvidenceRequest], Field(max_length=20)] = []
    screening_summary: Text = ""
    thesis_fit: Annotated[str, Field(max_length=160)] = ""


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
