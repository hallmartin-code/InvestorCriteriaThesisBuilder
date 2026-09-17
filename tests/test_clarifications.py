"""Answering the Criteria Pack's questions (CLAUDE.md §7, §15 Screens 3).

The wordings here are from a real build for a CPG angel, which asked the same question twice —
once on the element it blocked and once at the top.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as web
from icb.criteria.prompts import build_content, render_clarifications
from icb.profile import store
from test_criteria import make_pack
from test_profile_api import COMPLETE_FIELDS

SLUG = "acme-capital"
PROFILE = f"/api/investors/{SLUG}/profile"
CLARIFY = f"/api/investors/{SLUG}/clarifications"
OWNERSHIP = ("Which constraint is fixed: the 5% ownership target, the $100k-$500k check band, or the "
             "$500k-$1M round band? At those round sizes they cannot all hold.")
ANSWER = "The check band is fixed; ownership is a target, not a floor."


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ICB_DATA_DIR", str(tmp_path / "investors"))
    with TestClient(web.app) as c:
        c.post("/api/investors", json={"slug": SLUG, "name": "Acme Capital"})
        c.put(PROFILE, json={"schema_version": 1, "slug": SLUG, "display_name": "Acme Capital",
                             "fields": COMPLETE_FIELDS})
        yield c


def test_answers_are_saved_to_the_investor_and_come_back_with_the_profile(client):
    response = client.post(CLARIFY, json={"answers": [{"question": OWNERSHIP, "answer": ANSWER}]})
    assert response.status_code == 200
    assert response.json()["answered"] == 1

    profile = client.get(PROFILE).json()
    assert profile["clarifications"] == [{"question": OWNERSHIP, "answer": ANSWER,
                                          "answered_at": profile["clarifications"][0]["answered_at"],
                                          "source": "intake"}]


def test_re_answering_replaces_and_clearing_removes(client):
    client.post(CLARIFY, json={"answers": [{"question": OWNERSHIP, "answer": ANSWER}]})
    client.post(CLARIFY, json={"answers": [{"question": OWNERSHIP, "answer": "Ownership is fixed at 5%."}]})
    answers = client.get(PROFILE).json()["clarifications"]
    assert len(answers) == 1 and answers[0]["answer"] == "Ownership is fixed at 5%."

    body = client.post(CLARIFY, json={"answers": [{"question": OWNERSHIP, "answer": "  "}]}).json()
    assert body["clarifications"] == [] and body["answered"] == 0


def test_saving_answers_does_not_disturb_the_inputs(client):
    client.post(CLARIFY, json={"answers": [{"question": OWNERSHIP, "answer": ANSWER}]})
    profile = client.get(PROFILE).json()
    assert profile["fields"]["investor_type"]["status"] == "provided"
    assert profile["fields"]["check_size"]["value"] == {"min_usd": 100_000, "max_usd": 250_000}

    # and a later save of the form keeps the answers
    client.put(PROFILE, json={"schema_version": 1, "slug": SLUG, "display_name": "Acme Capital",
                              "fields": COMPLETE_FIELDS})
    assert len(client.get(PROFILE).json()["clarifications"]) == 1


@pytest.mark.parametrize(("payload", "fragment"), [
    ({"answers": "nope"}, "Send the answers"),
    ({}, "Send the answers"),
])
def test_bad_payloads_are_refused(client, payload, fragment):
    response = client.post(CLARIFY, json=payload)
    assert response.status_code == 422 and fragment in response.json()["error"]


def test_unknown_investor_is_not_found(client):
    assert client.post("/api/investors/nobody/clarifications", json={"answers": []}).status_code == 404


def test_answers_reach_the_builder_prompt(client):
    client.post(CLARIFY, json={"answers": [{"question": OWNERSHIP, "answer": ANSWER}]})
    profile = store.read_profile(SLUG)

    rendered = render_clarifications(profile)
    assert OWNERSHIP in rendered and ANSWER in rendered

    blocks = build_content(profile, notes=[])
    joined = "\n".join(block["text"] for block in blocks)
    assert "ANSWERS TO EARLIER QUESTIONS" in joined and ANSWER in joined
    assert "ask it once" in joined  # the task line no longer invites duplicates


REAL_DRAFT_QUESTIONS = [
    "Which single return target governs: capital preservation plus 10% growth, 5.0x multiple, 20% IRR, or 50% growth over 5 years? Each implies different entry-price discipline.",
    OWNERSHIP,
    "Does any booked third-party revenue in the last 90 days clear the pre-revenue filter, or is there a minimum monthly revenue or repeat-order count?",
    "Do you want a hard gross-margin floor for CPG (for example 40% at current volumes), or should margin remain scored only?",
    "Are post-money SAFEs acceptable as equivalent to convertible notes, and will you accept an uncapped note?",
    "With $2M available and a matching follow-on policy, cap the portfolio at 4-6 positions with 50% reserved, or fund follow-ons from future capital?",
    "Beyond the Dude Wipes exit, what specific resources do you bring to a CPG brand: named buyer relationships, co-packer access, hours per month?",
    "Do you require pro-rata rights, information rights, or a board observer seat as a condition of investing, or are these scored preferences only?",
    "Within food and beverage, which sub-categories are excluded (alcohol, supplements, regulated CBD, cold-chain perishables)?",
    "thesis: Beyond the Dude Wipes exit, what repeatable resources do you bring to a CPG brand (retail-buyer relationships, co-packer access, hours per month)?",
    "hard criterion 'Post-revenue only': Does any booked third-party revenue in the last 90 days clear the pre-revenue filter, or do you require a minimum monthly revenue figure?",
    "hard criterion 'Convertible note or priced equity': Do you accept post-money SAFEs as equivalent to convertible notes, and will you accept a note without a valuation cap?",
    "factor 'Unit economics and gross margin': Do you want a hard gross-margin floor (for example 40% at current volumes), or should margin remain a scored factor only?",
    "factor 'Entry price and ownership achieved': Which constraint is fixed: the 5% ownership target, the $100k-$500k check band, or the $500k-$1M round band? At those round sizes they conflict.",
    "factor 'Milestone definability for follow-on': With $2M available and a matching follow-on policy, should the portfolio be capped at 4-6 positions with 50% reserved, or funded from future capital?",
    "factor 'Exit path and modelled return': Which single target should deals be underwritten to: 10% growth with preservation, 5.0x multiple, 20% IRR, or 50% over 5 years?",
    "deal-breaker 'The only instrument offered is neither a convertible note nor priced equity.': Is a post-money SAFE an acceptable equivalent to a convertible note, or a walk-away?",
]


def test_a_real_draft_of_seventeen_questions_asks_nine():
    """Every one of the eight repeats collapses, and all nine distinct questions survive."""
    from icb.criteria.models import _deduplicate

    kept = _deduplicate(REAL_DRAFT_QUESTIONS)
    assert len(kept) == 9
    assert kept == REAL_DRAFT_QUESTIONS[:9]  # the plain wordings win over the prefixed repeats


def test_the_same_question_asked_twice_is_listed_once():
    pack = make_pack(open_questions=[OWNERSHIP])
    pack.draft.factors[0].needs_input = ("Which constraint is fixed: the 5% ownership target, the "
                                         "$100k-$500k check band, or the $500k-$1M round band?")
    pack.draft.factors[1].needs_input = "Which single return target governs: a 5.0x multiple or a 20% IRR?"

    questions = pack.draft.blocking_questions()
    assert len(questions) == 2  # the ownership pair collapses; the return question stays
    assert questions[0] == OWNERSHIP
    assert "return target" in questions[1]
