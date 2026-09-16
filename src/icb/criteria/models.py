"""The Criteria Pack document and the JSON schema the model fills (CLAUDE.md §7).

Every generated element carries `grounded_in` (profile field paths it derives from) or
`needs_input` (one specific question). A pack with any `needs_input` or open question cannot
be approved, which is how "never invent investor preferences" is enforced in code.

Structural rules — 6–10 factors, integer weights summing to 100, exactly five rubric levels,
a 150–250 word thesis — are validated here, not left to the prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Short = Annotated[str, Field(max_length=200)]
Text = Annotated[str, Field(max_length=5_000)]
Ident = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,58}[a-z0-9]$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Grounded(_Strict):
    grounded_in: Annotated[list[Short], Field(max_length=20)] = []
    needs_input: Short | None = None


class Thesis(Grounded):
    text: Text = ""

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\b[\w'-]+\b", self.text))


class HardCriterion(Grounded):
    criterion_id: Ident
    label: Short
    requirement: Short
    test: Text
    evidence_required: Annotated[list[Short], Field(max_length=10)] = []


class RubricLevel(_Strict):
    score: Annotated[int, Field(ge=1, le=5)]
    evidence: Text


class Factor(Grounded):
    factor_id: Ident
    label: Short
    short_label: Annotated[str, Field(max_length=12)]
    weight: Annotated[int, Field(ge=1, le=100)]
    weight_rationale: Text
    rubric: list[RubricLevel]
    floor: Annotated[int, Field(ge=1, le=5)] | None = None
    evidence_required: Annotated[list[Short], Field(max_length=10)] = []

    @model_validator(mode="after")
    def _five_distinct_levels(self) -> Factor:
        scores = sorted(level.score for level in self.rubric)
        if scores != [1, 2, 3, 4, 5]:
            raise ValueError(f"factor '{self.factor_id}' needs exactly one rubric level for each score 1-5")
        return self


class DealBreaker(Grounded):
    deal_breaker_id: Ident
    walk_away_condition: Short
    trigger: Text


class Concern(Grounded):
    concern_id: Ident
    factor_id: Ident
    condition: Short
    consequence: Text


class ReviewCadence(Grounded):
    triggers: Annotated[list[Short], Field(max_length=10)] = []
    min_sample_size: Annotated[int, Field(ge=1, le=1_000)] = 10
    outcome_data: Annotated[list[Short], Field(max_length=10)] = []
    versioning: Text = ""


class CriteriaDraft(_Strict):
    """Exactly what the model returns. The pack adds provenance around it."""

    thesis: Thesis
    hard_criteria: Annotated[list[HardCriterion], Field(max_length=30)] = []
    factors: list[Factor]
    deal_breakers: Annotated[list[DealBreaker], Field(max_length=20)] = []
    concerns: Annotated[list[Concern], Field(max_length=30)] = []
    consistency_controls: Annotated[list[Text], Field(max_length=20)] = []
    bias_checks: Annotated[list[Text], Field(max_length=20)] = []
    exception_procedure: Text = ""
    review_cadence: ReviewCadence
    advance_threshold: Annotated[float, Field(ge=1.0, le=5.0)]
    max_unscored_weight_pct: Annotated[int, Field(ge=0, le=100)]
    open_questions: Annotated[list[Short], Field(max_length=40)] = []
    not_applied: Annotated[list[Short], Field(max_length=40)] = []

    @model_validator(mode="after")
    def _structure(self) -> CriteriaDraft:
        if not 6 <= len(self.factors) <= 10:
            raise ValueError(f"a pack needs 6-10 scoring factors, not {len(self.factors)}")
        total = sum(factor.weight for factor in self.factors)
        if total != 100:
            raise ValueError(f"factor weights must sum to 100, not {total}")
        for name, ids in (
            ("factor", [f.factor_id for f in self.factors]),
            ("hard criterion", [c.criterion_id for c in self.hard_criteria]),
            ("deal-breaker", [d.deal_breaker_id for d in self.deal_breakers]),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError(f"every {name} id must be unique")
        known = {f.factor_id for f in self.factors}
        unknown = sorted({c.factor_id for c in self.concerns} - known)
        if unknown:
            raise ValueError(f"concerns name unknown factors: {', '.join(unknown)}")
        words = self.thesis.word_count
        if self.thesis.needs_input is None and not 150 <= words <= 250:
            raise ValueError(f"the thesis must be 150-250 words, not {words}")
        return self

    def blocking_questions(self) -> list[str]:
        """Everything that must be answered before the investor can approve this pack."""
        questions = list(self.open_questions)
        elements: list[tuple[str, Grounded]] = [("thesis", self.thesis), ("review cadence", self.review_cadence)]
        elements += [(f"hard criterion '{c.label}'", c) for c in self.hard_criteria]
        elements += [(f"factor '{f.label}'", f) for f in self.factors]
        elements += [(f"deal-breaker '{d.walk_away_condition}'", d) for d in self.deal_breakers]
        elements += [(f"concern '{c.condition}'", c) for c in self.concerns]
        for where, element in elements:
            if element.needs_input:
                questions.append(f"{where}: {element.needs_input}")
        return questions


class CriteriaPack(_Strict):
    schema_version: Literal[1] = 1
    version: Annotated[int, Field(ge=1)]
    slug: Short
    display_name: Short
    status: Literal["draft", "approved"] = "draft"
    created_at: str
    approved_at: str | None = None
    model: Short = ""
    profile_updated_at: str | None = None
    draft: CriteriaDraft

    def canonical_json(self) -> str:
        """Stable bytes for hashing: content only, so key order or timestamps can't change it."""
        payload = {
            "schema_version": self.schema_version,
            "version": self.version,
            "slug": self.slug,
            "draft": self.draft.model_dump(mode="json"),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "hash": self.content_hash(),
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "factors": [
                {"factor_id": f.factor_id, "label": f.label, "short_label": f.short_label,
                 "weight": f.weight, "floor": f.floor}
                for f in self.draft.factors
            ],
            "hard_criteria": [{"criterion_id": c.criterion_id, "label": c.label, "requirement": c.requirement}
                              for c in self.draft.hard_criteria],
            "deal_breakers": len(self.draft.deal_breakers),
            "advance_threshold": self.draft.advance_threshold,
            "max_unscored_weight_pct": self.draft.max_unscored_weight_pct,
            "open_questions": self.draft.blocking_questions(),
            "not_applied": self.draft.not_applied,
            "thesis_words": self.draft.thesis.word_count,
        }


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --- the schema the model fills ------------------------------------------------------------

def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required}


_STR = {"type": "string"}
_GROUNDING = {
    "grounded_in": {"type": "array", "items": _STR,
                    "description": "Profile field paths this element derives from, e.g. fields.check_size."},
    "needs_input": {"type": ["string", "null"],
                    "description": "One specific question for the investor when this cannot be grounded; null otherwise."},
}

DRAFT_SCHEMA: dict[str, Any] = _obj(
    {
        "thesis": _obj({**_GROUNDING, "text": {**_STR, "description": "150-250 words."}}, ["text", "grounded_in", "needs_input"]),
        "hard_criteria": {"type": "array", "items": _obj(
            {**_GROUNDING, "criterion_id": _STR, "label": _STR, "requirement": _STR, "test": _STR,
             "evidence_required": {"type": "array", "items": _STR}},
            ["criterion_id", "label", "requirement", "test", "evidence_required", "grounded_in", "needs_input"])},
        "factors": {"type": "array", "items": _obj(
            {**_GROUNDING, "factor_id": _STR, "label": _STR,
             "short_label": {**_STR, "description": "At most 12 characters."},
             "weight": {"type": "integer", "description": "Integer; all weights sum to 100."},
             "weight_rationale": _STR,
             "rubric": {"type": "array", "description": "Exactly five levels, scores 1-5.", "items": _obj(
                 {"score": {"type": "integer"}, "evidence": _STR}, ["score", "evidence"])},
             "floor": {"type": ["integer", "null"]},
             "evidence_required": {"type": "array", "items": _STR}},
            ["factor_id", "label", "short_label", "weight", "weight_rationale", "rubric", "floor",
             "evidence_required", "grounded_in", "needs_input"])},
        "deal_breakers": {"type": "array", "items": _obj(
            {**_GROUNDING, "deal_breaker_id": _STR, "walk_away_condition": _STR, "trigger": _STR},
            ["deal_breaker_id", "walk_away_condition", "trigger", "grounded_in", "needs_input"])},
        "concerns": {"type": "array", "items": _obj(
            {**_GROUNDING, "concern_id": _STR, "factor_id": _STR, "condition": _STR, "consequence": _STR},
            ["concern_id", "factor_id", "condition", "consequence", "grounded_in", "needs_input"])},
        "consistency_controls": {"type": "array", "items": _STR},
        "bias_checks": {"type": "array", "items": _STR},
        "exception_procedure": _STR,
        "review_cadence": _obj(
            {**_GROUNDING, "triggers": {"type": "array", "items": _STR},
             "min_sample_size": {"type": "integer"},
             "outcome_data": {"type": "array", "items": _STR},
             "versioning": _STR},
            ["triggers", "min_sample_size", "outcome_data", "versioning", "grounded_in", "needs_input"]),
        "advance_threshold": {"type": "number", "description": "Weighted 1.0-5.0."},
        "max_unscored_weight_pct": {"type": "integer"},
        "open_questions": {"type": "array", "items": _STR},
        "not_applied": {"type": "array", "items": _STR},
    },
    ["thesis", "hard_criteria", "factors", "deal_breakers", "concerns", "consistency_controls", "bias_checks",
     "exception_procedure", "review_cadence", "advance_threshold", "max_unscored_weight_pct",
     "open_questions", "not_applied"],
)
