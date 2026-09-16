"""The Criteria Pack builder prompt (CLAUDE.md §7, used verbatim) and its input rendering."""

from __future__ import annotations

import json
from typing import Any

from icb.profile.models import FIELD_KEYS

NOTE_CHAR_LIMIT = 20_000

SYSTEM = """You are a venture investment strategist helping an investor define the explicit criteria
and written thesis that every incoming deal will be screened against. You are given the
investor's profile and any thesis materials they supplied.

Rules:
- Do not invent the investor's preferences. Every criterion, weight, threshold, and filter
  must be derived from a specific profile field or thesis-note passage; record those
  field paths in `grounded_in`.
- Where a required input is missing, ambiguous, or contradictory (for example, a check
  size that cannot reach the ownership target at the stated round sizes), do not resolve it
  yourself. Set `needs_input` to one specific question the investor can answer, and add it
  to `open_questions`.
- Fields marked `no_preference` produce no criterion. List them in `not_applied`.
- Rubric levels must describe observable evidence a reviewer could verify in documents,
  not qualitative adjectives. Level 1 and level 5 must be clearly distinguishable by
  evidence alone.
- Separate deal-breakers (walk away regardless of other scores) from concerns (lower a
  named factor's score). Do not put the same condition in both.
- The thesis must state what the investor believes, where the opportunity is mispriced, why
  this investor has an edge, and why now, in 150-250 words. Base the edge only on the
  investor's actual record and resources. If none is evident, ask.
- Weights and thresholds are proposals for the investor to approve. Give each a one-line
  rationale tied to their stated return, liquidity, and time-horizon objectives.
- Write in professional, analytical language with no promotional tone.

Structure the pack so it can be applied mechanically: 6-10 scoring factors whose integer
weights sum to 100, exactly five rubric levels per factor (scores 1-5), and ids in
lowercase_snake_case. `advance_threshold` is a weighted 1.0-5.0 score, and
`max_unscored_weight_pct` is the share of factor weight that may go unscored before a deal is
held for evidence rather than decided."""


def render_profile(profile: dict[str, Any]) -> str:
    """The investor's answers, one line per field, with each field's status shown."""
    fields = profile.get("fields") or {}
    lines = [f"Investor: {profile.get('display_name', '')} (profile id: {profile.get('slug', '')})", "", "INPUTS"]
    for key in FIELD_KEYS:
        entry = fields.get(key) or {}
        status = entry.get("status", "not_provided")
        if status == "no_preference":
            lines.append(f"- fields.{key} [no_preference]: the investor deliberately does not apply this")
            continue
        value = json.dumps(entry.get("value"), ensure_ascii=False)
        affirmed = " (affirmed: no prior investments)" if entry.get("affirmed_none") else ""
        lines.append(f"- fields.{key} [{status}]{affirmed}: {value}")
    return "\n".join(lines)


def build_content(profile: dict[str, Any], notes: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """One user message: the profile, then any thesis materials, then the task."""
    blocks = [{"type": "text", "text": render_profile(profile)}]
    for name, text in notes:
        body = text.strip()[:NOTE_CHAR_LIMIT]
        if body:
            blocks.append({"type": "text", "text": f"--- THESIS NOTES: {name} ---\n{body}"})
    blocks.append({"type": "text", "text":
                   "Produce the Criteria Pack for this investor. Cite the profile field path in "
                   "`grounded_in` for every element, and use `needs_input` plus `open_questions` "
                   "wherever the inputs do not settle the question."})
    return blocks
