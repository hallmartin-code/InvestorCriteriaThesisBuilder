"""The one-page Screening Scorecard (templates/one_pager.md).

The story is built at each density level and measured against the frame before rendering; the
rendered bytes are then checked with pypdf, because reportlab paints past the bottom edge
without ever starting a second page. The decision panel, hard-criteria results, factor cells,
triggered deal-breakers and evidence requests are present at every level.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import BaseDocTemplate, Frame, KeepInFrame, PageTemplate, Paragraph, Spacer, Table, TableStyle

from icb.render import theme as t
from icb.screen.models import Screening

PAGE_WIDTH, PAGE_HEIGHT = letter
MARGIN_X = 0.42 * inch
MARGIN_TOP = 0.34 * inch
MARGIN_BOTTOM = 0.52 * inch
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X
FRAME_HEIGHT = PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
FIT_TOLERANCE = 4.0
NOT_PROVIDED = "Not provided"


class OnePageError(RuntimeError):
    """The scorecard could not be fitted to a single page."""


def render_pdf(screening: Screening, output: str | Path, check_size: dict[str, int] | None = None) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_pdf_bytes(screening, check_size))
    return path


def render_pdf_bytes(screening: Screening, check_size: dict[str, int] | None = None) -> bytes:
    fonts = t.register_fonts()
    for density in t.DENSITIES:
        story = _story(screening, density, fonts, check_size)
        if _measure(story) > FRAME_HEIGHT - FIT_TOLERANCE:
            continue
        data = _render(story, screening, fonts)
        if _page_count(data) == 1:
            screening.provenance.truncations = [f"density level {density.level}"] if density.level else []
            return data
    story = _story(screening, t.DENSITIES[-1], fonts, check_size)
    data = _render([KeepInFrame(CONTENT_WIDTH, FRAME_HEIGHT - FIT_TOLERANCE, story, mode="shrink")], screening, fonts)
    if _page_count(data) != 1:
        raise OnePageError("The scorecard could not be fitted to a single page.")
    screening.provenance.truncations = ["density level 5", "shrink to fit"]
    return data


def _page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _measure(story: list[Any]) -> float:
    total = 0.0
    for flowable in story:
        _, height = flowable.wrap(CONTENT_WIDTH, FRAME_HEIGHT * 20)
        total += height + flowable.getSpaceBefore() + flowable.getSpaceAfter()
    return total


def _render(story: list[Any], screening: Screening, fonts: t.FontSet) -> bytes:
    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer, pagesize=letter, leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM, title=f"{t.DOC_TITLE} - {screening.company_name()}",
        author=t.ORG_NAME, subject="Investor screening scorecard", creator=t.ORG_NAME)
    frame = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_WIDTH, FRAME_HEIGHT, leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0, id="body")
    doc.addPageTemplates([PageTemplate(id="one", frames=[frame],
                                       onPage=lambda canvas, _doc: _footer(canvas, fonts, screening))])
    doc.build(list(story))
    return buffer.getvalue()


def _footer(canvas: Any, fonts: t.FontSet, screening: Screening) -> None:
    """House footer: [Title]   [PAGE#]   Compiled on [DATE] by TEN Capital Network   [logo]."""
    date = _date_words(screening.provenance.generated_at)
    text = f"{t.DOC_TITLE}          {canvas.getPageNumber()}          Compiled on {date} by {t.ORG_NAME}    "
    logo_w, logo_h = 48.0, 18.0
    has_logo = t.LOGO_PATH.is_file()
    text_w = stringWidth(text, fonts.regular, 7)
    x = (PAGE_WIDTH - text_w - (logo_w if has_logo else 0)) / 2
    y = 0.24 * inch
    canvas.saveState()
    canvas.setFont(fonts.regular, 7)
    canvas.setFillColor(t.MUTED)
    canvas.drawString(x, y + 5, text)
    if has_logo:
        canvas.drawImage(str(t.LOGO_PATH), x + text_w, y, width=logo_w, height=logo_h,
                         mask="auto", preserveAspectRatio=True)
    canvas.restoreState()


def _date_words(iso: str) -> str:
    from datetime import datetime

    try:
        moment = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        moment = datetime.now()
    return f"{moment.strftime('%B')} {moment.day}, {moment.year}"


class _Styles:
    def __init__(self, density: t.Density, fonts: t.FontSet) -> None:
        body, small = density.body, density.small
        self.fonts, self.density = fonts, density
        self.body = ParagraphStyle("body", fontName=fonts.regular, fontSize=body, leading=body * 1.22,
                                   textColor=t.INK, spaceAfter=body * 0.28)
        self.small = ParagraphStyle("small", parent=self.body, fontSize=small, leading=small * 1.22,
                                    textColor=t.MUTED, spaceAfter=0)
        self.cell = ParagraphStyle("cell", parent=self.body, spaceAfter=0)
        self.section = ParagraphStyle("section", fontName=fonts.bold, fontSize=7.6, leading=9.2, textColor=t.NAVY)
        self.eyebrow = ParagraphStyle("eyebrow", fontName=fonts.bold, fontSize=7.2, leading=9, textColor=t.ORANGE)
        self.meta = ParagraphStyle("meta", fontName=fonts.regular, fontSize=6.8, leading=8.4, textColor=t.LIGHT_BLUE)
        self.tile = ParagraphStyle("tile", fontName=fonts.bold, fontSize=19, leading=21, textColor=t.WHITE,
                                   alignment=TA_CENTER)
        self.tile_label = ParagraphStyle("tile_label", fontName=fonts.regular, fontSize=5.9, leading=7.2,
                                         textColor=t.LIGHT_BLUE, alignment=TA_CENTER)
        self.center = ParagraphStyle("center", parent=self.cell, alignment=TA_CENTER, fontSize=small,
                                     leading=small * 1.18)
        self.chip = ParagraphStyle("chip", fontName=fonts.bold, fontSize=small, leading=small * 1.2,
                                   textColor=t.WHITE, alignment=TA_CENTER)


def _safe(text: str, styles: _Styles) -> str:
    return escape(t.font_safe(str(text or ""), styles.fonts))


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _rich(text: str, styles: _Styles, limit: int) -> str:
    """Escaped, shortened, with the inline markers highlighted."""
    value = _safe(_short(text, limit), styles)
    for marker in ("NOT PROVIDED", "UNVERIFIED", "Unscored"):
        value = value.replace(marker, f'<font color="{t.ORANGE_HEX}"><b>{marker}</b></font>')
    return value


def _section(title: str, styles: _Styles, width: float = CONTENT_WIDTH) -> Table:
    table = Table([[Paragraph(escape(title.upper()), styles.section)]], colWidths=[width])
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.9, t.ORANGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
    ]))
    return table


def _story(screening: Screening, density: t.Density, fonts: t.FontSet,
           check_size: dict[str, int] | None) -> list[Any]:
    styles = _Styles(density, fonts)
    gap = density.gap
    return [
        _header(screening, styles),
        Spacer(1, gap),
        _section("Company Snapshot", styles),
        Spacer(1, 2.5),
        _snapshot(screening, styles, check_size),
        Spacer(1, 3),
        _score_strip(screening, styles),
        Spacer(1, gap),
        _two_columns(screening, styles),
        Spacer(1, gap),
        _section("Deal-Breakers & Concerns", styles),
        Spacer(1, 2.5),
        _risks(screening, styles),
        Spacer(1, gap),
        _gaps_and_requests(screening, styles),
        Spacer(1, gap),
        _decision(screening, styles),
        Spacer(1, 3),
        _basis(screening, styles),
    ]


def _header(screening: Screening, styles: _Styles) -> Table:
    decision = screening.decision
    provenance = screening.provenance
    name = screening.company_name()
    size = 15 if len(name) <= 42 else 12.5 if len(name) <= 80 else 10.5
    name_style = ParagraphStyle("name", fontName=styles.fonts.bold, fontSize=size, leading=size * 1.15,
                                textColor=t.WHITE)
    company = screening.extraction.company
    meta_parts = [value for value in (_value(company.sector), _value(company.stage), _value(company.geography)) if value]
    meta_parts.append(f"Source: {provenance.source_filename} ({provenance.slide_count} slides)")
    meta_parts.append(_date_words(provenance.generated_at))
    pack = provenance.criteria_pack or {}
    meta_two = (f"Screened for {pack.get('investor_name', screening.investor_name)}  ·  "
                f"Criteria Pack v{pack.get('version', '?')}  ·  #{str(pack.get('hash', ''))[:8]}")

    left = [
        Paragraph("INVESTOR SCREENING SCORECARD", styles.eyebrow),
        Paragraph(_safe(_short(name, 140), styles), name_style),
        Paragraph(_safe(_short("  ·  ".join(meta_parts), 150), styles), styles.meta),
        Paragraph(_safe(meta_two, styles), styles.meta),
    ]
    score = "—" if decision.weighted_score is None else f"{decision.weighted_score:.1f}"
    tiles = Table([[
        [Paragraph(f'{score}<font size="8.5"> /5</font>', styles.tile),
         Paragraph(f"{t.SCORE_LABEL} · ADVANCE AT {decision.advance_threshold:.1f}", styles.tile_label)],
        [Paragraph(f'{decision.evidence_coverage}<font size="8.5"> /100</font>', styles.tile),
         Paragraph("EVIDENCE COVERAGE", styles.tile_label)],
    ]], colWidths=[95, 95])
    tiles.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), t.NAVY_LIGHT), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEAFTER", (0, 0), (0, 0), 0.6, t.NAVY), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    header = Table([[left, tiles]], colWidths=[CONTENT_WIDTH - 200, 200])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), t.NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 10), ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -1), 2, t.ORANGE),
    ]))
    return header


def _value(field: Any) -> str:
    return field.value or "" if field else ""


def _cell(label: str, field: Any, styles: _Styles, limit: int = 48, suffix: str = "") -> Paragraph:
    small = styles.small.fontSize
    if field is None or not getattr(field, "value", None):
        body = f'<font color="#5B6573"><i>{NOT_PROVIDED}</i></font>'
    else:
        body = f"<b>{_safe(_short(field.value, limit), styles)}</b>"
        if field.classification == "INFERENCE":
            body += f' <font size="{small - 0.4}" color="#5B6573">(inferred)</font>'
        if suffix:
            body += f' <font size="{small - 0.4}" color="#5B6573">{escape(suffix)}</font>'
    return Paragraph(f'<font size="{small - 0.2}" color="#5B6573">{escape(label.upper())}</font><br/>{body}',
                     styles.cell)


def _joined(styles: _Styles, label: str, *fields: Any, limit: int = 60) -> Paragraph:
    parts = [f.value for f in fields if f is not None and f.value]
    if not parts:
        return _cell(label, None, styles)
    inferred = any(f is not None and f.value and f.classification == "INFERENCE" for f in fields)
    joined = type("Joined", (), {"value": " · ".join(parts),
                                 "classification": "INFERENCE" if inferred else "FACT"})()
    return _cell(label, joined, styles, limit)


def _snapshot(screening: Screening, styles: _Styles, check_size: dict[str, int] | None) -> Table:
    company = screening.extraction.company
    valuation_suffix = company.valuation_basis if company.valuation.value else ""
    ownership = _ownership_at_check(company, check_size)
    rows = [
        [_joined(styles, "Sector · Subsector", company.sector, company.subsector),
         _cell("Stage", company.stage, styles),
         _cell("Geography", company.geography, styles),
         _joined(styles, "Revenue / Traction", company.revenue, company.key_traction)],
        [_joined(styles, "Raise · Instrument", company.raise_amount, company.instrument),
         _cell("Valuation", company.valuation, styles, suffix=valuation_suffix),
         _joined(styles, "Committed · Lead", company.amount_committed, company.lead_investor),
         _cell("Ownership at check", ownership, styles, suffix="(computed)" if ownership else "")],
    ]
    width = CONTENT_WIDTH / 4
    table = Table(rows, colWidths=[width] * 4)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), t.BACKGROUND), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, t.RULE), ("LINEAFTER", (0, 0), (-2, -1), 0.4, t.RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
    ]))
    return table


def _ownership_at_check(company: Any, check_size: dict[str, int] | None) -> Any | None:
    """Post-money = valuation, or valuation + raise when the deck states a pre-money number."""
    if not check_size or company.valuation.amount_usd is None or company.valuation_basis == "not stated":
        return None
    post = company.valuation.amount_usd
    if company.valuation_basis == "pre-money":
        post += company.raise_amount.amount_usd or 0
    if post <= 0:
        return None
    low = (check_size.get("min_usd") or 0) / post * 100
    high = (check_size.get("max_usd") or 0) / post * 100
    if high <= 0:
        return None
    return type("Computed", (), {"value": f"{low:.1f}–{high:.1f}%", "classification": "FACT"})()


def _score_strip(screening: Screening, styles: _Styles) -> Table:
    cells = []
    small = styles.small.fontSize
    for factor in screening.extraction.factors:
        unscored = factor.score is None
        colour = t.UNSCORED_COLOR if unscored else t.SCORE_COLORS[factor.score]
        value = "—" if unscored else str(factor.score)
        note = ""
        if unscored:
            note = '<br/><font size="4.8" color="#8A94A3">unscored</font>'
        elif factor.floor is not None and factor.score < factor.floor:
            note = f'<br/><font size="4.8" color="{t.SCORE_COLORS[1]}">below floor {factor.floor}</font>'
        cells.append(Paragraph(
            f'<font size="{small - 0.3}" color="#5B6573">{_safe(factor.short_label or factor.factor_id, styles)}</font>'
            f'<br/><font size="9.5" color="{colour}"><b>{value}</b></font>'
            f'<font size="5.6" color="#8A94A3">/5 · {factor.weight}%</font>{note}', styles.center))
    if not cells:
        cells = [Paragraph("No factors in this pack.", styles.center)]
    table = Table([cells], colWidths=[CONTENT_WIDTH / len(cells)] * len(cells))
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, t.RULE), ("LINEAFTER", (0, 0), (-2, -1), 0.4, t.RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8), ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
    ]))
    return table


def _slides(slides: list[int]) -> str:
    return f" ({', '.join(f'S{n}' for n in slides[:4])})" if slides else ""


def _two_columns(screening: Screening, styles: _Styles) -> Table:
    density = styles.density
    gutter = 12
    col = (CONTENT_WIDTH - gutter) / 2

    left: list[Any] = [_section("Hard Criteria", styles, col), Spacer(1, 2.5)]
    for result in screening.extraction.hard_criteria:
        colour = t.RESULT_COLORS.get(result.result, "#5B6573")
        evidence = _rich(result.deck_evidence, styles, density.criteria_chars)
        left.append(Paragraph(
            f'<font color="#1B2A4A"><b>{_safe(result.label or result.criterion_id, styles)}:</b></font> '
            f'<font color="{colour}"><b>{result.result}</b></font> — {evidence}'
            f'<font color="#5B6573">{escape(_slides(result.slides))}</font>', styles.body))
    if density.not_applied_line:
        not_applied = (screening.provenance.criteria_pack or {}).get("not_applied") or []
        if not_applied:
            left.append(Paragraph(f'<font color="#5B6573">Not applied: '
                                  f'{_safe(", ".join(not_applied), styles)}</font>', styles.small))

    right: list[Any] = [_section("Factor Evidence", styles, col), Spacer(1, 2.5)]
    for factor in screening.extraction.factors:
        label = _safe(factor.label or factor.factor_id, styles)
        if factor.score is None:
            body = f'<font color="#E85D26"><b>Unscored</b></font> — {_rich(factor.gap, styles, density.factor_chars)}'
            head = f"{label} —/5"
        else:
            body = _rich(factor.evidence_summary, styles, density.factor_chars) + \
                   f'<font color="#5B6573">{escape(_slides([e.slide for e in factor.evidence if e.slide]))}</font>'
            head = f"{label} {factor.score}/5"
            if factor.floor is not None and factor.score < factor.floor:
                body += f' <font color="#5B6573">· below floor {factor.floor}</font>'
        right.append(Paragraph(f'<font color="#1B2A4A"><b>{head}:</b></font> {body}', styles.body))

    table = Table([[left, "", right]], colWidths=[col, gutter, col])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _risks(screening: Screening, styles: _Styles) -> Table:
    density = styles.density
    widths = [58, 256, CONTENT_WIDTH - 314]
    rows = [[Paragraph("<b>SEVERITY</b>", styles.small), Paragraph("<b>ISSUE &amp; EVIDENCE</b>", styles.small),
             Paragraph("<b>IMPACT ON SCREEN &amp; RESOLUTION</b>", styles.small)]]
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.5, t.NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.5), ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
    ]

    entries: list[tuple[str, Any, str]] = [("DEAL-BREAKER", item, "deal_breaker")
                                           for item in screening.extraction.deal_breakers_triggered]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    concerns = sorted(screening.extraction.concerns, key=lambda c: order.get(c.severity, 3))
    entries += [(concern.severity, concern, "concern") for concern in concerns[: density.concerns]]

    if not entries:
        rows.append([Paragraph("—", styles.center),
                     Paragraph("No deal-breakers triggered and no concerns identified from deck evidence.", styles.cell),
                     Paragraph("Verify deck claims against source documents.", styles.cell)])
    for index, (severity, item, kind) in enumerate(entries, start=1):
        evidence = ""
        if density.evidence_chars and item.excerpt:
            excerpt = _safe(_short(item.excerpt, density.evidence_chars), styles)
            slide = f"S{item.slides[0]}: " if item.slides else ""
            evidence = (f'<br/><font size="{styles.small.fontSize}" color="#5B6573">'
                        f'{item.classification} · {escape(slide)}"{excerpt}"</font>')
        if kind == "deal_breaker":
            impact = f"Walk-away condition: {_safe(_short(item.walk_away_condition, density.impact_chars), styles)}"
        else:
            impact = (f"Lowers {_safe(item.factor_label or item.factor_id, styles)}. "
                      f"{_safe(_short(item.consequence, density.impact_chars), styles)}")
        if density.resolution_chars and item.resolution:
            impact += (f' <font color="#1B2A4A"><b>Resolve:</b></font> '
                       f"{_safe(_short(item.resolution, density.resolution_chars), styles)}")
        rows.append([
            Paragraph(severity, styles.chip),
            Paragraph(f"<b>{_safe(_short(item.issue, density.issue_chars), styles)}</b>{evidence}", styles.cell),
            Paragraph(impact, styles.cell),
        ])
        commands.append(("BACKGROUND", (0, index), (0, index), t.SEVERITY_COLORS.get(severity, t.MUTED)))
        if index % 2 == 0:
            commands.append(("BACKGROUND", (1, index), (-1, index), t.BACKGROUND))
        commands.append(("LINEBELOW", (0, index), (-1, index), 0.3, t.RULE))

    table = Table(rows, colWidths=widths)
    table.setStyle(TableStyle(commands))
    return table


def _gaps_and_requests(screening: Screening, styles: _Styles) -> Table:
    density = styles.density
    decision = screening.decision
    gutter = 12
    col = (CONTENT_WIDTH - gutter) / 2

    unscored = sum(1 for factor in screening.extraction.factors if factor.score is None)
    coverage = (f"{unscored} of {len(screening.extraction.factors)} factors unscored "
                f"({decision.unscored_weight_pct}% of weight; limit {decision.max_unscored_weight_pct}%). "
                f"{decision.criteria_counts.get('unverified', 0)} hard criteria unverified.")
    left: list[Any] = [_section("Evidence Gaps & Bias Flags", styles, col), Spacer(1, 2.5),
                       Paragraph(_safe(coverage, styles), styles.body)]
    flags = screening.extraction.bias_flags[: density.bias_flags]
    for flag in flags:
        detail = f" · {_slides(flag.slides).strip(' ()')}" if flag.slides else ""
        left.append(Paragraph(
            f'<font color="#E85D26"><b>•</b></font> <b>{_safe(_short(flag.signal, density.bias_chars), styles)}</b>'
            f' <font color="#5B6573">› {escape(flag.type)}{escape(detail)}</font>', styles.body))
    if not flags:
        left.append(Paragraph('<font color="#5B6573">No bias signals flagged.</font>', styles.body))

    right: list[Any] = [_section("Evidence to Request", styles, col), Spacer(1, 2.5)]
    for request in screening.extraction.evidence_requests[:5]:
        right.append(Paragraph(
            f'<font color="#E85D26"><b>{request.priority}.</b></font> '
            f'{_safe(_short(request.request, density.request_chars), styles)} '
            f'<font size="{styles.small.fontSize}" color="#5B6573">[{escape(request.audience)}]</font>', styles.body))
    if not screening.extraction.evidence_requests:
        right.append(Paragraph('<font color="#5B6573">Nothing further requested from the deck.</font>', styles.body))

    table = Table([[left, "", right]], colWidths=[col, gutter, col])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _decision(screening: Screening, styles: _Styles) -> Table:
    density = styles.density
    decision = screening.decision
    counts = decision.criteria_counts
    key = "HOLD" if decision.decision.startswith("HOLD") else decision.decision
    worst = "NOT MET" if counts.get("not_met") else "UNVERIFIED" if counts.get("unverified") else "MET"

    def chip(label: str, value: str, colour: str) -> Paragraph:
        return Paragraph(
            f'<font size="{styles.small.fontSize - 0.2}" color="#5B6573">{escape(label)}</font><br/>'
            f'<font size="{styles.body.fontSize + 1.6}" color="{colour}"><b>{_safe(value, styles)}</b></font>',
            styles.cell)

    chips = Table([[
        chip("DECISION", decision.decision, t.DECISION_COLORS[key]),
        chip("HARD CRITERIA", f"{counts.get('met', 0)} MET · {counts.get('unverified', 0)} UNVERIFIED "
                              f"· {counts.get('not_met', 0)} NOT MET", t.RESULT_COLORS[worst]),
        chip("RULE APPLIED", f"Rule {decision.rule} — {decision.rule_label}", "#1B2A4A"),
    ]], colWidths=[150, 150, CONTENT_WIDTH - 8 - 300 - 18])
    chips.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    rationale = f"{decision.rule_sentence} {screening.extraction.screening_summary}"
    review = screening.review or {}
    blank = "_" * 18
    reviewer = (f"Reviewer decision: {review.get('final_decision') or blank}   "
                f"Override: {('Yes' if review.get('override') else 'No') if review else '____'}   "
                f"Reason: {review.get('exception_reason') or '_' * 24}   "
                f"Initials / date: {review.get('reviewer_initials') or '______'} {review.get('decided_at', '')[:10] or '______'}")

    heading = Table([[Paragraph("SCREENING DECISION", styles.section),
                      Paragraph(f'<font color="#5B6573"><i>{escape(t.AI_LABEL)}</i></font>',
                                ParagraphStyle("ai", parent=styles.small, alignment=2))]],
                    colWidths=[CONTENT_WIDTH * 0.45, CONTENT_WIDTH * 0.55 - 22])
    heading.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))

    body = [heading, chips,
            Paragraph(_safe(_short(rationale, density.rationale_chars), styles), styles.cell),
            Paragraph(f'<font color="#1B2A4A"><b>Thesis fit:</b></font> '
                      f'{_safe(_short(screening.extraction.thesis_fit, density.thesis_fit_chars), styles)}', styles.cell),
            Paragraph(f'<font color="#5B6573">{_safe(reviewer, styles)}</font>', styles.small)]
    table = Table([["", body]], colWidths=[4, CONTENT_WIDTH - 4])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), t.ORANGE), ("BACKGROUND", (1, 0), (1, 0), t.TINT),
        ("LEFTPADDING", (1, 0), (1, 0), 9), ("RIGHTPADDING", (1, 0), (1, 0), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0),
    ]))
    return table


def _basis(screening: Screening, styles: _Styles) -> Paragraph:
    extraction = screening.extraction
    provenance = screening.provenance
    names = [name for name in type(extraction.company).model_fields if name != "valuation_basis"]
    fields = [getattr(extraction.company, name) for name in names]
    facts = sum(1 for f in fields if f.classification == "FACT")
    inferences = sum(1 for f in fields if f.classification == "INFERENCE")
    missing = sum(1 for f in fields if f.classification == "NOT PROVIDED")
    scored = sum(1 for f in extraction.factors if f.score is not None)
    pack = provenance.criteria_pack or {}
    text = (f"Evidence basis: {facts} facts · {inferences} inferences · {missing} items not provided · "
            f"{scored} of {len(extraction.factors)} factors scored · "
            f"{screening.decision.criteria_counts.get('unverified', 0)} criteria unverified · "
            f"{len(extraction.deal_breakers_triggered)} deal-breakers / {len(extraction.concerns)} concerns · "
            f"{len(extraction.bias_flags)} bias flags · slide refs S# · "
            f"Criteria Pack v{pack.get('version', '?')} #{str(pack.get('hash', ''))[:8]} · "
            f"engine: Claude ({provenance.model}){' · cached' if provenance.cached else ''}. {t.DISCLAIMER}")
    style = ParagraphStyle("basis", parent=styles.small, fontSize=5.6, leading=6.9)
    return Paragraph(_safe(text, styles), style)
