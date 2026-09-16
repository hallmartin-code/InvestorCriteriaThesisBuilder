"""Criteria Pack: structural rules, the approval gate, hashing, and immutability (CLAUDE.md §7)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from icb.criteria import build as criteria_build
from icb.criteria.models import CriteriaDraft, CriteriaPack
from icb.llm.client import ModelResult
from icb.profile import store, validate
from icb.profile.models import ProfileDocument
from test_profile_api import COMPLETE_FIELDS

THESIS = " ".join(["word"] * 180)
WEIGHTS = (20, 20, 15, 15, 15, 15)


def factor(index: int, weight: int, **overrides):
    return {
        "factor_id": f"factor_{index}", "label": f"Factor {index}", "short_label": f"F{index}",
        "weight": weight, "weight_rationale": "Tied to the stated return objective.",
        "rubric": [{"score": score, "evidence": f"Observable evidence at level {score}."} for score in range(1, 6)],
        "floor": None, "evidence_required": ["deck_statement"], "grounded_in": ["fields.return_objective"],
        "needs_input": None, **overrides,
    }


def draft_data(**overrides):
    data = {
        "thesis": {"text": THESIS, "grounded_in": ["fields.thesis_notes"], "needs_input": None},
        "hard_criteria": [{"criterion_id": "stage", "label": "Stage", "requirement": "Seed",
                           "test": "The deck states the round stage.", "evidence_required": ["deck_statement"],
                           "grounded_in": ["fields.stages"], "needs_input": None}],
        "factors": [factor(i, w) for i, w in enumerate(WEIGHTS, start=1)],
        "deal_breakers": [{"deal_breaker_id": "no_ip", "walk_away_condition": "No IP protection",
                           "trigger": "The deck states no patents are filed.",
                           "grounded_in": ["fields.instant_no_filters"], "needs_input": None}],
        "concerns": [{"concern_id": "thin_team", "factor_id": "factor_1", "condition": "Single founder",
                      "consequence": "Lowers the team factor.", "grounded_in": ["fields.prior_investments"],
                      "needs_input": None}],
        "consistency_controls": ["Record a rationale for every decision."],
        "bias_checks": ["Named co-investors are not evidence of quality."],
        "exception_procedure": "An override needs written evidence.",
        "review_cadence": {"triggers": ["Every 20 screened deals"], "min_sample_size": 20,
                           "outcome_data": ["Exits"], "versioning": "Changes create a new version.",
                           "grounded_in": ["fields.time_horizon_years"], "needs_input": None},
        "advance_threshold": 3.5, "max_unscored_weight_pct": 30, "open_questions": [], "not_applied": [],
    }
    data.update(overrides)
    return data


def make_pack(**overrides) -> CriteriaPack:
    return CriteriaPack(version=1, slug="acme-capital", display_name="Acme Capital",
                        created_at="2026-09-16T00:00:00+00:00", model="claude-opus-5",
                        draft=CriteriaDraft.model_validate(draft_data(**overrides)))


@pytest.fixture
def investor(tmp_path, monkeypatch):
    monkeypatch.setenv("ICB_DATA_DIR", str(tmp_path / "investors"))
    store.create_investor("acme-capital", "Acme Capital")
    return "acme-capital"


def save_profile(slug, fields):
    document = ProfileDocument(slug=slug, display_name="Acme Capital", fields=fields)
    result = validate.normalize(document)
    store.write_profile(slug, {"schema_version": 1, "slug": slug, "display_name": "Acme Capital",
                               "updated_at": store.now_iso(), "fields": result["fields"]})


@pytest.mark.parametrize(("overrides", "fragment"), [
    ({"factors": [factor(i, w) for i, w in enumerate((25, 25, 25, 25), start=1)]}, "6-10 scoring factors"),
    ({"factors": [factor(i, 10) for i in range(1, 7)]}, "sum to 100"),
    ({"thesis": {"text": "too short", "grounded_in": [], "needs_input": None}}, "150-250 words"),
])
def test_structural_rules_are_enforced(overrides, fragment):
    with pytest.raises(ValidationError, match=fragment):
        CriteriaDraft.model_validate(draft_data(**overrides))


def test_rubric_needs_one_level_per_score():
    broken = factor(1, 20)
    broken["rubric"] = broken["rubric"][:4]
    with pytest.raises(ValidationError, match="rubric level for each score"):
        CriteriaDraft.model_validate(draft_data(factors=[broken] + [factor(i, w) for i, w in enumerate(WEIGHTS[1:], start=2)]))


def test_concerns_must_name_a_known_factor():
    data = draft_data()
    data["concerns"][0]["factor_id"] = "nope"
    with pytest.raises(ValidationError, match="unknown factors"):
        CriteriaDraft.model_validate(data)


def test_blocking_questions_come_from_needs_input_and_open_questions():
    pack = make_pack(open_questions=["What is the reserve policy?"])
    pack.draft.factors[0].needs_input = "Which team evidence counts?"
    blocking = pack.draft.blocking_questions()
    assert blocking[0] == "What is the reserve policy?"
    assert any("Which team evidence counts?" in question for question in blocking)


def test_hash_ignores_key_order_and_timestamps():
    pack = make_pack()
    reordered = json.loads(json.dumps(pack.model_dump(mode="json"), sort_keys=True))
    reordered["created_at"] = "2030-01-01T00:00:00+00:00"
    assert CriteriaPack.model_validate(reordered).content_hash() == pack.content_hash()
    changed = pack.model_copy(deep=True)
    changed.draft.advance_threshold = 4.0
    assert changed.content_hash() != pack.content_hash()


def test_build_refuses_while_inputs_are_incomplete(investor):
    save_profile(investor, {"investor_type": {"status": "provided", "value": "fund"}})
    with pytest.raises(store.InvalidInput, match="still needed"):
        criteria_build.build_draft(investor)


def test_build_stores_a_draft_and_approval_freezes_it(investor, monkeypatch):
    save_profile(investor, COMPLETE_FIELDS)
    calls = {}

    def fake_call(**kwargs):
        calls.update(kwargs)
        return ModelResult(data=draft_data(), model="claude-opus-5", input_tokens=10, output_tokens=20, corrected=False)

    monkeypatch.setattr(criteria_build.llm, "call_json", fake_call)
    pack = criteria_build.build_draft(investor)

    assert pack.version == 1 and pack.status == "draft"
    assert "Acme Capital" in calls["content"][0]["text"]
    assert store.approved_pack_summary(store.investor_path(investor)) is None

    approved = criteria_build.approve(investor)
    assert approved.status == "approved" and approved.approved_at
    summary = store.approved_pack_summary(store.investor_path(investor))
    assert summary == {"version": 1, "hash": approved.content_hash(), "approved_at": approved.approved_at}
    with pytest.raises(store.InvalidInput, match="already approved"):
        criteria_build.approve(investor)


def test_approval_refuses_while_questions_remain(investor, monkeypatch):
    save_profile(investor, COMPLETE_FIELDS)
    monkeypatch.setattr(criteria_build.llm, "call_json", lambda **kwargs: ModelResult(
        data=draft_data(open_questions=["Which sectors are out of scope?"]),
        model="claude-opus-5", input_tokens=1, output_tokens=1, corrected=False))
    criteria_build.build_draft(investor)
    with pytest.raises(store.InvalidInput, match="must be answered"):
        criteria_build.approve(investor)
