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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Short = Annotated[str, Field(max_length=200)]
Text = Annotated[str, Field(max_length=5_000)]
Ident = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,58}[a-z0-9]$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Grounded(_Strict):
    grounded_in: Annotated[list[Short], Field(max_length=20)] = []
    needs_input: Short | None = None

    @field_validator("grounded_in", mode="before")
    @classmethod
    def _split_paths(cls, value: Any) -> Any:
        """The schema asks for a comma-separated string (nested arrays enlarge the grammar)."""
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    # The builder schema carries no nullable types (an API limit): "" means "nothing to ask".
    @field_validator("needs_input", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value


class Thesis(Grounded):
    text: Text = ""

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\b[\w'-]+\b", self.text))


def _split_list(value: Any) -> Any:
    """Evidence types arrive comma-separated; nested arrays enlarge the compiled grammar."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class HardCriterion(Grounded):
    criterion_id: Ident
    label: Short
    requirement: Short
    test: Text
    evidence_required: Annotated[list[Short], Field(max_length=10)] = []

    _split = field_validator("evidence_required", mode="before")(_split_list)


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

    _split = field_validator("evidence_required", mode="before")(_split_list)

    @model_validator(mode="before")
    @classmethod
    def _rubric_from_fields(cls, data: Any) -> Any:
        """The schema asks for rubric_1..rubric_5 (no nested arrays)."""
        if isinstance(data, dict) and "rubric_1" in data:
            data = dict(data)
            data.setdefault("rubric", [{"score": score, "evidence": data.pop(f"rubric_{score}", "")}
                                       for score in range(1, 6)])
        return data

    @field_validator("rubric", mode="before")
    @classmethod
    def _levels_from_strings(cls, value: Any) -> Any:
        """A plain list of five strings, lowest first, is also accepted."""
        if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            return [{"score": index, "evidence": text} for index, text in enumerate(value, start=1)]
        return value

    @field_validator("floor", mode="before")
    @classmethod
    def _zero_is_none(cls, value: Any) -> Any:
        return None if value in (0, "", "0") else value

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

    @model_validator(mode="before")
    @classmethod
    def _from_flat_schema(cls, data: Any) -> Any:
        """The builder schema is flattened to keep the compiled grammar small; rebuild the document."""
        if not isinstance(data, dict):
            return data
        data = dict(data)

        if "advance_threshold_tenths" in data:
            tenths = data.pop("advance_threshold_tenths")
            data.setdefault("advance_threshold", round(float(tenths) / 10, 2) if tenths else 0)

        if "thesis_text" in data:
            data.setdefault("thesis", {"text": data.pop("thesis_text"),
                                       "grounded_in": data.pop("thesis_grounded_in", ""),
                                       "needs_input": data.pop("thesis_needs_input", "")})

        if "review_triggers" in data or "review_versioning" in data:
            data.setdefault("review_cadence", {
                "triggers": data.pop("review_triggers", []),
                "min_sample_size": data.pop("review_min_sample_size", 10) or 10,
                "outcome_data": data.pop("review_outcome_data", []),
                "versioning": data.pop("review_versioning", ""),
            })

        if isinstance(data.get("findings"), list):
            breakers, concerns = [], []
            for finding in data.pop("findings"):
                if not isinstance(finding, dict):
                    continue
                shared = {key: finding.get(key, "") for key in ("grounded_in", "needs_input")}
                if finding.get("kind") == "concern":
                    concerns.append({"concern_id": finding.get("id", ""), "factor_id": finding.get("factor_id", ""),
                                     "condition": finding.get("condition", ""),
                                     "consequence": finding.get("detail", ""), **shared})
                else:
                    breakers.append({"deal_breaker_id": finding.get("id", ""),
                                     "walk_away_condition": finding.get("condition", ""),
                                     "trigger": finding.get("detail", ""), **shared})
            data.setdefault("deal_breakers", breakers)
            data.setdefault("concerns", concerns)
        return data

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
# No nullable or union types, and as few nested object types as possible: the API rejects
# schemas with many unions or an over-large compiled grammar.
_GROUNDING = {
    "grounded_in": {"type": "array", "items": _STR,
                    "description": "Profile field paths this element derives from, e.g. fields.check_size."},
    "needs_input": {**_STR,
                    "description": "One specific question for the investor when this cannot be grounded; "
                                   "empty string otherwise."},
}

_GROUNDED_FLAT = {
    "grounded_in": {**_STR, "description": "Comma-separated profile field paths, e.g. fields.check_size, fields.stages."},
    "needs_input": {**_STR, "description": "One specific question for the investor when this cannot be grounded; "
                                           "empty string otherwise."},
}

DRAFT_SCHEMA: dict[str, Any] = _obj(
    {
        "thesis_text": {**_STR, "description": "150-250 words: the belief, the mispricing, the edge, why now."},
        "thesis_grounded_in": _GROUNDED_FLAT["grounded_in"],
        "thesis_needs_input": _GROUNDED_FLAT["needs_input"],
        "hard_criteria": {"type": "array", "items": _obj(
            {**_GROUNDED_FLAT, "criterion_id": _STR, "label": _STR, "requirement": _STR, "test": _STR,
             "evidence_required": {**_STR, "description": "Comma-separated evidence types."}},
            ["criterion_id", "label", "requirement", "test", "evidence_required", "grounded_in", "needs_input"])},
        "factors": {"type": "array", "items": _obj(
            {**_GROUNDED_FLAT, "factor_id": _STR, "label": _STR,
             "short_label": {**_STR, "description": "At most 12 characters."},
             "weight": {"type": "integer", "description": "Integer; all weights sum to 100."},
             "weight_rationale": _STR,
             "rubric_1": {**_STR, "description": "Observable evidence for score 1."},
             "rubric_2": {**_STR, "description": "Observable evidence for score 2."},
             "rubric_3": {**_STR, "description": "Observable evidence for score 3."},
             "rubric_4": {**_STR, "description": "Observable evidence for score 4."},
             "rubric_5": {**_STR, "description": "Observable evidence for score 5."},
             "floor": {"type": "integer", "description": "Minimum acceptable score for this factor, or 0 for none."},
             "evidence_required": {**_STR, "description": "Comma-separated evidence types."}},
            ["factor_id", "label", "short_label", "weight", "weight_rationale", "rubric_1", "rubric_2",
             "rubric_3", "rubric_4", "rubric_5", "floor", "evidence_required", "grounded_in", "needs_input"])},
        "findings": {"type": "array",
                     "description": "Deal-breakers (walk away) and concerns (lower one named factor).",
                     "items": _obj(
            {**_GROUNDED_FLAT, "kind": {"type": "string", "enum": ["deal_breaker", "concern"]},
             "id": {**_STR, "description": "deal_breaker_id or concern_id."},
             "factor_id": {**_STR, "description": "For a concern, the factor it lowers; empty for a deal-breaker."},
             "condition": {**_STR, "description": "The walk-away condition, or the concern's condition."},
             "detail": {**_STR, "description": "The observable trigger, or the consequence."}},
            ["kind", "id", "factor_id", "condition", "detail", "grounded_in", "needs_input"])},
        "consistency_controls": {"type": "array", "items": _STR},
        "bias_checks": {"type": "array", "items": _STR},
        "exception_procedure": _STR,
        "review_triggers": {"type": "array", "items": _STR},
        "review_min_sample_size": {"type": "integer"},
        "review_outcome_data": {"type": "array", "items": _STR},
        "review_versioning": _STR,
        "advance_threshold_tenths": {"type": "integer",
                                     "description": "The weighted score needed to advance, in tenths: 35 means 3.5."},
        "max_unscored_weight_pct": {"type": "integer"},
        "open_questions": {"type": "array", "items": _STR},
        "not_applied": {"type": "array", "items": _STR},
    },
    ["thesis_text", "thesis_grounded_in", "thesis_needs_input", "hard_criteria", "factors", "findings",
     "consistency_controls", "bias_checks", "exception_procedure", "review_triggers", "review_min_sample_size",
     "review_outcome_data", "review_versioning", "advance_threshold_tenths", "max_unscored_weight_pct",
     "open_questions", "not_applied"],
)
