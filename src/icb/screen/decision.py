"""Apply a Criteria Pack to a screening extraction and decide (templates/one_pager.md §6).

Pure functions, no I/O and no model call. `align` copies the pack's labels, weights, floors and
walk-away conditions onto the model's results and fills in anything it left out; `decide` then
applies the five rules in order. The model never decides.
"""

from __future__ import annotations

from icb.criteria.models import CriteriaPack
from icb.screen.models import (
    ConcernResult,
    Decision,
    FactorResult,
    HardCriterionResult,
    ScreeningExtraction,
)

RULE_LABELS = {
    1: "Deal-breaker triggered",
    2: "Hard criterion not met",
    3: "Evidence insufficient",
    4: "Meets threshold and floors",
    5: "Below threshold or floor",
}


def align(extraction: ScreeningExtraction, pack: CriteriaPack) -> tuple[ScreeningExtraction, list[str]]:
    """Return a copy carrying the pack's own labels and weights. Results the pack doesn't define are dropped."""
    warnings: list[str] = []
    draft = pack.draft
    aligned = extraction.model_copy(deep=True)

    criteria = {c.criterion_id: c for c in draft.hard_criteria}
    results = {r.criterion_id: r for r in aligned.hard_criteria if r.criterion_id in criteria}
    dropped = {r.criterion_id for r in aligned.hard_criteria} - set(results)
    aligned.hard_criteria = []
    for criterion_id, criterion in criteria.items():
        result = results.get(criterion_id) or HardCriterionResult(criterion_id=criterion_id)
        result.label, result.requirement = criterion.label, criterion.requirement
        if criterion_id not in results:
            result.deck_evidence = result.deck_evidence or "The deck does not state this."
            warnings.append(f"The model returned no result for hard criterion '{criterion.label}'.")
        aligned.hard_criteria.append(result)

    factors = {f.factor_id: f for f in draft.factors}
    scored = {r.factor_id: r for r in aligned.factors if r.factor_id in factors}
    dropped |= {r.factor_id for r in aligned.factors} - set(scored)
    aligned.factors = []
    for factor_id, factor in factors.items():
        result = scored.get(factor_id) or FactorResult(factor_id=factor_id)
        result.label, result.short_label = factor.label, factor.short_label
        result.weight, result.floor = factor.weight, factor.floor
        if factor_id not in scored:
            result.gap = result.gap or "The model returned no score for this factor."
            warnings.append(f"The model returned no score for factor '{factor.label}'.")
        if not result.evidence_standard_met:
            result.score = None  # absence of evidence is never a low score
        if result.score is None and not result.gap:
            result.gap = "The deck does not meet the evidence standard for this factor."
        aligned.factors.append(result)

    breakers = {d.deal_breaker_id: d for d in draft.deal_breakers}
    kept = [t for t in aligned.deal_breakers_triggered if t.deal_breaker_id in breakers]
    dropped |= {t.deal_breaker_id for t in aligned.deal_breakers_triggered} - set(breakers)
    for triggered in kept:
        triggered.walk_away_condition = breakers[triggered.deal_breaker_id].walk_away_condition
    aligned.deal_breakers_triggered = kept

    labels = {f.factor_id: f.label for f in draft.factors}
    aligned.concerns = [_labelled(concern, labels) for concern in aligned.concerns]
    if dropped:
        warnings.append("The model referred to ids that are not in the pack: " + ", ".join(sorted(dropped)) + ".")
    return aligned, warnings


def _labelled(concern: ConcernResult, labels: dict[str, str]) -> ConcernResult:
    concern.factor_label = labels.get(concern.factor_id, "")
    return concern


def decide(extraction: ScreeningExtraction, pack: CriteriaPack) -> Decision:
    """The five rules, in order; the first match wins."""
    draft = pack.draft
    scored = [f for f in extraction.factors if f.score is not None]
    scored_weight = sum(f.weight for f in scored)
    unscored_weight = sum(f.weight for f in extraction.factors if f.score is None)
    weighted = round(sum(f.score * f.weight for f in scored) / scored_weight, 2) if scored_weight else None
    floor_breaches = [f.label or f.factor_id for f in scored if f.floor is not None and f.score < f.floor]

    counts = {"met": 0, "not_met": 0, "unverified": 0}
    for result in extraction.hard_criteria:
        counts[{"MET": "met", "NOT MET": "not_met", "UNVERIFIED": "unverified"}[result.result]] += 1

    threshold = draft.advance_threshold
    max_unscored = draft.max_unscored_weight_pct
    common = {
        "weighted_score": weighted,
        "advance_threshold": threshold,
        "evidence_coverage": 100 - unscored_weight,
        "unscored_weight_pct": unscored_weight,
        "max_unscored_weight_pct": max_unscored,
        "floor_breaches": floor_breaches,
        "criteria_counts": counts,
    }

    triggered = extraction.deal_breakers_triggered
    if triggered:
        first = triggered[0].walk_away_condition or triggered[0].issue
        return Decision(decision="PASS", rule=1, rule_label=RULE_LABELS[1], **common,
                        rule_sentence=f"Rule 1: {len(triggered)} deal-breaker"
                                      f"{'s' if len(triggered) != 1 else ''} triggered, starting with {first}.")
    if counts["not_met"]:
        failed = next(r.label or r.criterion_id for r in extraction.hard_criteria if r.result == "NOT MET")
        return Decision(decision="PASS", rule=2, rule_label=RULE_LABELS[2], **common,
                        rule_sentence=f"Rule 2: {counts['not_met']} hard criteri"
                                      f"{'a are' if counts['not_met'] != 1 else 'on is'} not met, starting with {failed}.")
    if counts["unverified"] or unscored_weight > max_unscored:
        reasons = []
        if counts["unverified"]:
            reasons.append(f"{counts['unverified']} hard criteri"
                           f"{'a are' if counts['unverified'] != 1 else 'on is'} unverified")
        if unscored_weight > max_unscored:
            reasons.append(f"{unscored_weight}% of factor weight is unscored, above the {max_unscored}% limit")
        return Decision(decision="HOLD — REQUEST EVIDENCE", rule=3, rule_label=RULE_LABELS[3], **common,
                        rule_sentence="Rule 3: " + " and ".join(reasons) + ".")
    if weighted is not None and weighted >= threshold and not floor_breaches:
        return Decision(decision="ADVANCE", rule=4, rule_label=RULE_LABELS[4], **common,
                        rule_sentence=f"Rule 4: weighted score {weighted:.1f} meets the "
                                      f"{threshold:.1f} threshold with no floor breaches.")
    if weighted is None:
        detail = "no factor could be scored"
    elif floor_breaches:
        detail = f"weighted score {weighted:.1f} with a floor breach on {', '.join(floor_breaches)}"
    else:
        detail = f"weighted score {weighted:.1f} is below the {threshold:.1f} threshold"
    return Decision(decision="PASS", rule=5, rule_label=RULE_LABELS[5], **common,
                    rule_sentence=f"Rule 5: {detail}.")
