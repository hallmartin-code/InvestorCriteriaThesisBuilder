"""The shared core: build criteria, screen a deck, record a decision (CLAUDE.md §15).

The CLI and the web app both call these functions, so the two front ends cannot drift apart.
Everything that touches the model or the disk lives here; `app.py` only turns these into HTTP.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from icb.criteria import build as criteria
from icb.criteria.models import CriteriaPack
from icb.mail import content as mail_content
from icb.mail import mailer
from icb.render import scorecard
from icb.screen import extract
from icb.screen.models import Screening
from icb.profile import store

DECISIONS = ("ADVANCE", "PASS", "HOLD")


def _email(message: mail_content.Message, key: str, attachments: list[tuple[str, bytes]] | None = None,
           send: bool = True) -> dict[str, Any]:
    """Emailing is a side errand: a failure is reported, never raised (§16)."""
    if not send:
        return {"status": "skipped", "recipient": "", "reason": None, "message_id": None, "dropped": []}
    try:
        return mailer.send(subject=message.subject, html=message.html, text=message.text,
                           attachments=attachments, key=key).as_dict()
    except Exception as exc:  # the artifacts are already saved
        return {"status": "failed", "recipient": "", "reason": str(exc), "message_id": None, "dropped": []}


@dataclass
class ScreenOutcome:
    screening: Screening
    name: str
    paths: dict[str, str]
    email: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        decision = self.screening.decision
        provenance = self.screening.provenance
        return {
            "name": self.name,
            "company": self.screening.company_name(),
            "investor_name": self.screening.investor_name,
            "source_filename": provenance.source_filename,
            "decision": decision.decision,
            "rule": decision.rule,
            "rule_sentence": decision.rule_sentence,
            "weighted_score": decision.weighted_score,
            "advance_threshold": decision.advance_threshold,
            "evidence_coverage": decision.evidence_coverage,
            "criteria_counts": decision.criteria_counts,
            "pack": provenance.criteria_pack,
            "cached": provenance.cached,
            "warnings": provenance.parse_warnings + provenance.warnings,
        }


def approved_pack(slug: str) -> CriteriaPack:
    pack = store.read_criteria(slug, status="approved")
    if pack is None:
        raise store.InvalidInput("This investor has no approved Criteria Pack yet. Build and approve one first.")
    pack.pop("content_hash", None)
    return CriteriaPack.model_validate(pack)


def require_complete_inputs(slug: str) -> None:
    """Screening stays closed until every §6 input is answered or marked No preference."""
    _, open_questions = store.profile_progress(store.investor_path(slug))
    if open_questions:
        raise store.InvalidInput(
            f"Screening is closed for this investor: {open_questions} "
            f"input{'s are' if open_questions != 1 else ' is'} still needed.")


def build_criteria(slug: str, on_progress: Callable[[], None] | None = None,
                   send_email: bool = True) -> dict[str, Any]:
    pack = criteria.build_draft(slug, on_progress=on_progress)
    summary = pack.summary()
    summary["email"] = _email(
        mail_content.criteria_email(summary, pack.display_name),
        key=mailer.idempotency_key("criteria-draft", slug, pack.version, summary["hash"]),
        attachments=[(f"criteria-v{pack.version}-draft.json",
                      pack.model_dump_json(indent=2).encode("utf-8"))],
        send=send_email)
    return summary


def approve_criteria(slug: str, version: int | None = None, send_email: bool = True) -> dict[str, Any]:
    pack = criteria.approve(slug, version=version)
    summary = pack.summary()
    summary["email"] = _email(
        mail_content.criteria_email(summary, pack.display_name),
        key=mailer.idempotency_key("criteria-approved", slug, pack.version, summary["hash"]),
        attachments=[(f"criteria-v{pack.version}-approved.json",
                      pack.model_dump_json(indent=2).encode("utf-8"))],
        send=send_email)
    return summary


def _check_size(slug: str) -> dict[str, int] | None:
    profile = store.read_profile(slug) or {}
    entry = (profile.get("fields") or {}).get("check_size") or {}
    return entry.get("value") if entry.get("status") == "provided" else None


def _artifact_name(screening: Screening) -> str:
    company = re.sub(r"[^A-Za-z0-9]+", "-", screening.company_name()).strip("-") or "company"
    stamp = date.today().isoformat()
    return f"{company}-{stamp}-{screening.provenance.criteria_pack.get('hash', '')[:8]}"


def screen(
    slug: str,
    filename: str,
    data: bytes,
    *,
    use_cache: bool = True,
    send_email: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> ScreenOutcome:
    """Ingest, screen against the approved pack, render the scorecard, and log the decision."""
    investor = store.read_investor(slug)
    require_complete_inputs(slug)
    pack = approved_pack(slug)

    if on_progress:
        on_progress("screening")
    screening = extract.screen_deck(
        slug=slug, investor_name=investor["name"], filename=filename, data=data, pack=pack,
        use_cache=use_cache, on_progress=None)

    if on_progress:
        on_progress("rendering")
    pdf = scorecard.render_pdf_bytes(screening, check_size=_check_size(slug))
    name = _artifact_name(screening)
    payload = screening.model_dump(mode="json")
    paths = store.write_scorecard(slug, name, pdf, payload)

    email = _email(
        mail_content.screening_email(screening, name),
        key=mailer.idempotency_key("screening", slug, name, screening.provenance.criteria_pack.get("hash", "")),
        attachments=[(f"{name}.pdf", pdf),
                     (f"{name}.json", screening.model_dump_json(indent=2).encode("utf-8"))],
        send=send_email)

    decision = screening.decision
    store.append_decision(slug, {
        "recorded_at": store.now_iso(),
        "type": "screening",
        "email": {"status": email["status"], "message_id": email.get("message_id")},
        "name": name,
        "company": screening.company_name(),
        "source_filename": screening.provenance.source_filename,
        "pack": screening.provenance.criteria_pack,
        "model": screening.provenance.model,
        "cached": screening.provenance.cached,
        "decision": decision.decision,
        "rule": decision.rule,
        "rule_sentence": decision.rule_sentence,
        "weighted_score": decision.weighted_score,
        "evidence_coverage": decision.evidence_coverage,
        "criteria_counts": decision.criteria_counts,
        "factors": [{"factor_id": f.factor_id, "score": f.score, "weight": f.weight} for f in screening.extraction.factors],
        "hard_criteria": [{"criterion_id": c.criterion_id, "result": c.result} for c in screening.extraction.hard_criteria],
        "deal_breakers": [d.deal_breaker_id for d in screening.extraction.deal_breakers_triggered],
        "bias_flags": [{"type": b.type, "signal": b.signal} for b in screening.extraction.bias_flags],
        "evidence_requests": [r.request for r in screening.extraction.evidence_requests],
    })
    return ScreenOutcome(screening=screening, name=name, paths=paths, email=email)


def record_decision(
    slug: str,
    name: str,
    final_decision: str,
    reviewer_initials: str,
    exception_reason: str | None = None,
    send_email: bool = True,
) -> dict[str, Any]:
    """A human decision. Departing from the computed one requires a written reason (§10)."""
    final = (final_decision or "").strip().upper()
    if final not in DECISIONS:
        raise store.InvalidInput("The final decision must be ADVANCE, PASS or HOLD.")
    initials = (reviewer_initials or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2,4}", initials):
        raise store.InvalidInput("Enter reviewer initials of 2-4 letters.")

    path = store.read_scorecard(slug, name, "json")
    screening = Screening.model_validate_json(path.read_text(encoding="utf-8"))
    computed = "HOLD" if screening.decision.decision.startswith("HOLD") else screening.decision.decision
    override = final != computed
    reason = (exception_reason or "").strip()
    if override and len(reason) < 20:
        raise store.InvalidInput("An override needs a reason that names the evidence behind it.")

    screening.review = {
        "final_decision": final, "override": override, "exception_reason": reason or None,
        "reviewer_initials": initials, "decided_at": store.now_iso(),
    }
    pdf = scorecard.render_pdf_bytes(screening, check_size=_check_size(slug))
    store.write_scorecard(slug, name, pdf, screening.model_dump(mode="json"))
    store.append_decision(slug, {
        "recorded_at": store.now_iso(), "type": "decision", "name": name,
        "company": screening.company_name(), "computed_decision": screening.decision.decision,
        "final_decision": final, "override": override, "exception_reason": reason or None,
        "reviewer_initials": initials, "pack": screening.provenance.criteria_pack,
    })
    record = {"name": name, "final_decision": final, "override": override, **screening.review}
    record["email"] = _email(
        mail_content.decision_email(record, screening),
        key=mailer.idempotency_key("decision", slug, name, final, screening.review["decided_at"]),
        attachments=[(f"{name}.pdf", pdf)],
        send=send_email)
    return record
