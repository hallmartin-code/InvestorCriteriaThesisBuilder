"""What each result email says (CLAUDE.md §16).

Every number comes from the same validated objects the PDF renders; there is no extra model
call to write an email. Model text is escaped, and each message carries a plain-text
alternative. No remote images and no tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

from icb.render import theme
from icb.screen.models import Screening

CONFIDENTIAL = ("Confidential — TEN Capital internal. AI-assisted analysis; verify against source "
                "documents.")


@dataclass(frozen=True)
class Message:
    subject: str
    html: str
    text: str


def _wrap(title: str, colour: str, blocks: list[str]) -> str:
    body = "".join(blocks)
    return (
        '<div style="font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#1F2733;max-width:640px">'
        f'<p style="font-size:11px;color:#5B6573;margin:0 0 12px">{escape(CONFIDENTIAL)}</p>'
        f'<h1 style="font-size:18px;margin:0 0 4px;color:{colour}">{escape(title)}</h1>'
        f"{body}</div>"
    )


def _list_html(items: list[str]) -> str:
    if not items:
        return ""
    entries = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f'<ul style="margin:4px 0 12px;padding-left:18px">{entries}</ul>'


def _section(heading: str, items: list[str]) -> str:
    if not items:
        return ""
    return f'<p style="margin:12px 0 0"><b>{escape(heading)}</b></p>{_list_html(items)}'


def _lines(heading: str, items: list[str]) -> str:
    if not items:
        return ""
    return f"\n{heading}\n" + "\n".join(f"  - {item}" for item in items) + "\n"


def screening_email(screening: Screening, artifact: str) -> Message:
    decision = screening.decision
    extraction = screening.extraction
    company = screening.company_name()
    pack = screening.provenance.criteria_pack or {}
    key = "HOLD" if decision.decision.startswith("HOLD") else decision.decision
    colour = theme.DECISION_COLORS[key]
    score = "—" if decision.weighted_score is None else f"{decision.weighted_score:.1f}"

    subject = f"[ICB] {decision.decision} — {company} · {screening.investor_name} · {score}/5"

    failed = [f"{c.label or c.criterion_id}: {c.result} — {c.deck_evidence}"
              for c in extraction.hard_criteria if c.result in {"NOT MET", "UNVERIFIED"}]
    breakers = [f"{d.walk_away_condition or d.deal_breaker_id} — {d.issue}" for d in extraction.deal_breakers_triggered]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    concerns = [f"[{c.severity}] {c.issue} (lowers {c.factor_label or c.factor_id})"
                for c in sorted(extraction.concerns, key=lambda item: order.get(item.severity, 3))[:3]]
    requests = [f"{r.request} [{r.audience}]" for r in extraction.evidence_requests[:5]]
    flags = [f"{f.type}: {f.signal}" for f in extraction.bias_flags]
    notes = list(screening.provenance.parse_warnings) + list(screening.provenance.warnings)
    if screening.provenance.cached:
        notes.append("Cached result: this deck had already been screened against this pack.")

    counts = decision.criteria_counts
    provenance_line = (f"Criteria Pack v{pack.get('version', '?')} #{str(pack.get('hash', ''))[:8]} · "
                       f"deck {screening.provenance.source_filename} · model {screening.provenance.model}")
    facts = (f"Weighted score {score} of 5 (advance at {decision.advance_threshold:.1f}) · "
             f"evidence coverage {decision.evidence_coverage}/100 · "
             f"hard criteria {counts.get('met', 0)} met / {counts.get('unverified', 0)} unverified / "
             f"{counts.get('not_met', 0)} not met")

    html = _wrap(f"{decision.decision} — {company}", colour, [
        f'<p style="margin:0 0 10px">{escape(decision.rule_sentence)}</p>',
        f'<p style="margin:0 0 10px;color:#5B6573">{escape(facts)}</p>',
        f'<p style="margin:0 0 10px">{escape(extraction.screening_summary)}</p>',
        f'<p style="margin:0 0 10px"><b>Thesis fit:</b> {escape(extraction.thesis_fit)}</p>',
        _section("Deal-breakers triggered", breakers),
        _section("Hard criteria not met or unverified", failed),
        _section("Top concerns", concerns),
        _section("Evidence to request", requests),
        _section("Bias flags", flags),
        _section("Notes", notes),
        f'<p style="margin:14px 0 0;font-size:11px;color:#5B6573">{escape(provenance_line)}</p>',
    ])

    text = "\n".join([
        CONFIDENTIAL, "", f"{decision.decision} — {company} ({screening.investor_name})",
        decision.rule_sentence, facts, "", extraction.screening_summary,
        f"Thesis fit: {extraction.thesis_fit}",
        _lines("Deal-breakers triggered:", breakers),
        _lines("Hard criteria not met or unverified:", failed),
        _lines("Top concerns:", concerns),
        _lines("Evidence to request:", requests),
        _lines("Bias flags:", flags),
        _lines("Notes:", notes),
        provenance_line,
        f"Artifacts: {artifact}.pdf / {artifact}.json",
    ])
    return Message(subject=subject, html=html, text=text)


def criteria_email(summary: dict[str, Any], investor_name: str) -> Message:
    approved = summary.get("status") == "approved"
    version = summary.get("version")
    subject = f"[ICB] Criteria Pack v{version} {'approved' if approved else 'draft'} — {investor_name}"
    factors = [f"{f['label']} — {f['weight']}%" + (f" (floor {f['floor']})" if f.get("floor") else "")
               for f in summary.get("factors", [])]
    criteria = [f"{c['label']}: {c['requirement']}" for c in summary.get("hard_criteria", [])]
    questions = list(summary.get("open_questions", []))
    facts = (f"Advance at {float(summary.get('advance_threshold', 0)):.1f} of 5 · at most "
             f"{summary.get('max_unscored_weight_pct', 0)}% of weight unscored · "
             f"{summary.get('deal_breakers', 0)} deal-breakers · thesis {summary.get('thesis_words', 0)} words")
    blocked = (f"Approval blocked: {len(questions)} open question{'s' if len(questions) != 1 else ''}."
               if questions else "")

    html = _wrap(f"Criteria Pack v{version} {'approved' if approved else 'draft'} — {investor_name}",
                 theme.DECISION_COLORS["ADVANCE" if approved else "HOLD"], [
        f'<p style="margin:0 0 10px;color:#5B6573">{escape(facts)}</p>',
        (f'<p style="margin:0 0 10px"><b>{escape(blocked)}</b></p>' if blocked else ""),
        _section("Open questions", questions),
        _section("Scoring factors", factors),
        _section("Hard criteria", criteria),
        _section("Not applied (no preference)", list(summary.get("not_applied", []))),
        f'<p style="margin:14px 0 0;font-size:11px;color:#5B6573">Hash #{escape(str(summary.get("hash", ""))[:8])}</p>',
    ])
    text = "\n".join([
        CONFIDENTIAL, "", f"Criteria Pack v{version} {'approved' if approved else 'draft'} — {investor_name}",
        facts, blocked,
        _lines("Open questions:", questions),
        _lines("Scoring factors:", factors),
        _lines("Hard criteria:", criteria),
        _lines("Not applied (no preference):", list(summary.get("not_applied", []))),
        f"Hash #{str(summary.get('hash', ''))[:8]}",
    ])
    return Message(subject=subject, html=html, text=text)


def decision_email(record: dict[str, Any], screening: Screening) -> Message:
    company = screening.company_name()
    override = bool(record.get("override"))
    final = record.get("final_decision", "")
    subject = f"[ICB] Decision recorded: {final} — {company}" + (" (OVERRIDE)" if override else "")
    computed = screening.decision.decision
    colour = theme.DECISION_COLORS["HOLD" if final == "HOLD" else final] if final in theme.DECISION_COLORS \
        else theme.DECISION_COLORS["HOLD"]
    facts = f"Computed: {computed} · recorded: {final} · reviewer {record.get('reviewer_initials', '')}"
    reason = record.get("exception_reason") or ""

    html = _wrap(f"Decision recorded: {final} — {company}", colour, [
        f'<p style="margin:0 0 10px;color:#5B6573">{escape(facts)}</p>',
        (f'<p style="margin:0 0 10px"><b>Override reason:</b> {escape(reason)}</p>' if override else
         '<p style="margin:0 0 10px">The reviewer agreed with the computed decision.</p>'),
        f'<p style="margin:0 0 10px">{escape(screening.decision.rule_sentence)}</p>',
    ])
    text = "\n".join([CONFIDENTIAL, "", f"Decision recorded: {final} — {company}", facts,
                      (f"Override reason: {reason}" if override else
                       "The reviewer agreed with the computed decision."),
                      screening.decision.rule_sentence])
    return Message(subject=subject, html=html, text=text)
