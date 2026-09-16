"""The scorecard's visual system: palette, fonts, density ladder (templates/one_pager.md §8-§10).

Every colour and font path lives here; nothing below this file hard-codes one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ASSETS = Path(__file__).resolve().parents[3] / "assets"
FONT_DIR = ASSETS / "fonts"
LOGO_PATH = ASSETS / "TEN_Capital_logo_footer.png"

DOC_TITLE = "Investor Screening Scorecard"
ORG_NAME = "TEN Capital Network"
SCORE_LABEL = "WEIGHTED SCORE"
DISCLAIMER = ("AI-assisted screening against the investor's approved criteria; not investment, legal, or tax "
              "advice. Verify all findings against source documents.")
AI_LABEL = "AI-assisted screening — verify against source"

ORANGE_HEX = "#E85D26"
NAVY = colors.HexColor("#1B2A4A")
NAVY_LIGHT = colors.HexColor("#26395F")
ORANGE = colors.HexColor("#E85D26")
LIGHT_BLUE = colors.HexColor("#C8D6E8")
BACKGROUND = colors.HexColor("#F7F9FC")
TINT = colors.HexColor("#EEF3F9")
INK = colors.HexColor("#1F2733")
MUTED = colors.HexColor("#5B6573")
RULE = colors.HexColor("#D5DDE8")
WHITE = colors.white

SCORE_COLORS = {5: "#1F7A4D", 4: "#3F8A3A", 3: "#A86B12", 2: "#D9531E", 1: "#B42318"}
UNSCORED_COLOR = "#8A94A3"
SEVERITY_COLORS = {
    "DEAL-BREAKER": colors.HexColor("#B42318"),
    "HIGH": colors.HexColor("#E85D26"),
    "MEDIUM": colors.HexColor("#A86B12"),
    "LOW": colors.HexColor("#5B7083"),
}
RESULT_COLORS = {"MET": "#1F7A4D", "UNVERIFIED": "#A86B12", "NOT MET": "#B42318", "NOT APPLIED": "#5B6573"}
DECISION_COLORS = {"ADVANCE": "#1F7A4D", "HOLD": "#A86B12", "PASS": "#B42318"}


@dataclass(frozen=True)
class Density:
    """One compression level; the renderer tries them in order until the page fits."""

    level: int
    body: float
    small: float
    criteria_chars: int
    factor_chars: int
    concerns: int
    issue_chars: int
    evidence_chars: int
    impact_chars: int
    resolution_chars: int
    request_chars: int
    bias_flags: int
    bias_chars: int
    rationale_chars: int
    thesis_fit_chars: int
    not_applied_line: bool
    gap: float


DENSITIES: tuple[Density, ...] = (
    Density(0, 7.3, 6.1, 150, 140, 4, 110, 130, 150, 110, 180, 4, 80, 420, 160, True, 6.0),
    Density(1, 7.1, 6.0, 130, 120, 4, 100, 100, 130, 90, 165, 4, 70, 390, 160, True, 5.5),
    Density(2, 6.9, 5.9, 110, 100, 3, 95, 80, 115, 70, 150, 3, 65, 360, 140, True, 5.0),
    Density(3, 6.7, 5.8, 95, 85, 3, 90, 60, 100, 0, 135, 3, 60, 320, 120, False, 4.5),
    Density(4, 6.5, 5.6, 80, 72, 2, 85, 45, 90, 0, 120, 2, 55, 290, 110, False, 4.0),
    Density(5, 6.3, 5.5, 65, 60, 2, 80, 0, 80, 0, 110, 2, 50, 260, 100, False, 3.5),
)


@dataclass(frozen=True)
class FontSet:
    regular: str
    bold: str
    italic: str
    unicode: bool


_REGISTERED: FontSet | None = None


def register_fonts(font_dir: Path | None = None) -> FontSet:
    """Open Sans when the TTFs are present; otherwise the built-in Helvetica family."""
    global _REGISTERED
    if _REGISTERED is not None:
        return _REGISTERED
    directory = font_dir or FONT_DIR
    files = {name: directory / f"OpenSans-{name}.ttf" for name in ("Regular", "Bold", "Italic")}
    if all(path.is_file() for path in files.values()):
        try:
            for name, path in files.items():
                pdfmetrics.registerFont(TTFont(f"OpenSans-{name}", str(path)))
            pdfmetrics.registerFontFamily("OpenSans", normal="OpenSans-Regular", bold="OpenSans-Bold",
                                          italic="OpenSans-Italic", boldItalic="OpenSans-Bold")
            _REGISTERED = FontSet("OpenSans-Regular", "OpenSans-Bold", "OpenSans-Italic", True)
            return _REGISTERED
        except Exception:  # a corrupt font must not stop the report
            pass
    _REGISTERED = FontSet("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", False)
    return _REGISTERED


GLYPH_SUBSTITUTIONS = {
    "≠": "!=", "→": "->", "←": "<-", "≥": ">=", "≤": "<=",
    "•": "-", "×": "x", "✓": "yes", "≡": "=",
}


def font_safe(text: str, fonts: FontSet) -> str:
    """Replace glyphs Open Sans lacks; with the fallback fonts, reduce to cp1252."""
    for source, replacement in GLYPH_SUBSTITUTIONS.items():
        text = text.replace(source, replacement)
    if not fonts.unicode:
        text = text.encode("cp1252", "replace").decode("cp1252")
    return text
