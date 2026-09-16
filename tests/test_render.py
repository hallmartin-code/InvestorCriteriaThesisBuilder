"""The scorecard PDF: one page always, house footer, nulls, and the never-dropped blocks."""

from __future__ import annotations

import io

from pypdf import PdfReader

from icb.render import scorecard, theme
from icb.screen.decision import align, decide
from icb.screen.models import (
    BiasFlag,
    ConcernResult,
    Evidence,
    EvidenceRequest,
    FactorResult,
    HardCriterionResult,
    Provenance,
    Screening,
    ScreeningExtraction,
    SnapshotField,
    TriggeredDealBreaker,
)
from test_criteria import factor as pack_factor, make_pack

LONG = "word " * 400  # longer than any density limit


def text_of(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def pages(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def screening_for(pack, extraction: ScreeningExtraction) -> Screening:
    aligned, _ = align(extraction, pack)
    return Screening(
        slug="acme-capital", investor_name="Acme Capital", extraction=aligned,
        decision=decide(aligned, pack),
        provenance=Provenance(source_filename="deck.pdf", slide_count=18, model="claude-opus-5",
                              generated_at="2026-09-16T09:30:00+00:00",
                              criteria_pack={"version": 1, "hash": pack.content_hash(),
                                             "investor_name": "Acme Capital"}),
    )


def typical() -> Screening:
    pack = make_pack()
    extraction = ScreeningExtraction(
        company={"name": SnapshotField(value="Northwind Robotics", classification="FACT", confidence=0.98, slides=[1]),
                 "sector": SnapshotField(value="Industrial automation", classification="FACT", slides=[2]),
                 "stage": SnapshotField(value="Seed", classification="INFERENCE", slides=[12]),
                 "raise_amount": SnapshotField(value="$3.0M", classification="FACT", slides=[12], amount_usd=3_000_000),
                 "valuation": SnapshotField(value="$12M", classification="FACT", slides=[12], amount_usd=12_000_000),
                 "valuation_basis": "pre-money"},
        factors=[FactorResult(factor_id=f"factor_{i}", score=4 if i != 3 else None, evidence_standard_met=i != 3,
                              evidence_summary="Two named customers with signed contracts.",
                              evidence=[Evidence(quote="two signed enterprise contracts", slide=7)],
                              gap="" if i != 3 else "No unit economics are shown.") for i in range(1, 7)],
        hard_criteria=[HardCriterionResult(criterion_id="stage", result="MET", deck_evidence="Seed round stated",
                                           classification="FACT", slides=[12], excerpt="Raising a $3M seed")],
        concerns=[ConcernResult(factor_id="factor_1", severity="HIGH", issue="Single technical founder",
                                consequence="Lowers team score.", resolution="Meet the wider team.",
                                slides=[4], excerpt="Founder and CTO")],
        bias_flags=[BiasFlag(type="Social proof", signal="Logos of well-known investors", slides=[16])],
        evidence_requests=[EvidenceRequest(request="Unit economics by cohort", audience="Founder", priority=1)],
        screening_summary="Traction is evidenced; unit economics are not.",
        thesis_fit="Matches the stated industrial focus.",
    )
    return screening_for(pack, extraction)


def overstuffed() -> Screening:
    pack = make_pack(factors=[pack_factor(i, 10) for i in range(1, 11)])  # 10 factors, weights sum to 100
    extraction = ScreeningExtraction(
        company={name: SnapshotField(value="x" * 200, classification="INFERENCE", slides=[1, 2, 3], excerpt=LONG[:400])
                 for name in ("name", "sector", "subsector", "stage", "geography", "revenue", "key_traction",
                              "raise_amount", "instrument", "valuation", "amount_committed", "lead_investor")},
        factors=[FactorResult(factor_id=f"factor_{i}", score=3, evidence_standard_met=True,
                              evidence_summary=LONG[:2000], gap=LONG[:2000],
                              evidence=[Evidence(quote=LONG[:400], slide=2)]) for i in range(1, 11)],
        hard_criteria=[HardCriterionResult(criterion_id="stage", result="UNVERIFIED", deck_evidence=LONG[:2000],
                                           excerpt=LONG[:400], slides=[1, 2, 3])],
        deal_breakers_triggered=[TriggeredDealBreaker(deal_breaker_id="no_ip", issue=LONG[:200],
                                                      excerpt=LONG[:400], resolution=LONG[:2000], slides=[3])],
        concerns=[ConcernResult(factor_id=f"factor_{i % 10 + 1}", severity="HIGH", issue=LONG[:200],
                                consequence=LONG[:2000], resolution=LONG[:2000], excerpt=LONG[:400], slides=[4])
                  for i in range(30)],
        bias_flags=[BiasFlag(type="Momentum", signal=LONG[:200], slides=[5]) for _ in range(20)],
        evidence_requests=[EvidenceRequest(request=LONG[:200], audience="Legal counsel", reason=LONG[:2000],
                                           priority=i + 1) for i in range(20)],
        screening_summary=LONG[:2000], thesis_fit="x" * 160,
    )
    return screening_for(pack, extraction)


def test_a_typical_scorecard_is_one_page_with_the_house_footer():
    screening = typical()
    data = scorecard.render_pdf_bytes(screening, check_size={"min_usd": 100_000, "max_usd": 250_000})
    assert pages(data) == 1
    printed = text_of(data)
    assert "Investor Screening Scorecard" in printed
    assert "Compiled on September 16, 2026 by TEN Capital Network" in printed
    assert "Northwind Robotics" in printed
    assert "ADVANCE" in printed  # 15% unscored is inside the pack's 30% limit
    assert "Not provided" in printed  # snapshot cells the deck did not state
    assert "unscored" in printed and "Unscored" in printed


def test_ownership_at_check_is_computed_from_a_pre_money_valuation():
    data = scorecard.render_pdf_bytes(typical(), check_size={"min_usd": 750_000, "max_usd": 1_500_000})
    printed = text_of(data)
    assert "5.0" in printed and "10.0%" in printed  # 0.75M-1.5M of a 15M post-money
    assert "(computed)" in printed


def test_the_worst_case_the_schema_allows_still_fits_one_page():
    screening = overstuffed()
    data = scorecard.render_pdf_bytes(screening)
    assert pages(data) == 1
    assert screening.provenance.truncations  # the reduction ladder was used and recorded


def test_blocks_that_must_never_be_dropped_survive_the_worst_case():
    printed = text_of(scorecard.render_pdf_bytes(overstuffed()))
    assert "SCREENING DECISION" in printed and "RULE APPLIED" in printed
    assert "DEAL-BREAKER" in printed
    assert "EVIDENCE TO REQUEST" in printed
    assert printed.count("/5") >= 10  # every factor cell is present
    assert "Reviewer decision:" in printed


def test_glyphs_missing_from_the_font_are_substituted():
    fonts = theme.register_fonts()
    assert theme.font_safe("a ≠ b → c", fonts) == "a != b -> c"
