"""Result emails (CLAUDE.md §16). No network: urlopen is stubbed everywhere."""

from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest

from icb.mail import content, mailer
from test_render import typical

SENTINEL = "re_sentinel_key_value"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", SENTINEL)
    monkeypatch.setenv("ICB_REPORT_EMAIL_TO", "Info@tencapital.group")
    monkeypatch.setenv("ICB_REPORT_EMAIL_FROM", "icb@tencapital.group")
    monkeypatch.setattr(mailer, "MIN_INTERVAL_S", 0)
    monkeypatch.setattr(mailer, "_last_send", 0.0)


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []

    def fake_urlopen(request, timeout=None):
        calls.append({"url": request.full_url, "headers": dict(request.headers),
                      "payload": json.loads(request.data.decode("utf-8"))})
        return FakeResponse(json.dumps({"id": "msg_123"}).encode("utf-8"))

    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_nothing_is_sent_until_both_settings_exist(monkeypatch, sent):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("ICB_REPORT_EMAIL_TO", raising=False)
    outcome = mailer.send(subject="s", html="<p>h</p>", text="t")
    assert outcome.status == "not_configured" and not sent

    monkeypatch.setenv("RESEND_API_KEY", SENTINEL)
    assert mailer.send(subject="s", html="<p>h</p>", text="t").status == "not_configured"
    assert not sent


def test_a_sent_email_uses_only_the_configured_recipient(configured, sent):
    outcome = mailer.send(subject="Subject", html="<p>Body</p>", text="Body",
                          attachments=[("scorecard.pdf", b"%PDF-1.7 data")], key="abc123")
    assert outcome.status == "sent" and outcome.message_id == "msg_123"
    payload = sent[0]["payload"]
    assert payload["to"] == ["Info@tencapital.group"] and payload["from"] == "icb@tencapital.group"
    assert payload["text"] == "Body" and payload["html"] == "<p>Body</p>"
    assert base64.b64decode(payload["attachments"][0]["content"]) == b"%PDF-1.7 data"
    assert sent[0]["headers"]["Idempotency-key"] == "abc123"


def test_oversize_attachments_drop_the_json_first(configured, sent):
    outcome = mailer.send(subject="s", html="<p>h</p>", text="t",
                          attachments=[("scorecard.pdf", b"x" * (10 * 1024 * 1024)),
                                       ("screening.json", b"y" * (15 * 1024 * 1024))])
    assert outcome.status == "sent" and outcome.dropped == ["screening.json"]
    payload = sent[0]["payload"]
    assert [a["filename"] for a in payload["attachments"]] == ["scorecard.pdf"]
    assert mailer.OMITTED_NOTE in payload["text"] and mailer.OMITTED_NOTE in payload["html"]


def test_an_email_too_large_even_alone_is_sent_without_attachments(configured, sent):
    big = b"x" * (25 * 1024 * 1024)  # 33 MB once base64-encoded
    outcome = mailer.send(subject="s", html="<p>h</p>", text="t",
                          attachments=[("scorecard.pdf", big), ("screening.json", big)])
    assert outcome.status == "sent"
    assert outcome.dropped == ["screening.json", "scorecard.pdf"]
    assert sent[0]["payload"]["attachments"] == []


@pytest.mark.parametrize(("error", "fragment"), [
    (urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"{}")), "rejected the API key"),
    (urllib.error.HTTPError("u", 500, "err", {}, io.BytesIO(b"{}")), "Resend returned 500"),
    (TimeoutError("slow"), "could not be reached"),
])
def test_failures_are_reported_not_raised(configured, monkeypatch, error, fragment):
    monkeypatch.setattr(mailer.time, "sleep", lambda _seconds: None)

    def failing(request, timeout=None):
        raise error

    monkeypatch.setattr(mailer.urllib.request, "urlopen", failing)
    outcome = mailer.send(subject="s", html="<p>h</p>", text="t")
    assert outcome.status == "failed" and fragment in outcome.reason
    assert SENTINEL not in json.dumps(outcome.as_dict())


def test_the_key_is_stable_for_the_same_artifact():
    first = mailer.idempotency_key("screening", "acme", "Deck-2026-09-16-abc")
    assert first == mailer.idempotency_key("screening", "acme", "Deck-2026-09-16-abc")
    assert first != mailer.idempotency_key("screening", "acme", "Deck-2026-09-17-abc")


def test_screening_email_reports_the_decision_and_escapes_model_text():
    screening = typical()
    screening.extraction.screening_summary = "<script>alert(1)</script> Ben & Co"
    message = content.screening_email(screening, "Northwind-2026-09-16-abcd1234")
    assert message.subject.startswith("[ICB] ADVANCE — Northwind Robotics · Acme Capital · 4.0/5")
    assert "<script>" not in message.html and "&lt;script&gt;" in message.html
    assert "Ben &amp; Co" in message.html
    assert "Rule 4:" in message.text and content.CONFIDENTIAL in message.text
    assert "Unit economics by cohort [Founder]" in message.text  # evidence requests carried over


def test_criteria_and_decision_emails_say_what_happened():
    summary = {"version": 2, "status": "draft", "hash": "abcd1234ef", "advance_threshold": 3.5,
               "max_unscored_weight_pct": 30, "deal_breakers": 1, "thesis_words": 180,
               "factors": [{"label": "Team", "weight": 20, "floor": 3}],
               "hard_criteria": [{"label": "Stage", "requirement": "Seed"}],
               "open_questions": ["What is the reserve policy?"], "not_applied": ["ownership target"]}
    draft = content.criteria_email(summary, "Acme Capital")
    assert draft.subject == "[ICB] Criteria Pack v2 draft — Acme Capital"
    assert "Approval blocked: 1 open question." in draft.text
    assert "Team — 20% (floor 3)" in draft.text

    approved = content.criteria_email({**summary, "status": "approved", "open_questions": []}, "Acme Capital")
    assert approved.subject == "[ICB] Criteria Pack v2 approved — Acme Capital"
    assert "Approval blocked" not in approved.text

    screening = typical()
    record = {"final_decision": "PASS", "override": True, "reviewer_initials": "HM",
              "exception_reason": "The contracts are with a related party."}
    decision = content.decision_email(record, screening)
    assert decision.subject == "[ICB] Decision recorded: PASS — Northwind Robotics (OVERRIDE)"
    assert "The contracts are with a related party." in decision.text


def test_a_failed_send_still_leaves_the_screening_saved(tmp_path, monkeypatch):
    """Emailing is a side errand: the artifacts and the log survive a Resend outage."""
    from icb import pipeline

    monkeypatch.setattr(pipeline.mailer, "send", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    outcome = pipeline._email(content.criteria_email({"version": 1, "status": "draft", "hash": "x",
                                                      "advance_threshold": 3.5, "max_unscored_weight_pct": 30,
                                                      "deal_breakers": 0, "thesis_words": 180, "factors": [],
                                                      "hard_criteria": [], "open_questions": [], "not_applied": []},
                                                     "Acme Capital"), key="k")
    assert outcome["status"] == "failed" and "boom" in outcome["reason"]
