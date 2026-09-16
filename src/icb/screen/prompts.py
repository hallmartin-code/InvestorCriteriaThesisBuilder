"""The screening prompt (CLAUDE.md §8, used verbatim) and the extraction schema."""

from __future__ import annotations

import json
from typing import Any

from icb.criteria.models import CriteriaPack
from icb.ingest.router import Deck

PROMPT_VERSION = 1

SYSTEM = """You are screening a startup pitch deck against an investor's approved Criteria Pack. The
pack is the only standard; the deck is the only source of facts.

Rules:
- Extract only what the deck states. Never guess a number, name, valuation, or metric.
  Every result cites 1-based slide numbers.
- For each factor, match the deck's evidence to the rubric level whose observable-evidence
  description it satisfies. If the pack's evidence standard for that factor is not met by
  the deck, set `score` to null and `evidence_standard_met` to false, and state
  the gap. Do not score a factor low because evidence is absent.
- A hard criterion is MET or NOT MET only when the deck states the relevant fact.
  Otherwise it is UNVERIFIED.
- Founder assertions, projections, and "oversubscribed", deadline, or named-investor
  signals are not evidence of quality. Record them in `bias_flags`. They may not raise a
  score unless the pack's evidence standard explicitly accepts them.
- Record a deal-breaker only when its trigger is observably present in the deck.
- Do not recommend advance or pass. That decision is computed from your structured
  results."""


def render_pack(pack: CriteriaPack) -> str:
    """The standard, as the model sees it: ids it must reuse, and the evidence each one needs."""
    draft = pack.draft
    lines = [f"CRITERIA PACK v{pack.version} for {pack.display_name}", "", "INVESTMENT THESIS", draft.thesis.text, ""]

    lines.append("HARD CRITERIA (return one result per criterion_id)")
    for criterion in draft.hard_criteria:
        lines.append(f"- {criterion.criterion_id}: {criterion.label} — requires {criterion.requirement}. "
                     f"Test: {criterion.test} Evidence accepted: {', '.join(criterion.evidence_required) or 'deck statement'}.")
    if draft.not_applied:
        lines.append(f"Not applied (the investor has no preference): {', '.join(draft.not_applied)}")

    lines += ["", "SCORING FACTORS (return one result per factor_id)"]
    for factor in draft.factors:
        lines.append(f"- {factor.factor_id}: {factor.label} (weight {factor.weight}%"
                     + (f", floor {factor.floor}" if factor.floor else "") + ")")
        lines.append(f"  Evidence accepted: {', '.join(factor.evidence_required) or 'deck statement'}")
        for level in sorted(factor.rubric, key=lambda item: item.score):
            lines.append(f"  {level.score}: {level.evidence}")

    lines += ["", "DEAL-BREAKERS (report only when observably present)"]
    for breaker in draft.deal_breakers:
        lines.append(f"- {breaker.deal_breaker_id}: {breaker.walk_away_condition} — trigger: {breaker.trigger}")

    lines += ["", "CONCERNS (lower a named factor; never a walk-away)"]
    for concern in draft.concerns:
        lines.append(f"- {concern.concern_id} on {concern.factor_id}: {concern.condition} — {concern.consequence}")

    if draft.bias_checks:
        lines += ["", "BIAS CHECKS", *[f"- {check}" for check in draft.bias_checks]]
    return "\n".join(lines)


def build_content(deck: Deck, pack: CriteriaPack) -> list[dict[str, Any]]:
    unit = deck.unit
    task = (f"Screen the deck against the pack above. Cite {unit} numbers (1 to {deck.page_count}) for every "
            f"result, quote at most 25 words per piece of evidence, and return null for anything the deck "
            f"does not state. Use the pack's own ids. Do not state a decision.")
    return [*deck.blocks, {"type": "text", "text": render_pack(pack)}, {"type": "text", "text": task}]


def schema_fingerprint(schema: dict[str, Any]) -> str:
    return json.dumps(schema, sort_keys=True, separators=(",", ":"))


# --- the schema the model fills ------------------------------------------------------------

def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required}


_STR = {"type": "string"}
_SLIDES = {"type": "array", "items": {"type": "integer"}, "description": "1-based slide or section numbers."}
_CLASSIFICATION = {"type": "string", "enum": ["FACT", "INFERENCE", "NOT PROVIDED"]}

_SNAPSHOT = _obj(
    {"value": {"type": ["string", "null"]},
     "classification": _CLASSIFICATION,
     "confidence": {"type": "number", "description": "0-1: 0.9+ stated verbatim, 0.3-0.59 inferred."},
     "slides": _SLIDES,
     "excerpt": {**_STR, "description": "Verbatim from the deck, at most 25 words."},
     "amount_usd": {"type": ["integer", "null"], "description": "Currency values normalized to whole USD."}},
    ["value", "classification", "confidence", "slides", "excerpt", "amount_usd"])

_SNAPSHOT_KEYS = ["name", "sector", "subsector", "stage", "geography", "revenue", "key_traction",
                  "raise_amount", "instrument", "valuation", "amount_committed", "lead_investor"]

EXTRACTION_SCHEMA: dict[str, Any] = _obj(
    {
        "company": _obj(
            {**{key: _SNAPSHOT for key in _SNAPSHOT_KEYS},
             "valuation_basis": {"type": "string", "enum": ["pre-money", "post-money", "not stated"]}},
            [*_SNAPSHOT_KEYS, "valuation_basis"]),
        "hard_criteria": {"type": "array", "items": _obj(
            {"criterion_id": _STR,
             "result": {"type": "string", "enum": ["MET", "NOT MET", "UNVERIFIED"]},
             "deck_evidence": {**_STR, "description": "What the deck shows, or what it does not show."},
             "classification": _CLASSIFICATION, "slides": _SLIDES, "excerpt": _STR},
            ["criterion_id", "result", "deck_evidence", "classification", "slides", "excerpt"])},
        "factors": {"type": "array", "items": _obj(
            {"factor_id": _STR,
             "score": {"type": ["integer", "null"], "description": "1-5, or null when the evidence standard is not met."},
             "rubric_level_matched": {"type": ["integer", "null"]},
             "evidence_summary": _STR,
             "evidence": {"type": "array", "items": _obj(
                 {"quote": {**_STR, "description": "Verbatim, at most 25 words."},
                  "slide": {"type": ["integer", "null"]},
                  "evidence_type": {"type": "string", "enum": ["deck_statement", "financials", "cap_table",
                                                               "customer_reference", "third_party_data", "legal_doc"]}},
                 ["quote", "slide", "evidence_type"])},
             "evidence_standard_met": {"type": "boolean"},
             "gap": {**_STR, "description": "What is missing when the factor cannot be scored."}},
            ["factor_id", "score", "rubric_level_matched", "evidence_summary", "evidence",
             "evidence_standard_met", "gap"])},
        "deal_breakers_triggered": {"type": "array", "items": _obj(
            {"deal_breaker_id": _STR, "issue": _STR, "classification": _CLASSIFICATION,
             "slides": _SLIDES, "excerpt": _STR, "resolution": _STR},
            ["deal_breaker_id", "issue", "classification", "slides", "excerpt", "resolution"])},
        "concerns": {"type": "array", "items": _obj(
            {"factor_id": _STR, "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
             "issue": _STR, "consequence": _STR, "resolution": _STR,
             "classification": _CLASSIFICATION, "slides": _SLIDES, "excerpt": _STR},
            ["factor_id", "severity", "issue", "consequence", "resolution", "classification", "slides", "excerpt"])},
        "bias_flags": {"type": "array", "items": _obj(
            {"type": {"type": "string", "enum": ["Momentum", "Social proof", "Overconfidence"]},
             "signal": _STR, "slides": _SLIDES, "affected_factor_id": {"type": ["string", "null"]}},
            ["type", "signal", "slides", "affected_factor_id"])},
        "evidence_requests": {"type": "array", "items": _obj(
            {"request": _STR,
             "audience": {"type": "string", "enum": ["Founder", "Investor", "Legal counsel",
                                                     "Financial advisor", "Technical advisor"]},
             "reason": _STR, "linked_to": {**_STR, "description": "The criterion_id, factor_id or concern it resolves."}},
            ["request", "audience", "reason", "linked_to"])},
        "screening_summary": {**_STR, "description": "Analytical; never states a decision."},
        "thesis_fit": {**_STR, "description": "At most 160 characters."},
    },
    ["company", "hard_criteria", "factors", "deal_breakers_triggered", "concerns", "bias_flags",
     "evidence_requests", "screening_summary", "thesis_fit"],
)
