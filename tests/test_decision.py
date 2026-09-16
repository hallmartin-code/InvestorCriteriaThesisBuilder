"""The decision rules (templates/one_pager.md §6). Order matters; the first match wins."""

from __future__ import annotations

import pytest

from icb.screen.decision import align, decide
from icb.screen.models import (
    ConcernResult,
    FactorResult,
    HardCriterionResult,
    ScreeningExtraction,
    TriggeredDealBreaker,
)
from test_criteria import make_pack

FACTORS = ("factor_1", "factor_2", "factor_3", "factor_4", "factor_5", "factor_6")  # weights 20 20 15 15 15 15


def extraction(scores, criteria=("MET",), breakers=(), concerns=()):
    return ScreeningExtraction(
        factors=[FactorResult(factor_id=fid, score=score, evidence_standard_met=score is not None)
                 for fid, score in zip(FACTORS, scores, strict=True)],
        hard_criteria=[HardCriterionResult(criterion_id="stage", result=result) for result in criteria],
        deal_breakers_triggered=[TriggeredDealBreaker(deal_breaker_id=b, issue="Observed in the deck") for b in breakers],
        concerns=[ConcernResult(factor_id=f, issue="Concern") for f in concerns],
    )


def run(extracted, pack=None):
    pack = pack or make_pack()
    aligned, warnings = align(extracted, pack)
    return decide(aligned, pack), warnings


@pytest.mark.parametrize(("scores", "criteria", "breakers", "expected", "rule"), [
    ((4, 4, 4, 4, 4, 4), ("MET",), (), "ADVANCE", 4),
    ((3, 4, 4, 4, 3, 3), ("MET",), (), "ADVANCE", 4),           # exactly 3.5 — the threshold is inclusive
    ((3, 3, 3, 3, 3, 3), ("MET",), (), "PASS", 5),              # 3.0, below threshold
    ((4, 4, 4, None, 4, 4), ("MET",), (), "ADVANCE", 4),        # 15% unscored, inside the 30% limit
    ((4, None, None, 4, 4, 4), ("MET",), (), "HOLD — REQUEST EVIDENCE", 3),   # 35% unscored
    ((None, None, None, None, None, None), ("MET",), (), "HOLD — REQUEST EVIDENCE", 3),
    ((5, 5, 5, 5, 5, 5), ("UNVERIFIED",), (), "HOLD — REQUEST EVIDENCE", 3),
    ((None, None, 5, 5, 5, 5), ("NOT MET",), (), "PASS", 2),                 # rule 2 beats rule 3
    ((5, 5, 5, 5, 5, 5), ("NOT MET",), ("no_ip",), "PASS", 1),               # rule 1 beats rule 2
])
def test_rules_in_order(scores, criteria, breakers, expected, rule):
    decision, _ = run(extraction(scores, criteria, breakers))
    assert (decision.decision, decision.rule) == (expected, rule)
    assert decision.rule_sentence.startswith(f"Rule {rule}:")


def test_floor_breach_beats_a_high_average():
    pack = make_pack()
    pack.draft.factors[0].floor = 3
    decision, _ = run(extraction((2, 5, 5, 5, 5, 5)), pack)
    assert decision.decision == "PASS" and decision.rule == 5
    assert decision.floor_breaches == ["Factor 1"]
    assert decision.weighted_score == 4.4


def test_coverage_and_counts_are_reported():
    decision, _ = run(extraction((4, 4, 4, None, 4, 4), ("MET",)))
    assert decision.unscored_weight_pct == 15 and decision.evidence_coverage == 85
    assert decision.weighted_score == 4.0  # the unscored factor is excluded, not counted as zero
    assert decision.criteria_counts == {"met": 1, "not_met": 0, "unverified": 0}


def test_nothing_scored_but_unscored_allowed_is_a_pass_not_a_hold():
    pack = make_pack()
    pack.draft.max_unscored_weight_pct = 100
    decision, _ = run(extraction((None,) * 6), pack)
    assert decision.decision == "PASS" and decision.rule == 5
    assert decision.weighted_score is None
    assert "no factor could be scored" in decision.rule_sentence


def test_align_fills_pack_labels_and_missing_results():
    pack = make_pack()
    sparse = ScreeningExtraction(
        factors=[FactorResult(factor_id="factor_1", score=5, evidence_standard_met=True),
                 FactorResult(factor_id="ghost", score=5, evidence_standard_met=True)],
        hard_criteria=[],
        deal_breakers_triggered=[TriggeredDealBreaker(deal_breaker_id="no_ip")],
        concerns=[ConcernResult(factor_id="factor_1", issue="Single founder")],
    )
    aligned, warnings = align(sparse, pack)

    assert [f.factor_id for f in aligned.factors] == list(FACTORS)  # every pack factor is present
    assert aligned.factors[0].label == "Factor 1" and aligned.factors[0].weight == 20
    assert aligned.factors[1].score is None and aligned.factors[1].gap
    assert [c.criterion_id for c in aligned.hard_criteria] == ["stage"]
    assert aligned.hard_criteria[0].result == "UNVERIFIED"
    assert aligned.deal_breakers_triggered[0].walk_away_condition == "No IP protection"
    assert aligned.concerns[0].factor_label == "Factor 1"
    assert any("ghost" in warning for warning in warnings)


def test_a_score_without_the_evidence_standard_is_dropped():
    pack = make_pack()
    claimed = ScreeningExtraction(factors=[
        FactorResult(factor_id="factor_1", score=5, evidence_standard_met=False),
    ])
    aligned, _ = align(claimed, pack)
    assert aligned.factors[0].score is None and aligned.factors[0].gap
