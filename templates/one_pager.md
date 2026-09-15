# TEN Capital — Investor Screening Scorecard Template

The structure, fields, and formatting of the one-page PDF that `icb screen` generates. It is
company-agnostic and investor-agnostic: nothing here belongs to a specific deck, company,
investor, or run. Every `{placeholder}` arrives through the data contract in §5. The renderer
owns structure and formatting only. Content comes from the screening extraction, the
approved Criteria Pack, and `screen/decision.py`.

This document is a contract, not documentation. `tests/test_template.py` asserts that the
block order, vocabularies, fixed strings, palette tokens, and density ladder below match
`src/icb/screen/models.py`, `src/icb/screen/decision.py`, and `src/icb/render/`. If the code
changes and this file does not, the tests fail.

**Visual lineage.** The format replicates the TEN Capital one-page diligence report
(reference implementation: `../TechDiligenceIPRisk/app/reporting/pdf_generator.py` and
`templates.py`). The geometry, palette, typography, and fitting strategy are reused. The
fields are those of an investor-criteria screen.

---

## 1. Hard constraints

1. **Exactly one page. Always.** Overflow is resolved by the density ladder (§8), never by a
   second page. Fit is measured against the frame geometry, and the rendered bytes are
   checked with pypdf.
2. **These elements are never dropped at any density:**
   - the decision panel: decision, rule applied, and reviewer line
   - every hard-criterion result
   - every factor score cell
   - every triggered deal-breaker
   - the evidence-to-request list

   Density may shorten their text. It may not remove them.
3. **The decision is computed in code.** No model-written text on this page states or implies
   a decision different from `decision.decision`.

---

## 2. Page geometry

| Property | Value |
|---|---|
| Paper | US Letter, portrait |
| Margins | left/right 0.42in · top 0.34in · bottom 0.52in |
| Content width | page width − 0.84in |
| Two-column blocks | two equal columns, 12pt gutter |
| Footer baseline | 0.24in from the bottom edge, outside the content frame |
| Fonts | Open Sans Regular / Bold / Italic (TTF). Fallback: Helvetica family, with text reduced to cp1252 |

---

## 3. Document map

| # | Block | Layout |
|---|---|---|
| 1 | Header band | Full width, navy. Title block on the left, two score tiles on the right |
| 2 | Company Snapshot | Section rule + 4 × 2 label/value grid |
| 3 | Factor score strip | One row, one cell per Criteria Pack factor (6–10) |
| 4 | Hard Criteria \| Factor Evidence | Two columns of labelled lines |
| 5 | Deal-Breakers & Concerns | Section rule + 3-column table |
| 6 | Evidence Gaps & Bias Flags \| Evidence to Request | Two columns |
| 7 | Screening Decision | Tinted panel with an orange left bar: 3 chips + rationale + thesis fit + reviewer line |
| 8 | Evidence basis | One line of small muted text |
| 9 | Page footer | TEN Capital house footer |

Spacing between blocks is the density `gap` (§8). Section rules are 0.9pt orange lines
under an uppercase navy heading (7.6pt bold).

### Skeleton

```
┌───────────────────────────────────────────────────────────────┬──────────────┬──────────────┐
│ INVESTOR SCREENING SCORECARD                        (eyebrow) │  {ws} /5     │  {cov} /100  │
│ {company_name}                                                │ WEIGHTED     │ EVIDENCE     │
│ {sector} · {stage} · {geography} · Source: {file} ({n} slides) · {date}      │ COVERAGE     │
│ Screened for {investor_name} · Criteria Pack v{N} · #{hash8}  │ ADVANCE AT {t}              │
└───────────────────────────────────────────────────────────────┴──────────────┴──────────────┘
COMPANY SNAPSHOT ──────────────────────────────────────────────────────────────────────────────
│ SECTOR · SUBSECTOR   │ STAGE               │ GEOGRAPHY            │ REVENUE / TRACTION      │
│ RAISE · INSTRUMENT   │ VALUATION           │ COMMITTED · LEAD     │ OWNERSHIP AT CHECK      │
│ {factor1} n/5·w% │ {factor2} n/5·w% │ … one cell per pack factor … │ {factorN} —/5·w% unscored │
HARD CRITERIA ──────────────────────────────   FACTOR EVIDENCE ───────────────────────────────
{Criterion}: MET — {deck evidence} (S{n})      {Factor} {n}/5: {evidence summary} (S{n}, S{n})
{Criterion}: UNVERIFIED — {what is missing}    {Factor} —/5: Unscored — {gap}
{Criterion}: NOT MET — {deck evidence} (S{n})  {Factor} {n}/5: {…} · below floor {f}
Not applied: {criterion}, {criterion}
DEAL-BREAKERS & CONCERNS ──────────────────────────────────────────────────────────────────────
SEVERITY      │ ISSUE & EVIDENCE                        │ IMPACT ON SCREEN & RESOLUTION
DEAL-BREAKER  │ {issue}                                 │ Walk-away condition: {…} Resolve: {…}
{HIGH|MED|LOW}│ {CLASSIFICATION} · S{n}: "{excerpt}"    │ Lowers {factor}. {consequence} Resolve: {…}
EVIDENCE GAPS & BIAS FLAGS ─────────────────   EVIDENCE TO REQUEST ───────────────────────────
{n} of {N} factors unscored ({p}% of weight;    1. {request} [{audience}]
limit {max}%). {u} hard criteria unverified.    2. …  (max 5)
• {signal} › {bias type} · S{n}
┃ SCREENING DECISION
┃ DECISION                 HARD CRITERIA                         RULE APPLIED
┃ {ADVANCE|PASS|HOLD — …}  {m} MET · {u} UNVERIFIED · {x} NOT MET  Rule {n} — {rule label}
┃ {rationale}
┃ Thesis fit: {thesis_fit}
┃ Reviewer decision: {…}   Override: {…}   Reason: {…}   Initials / date: {…}
Evidence basis: {n} facts · {n} inferences · {n} items not provided · {s} of {N} factors scored · …

        Investor Screening Scorecard          {page}          Compiled on {Month D, YYYY} by TEN Capital Network    [logo]
```

---

## 4. Block specifications

### 4.1 Header band

- Background navy, with a 2pt orange line beneath it.
- **Left** (content width − 190pt), top to bottom:
  - Eyebrow: `INVESTOR SCREENING SCORECARD`, orange, 7.2pt bold.
  - Company name: white, bold. 15pt if ≤ 42 chars, 12.5pt if ≤ 80, else 10.5pt. Truncated at 140 chars.
  - Meta line 1: light blue, 6.8pt. Joined with `  ·  ` from `{sector}` (≤ 40), `{stage}` (≤ 40), `{geography}` (≤ 30), `Source: {source_filename} ({slide_count} slides)`, and `{generated_at:%b %d, %Y}`. Parts that are not provided are omitted. The whole line is truncated at 150 chars.
  - Meta line 2: light blue, 6.8pt: `Screened for {investor_name}  ·  Criteria Pack v{version}  ·  #{pack_hash[:8]}`.
- **Right**: two 88pt tiles on navy-light, separated by a navy rule.
  - Tile 1: `{weighted_score:.1f}` (19pt bold white) + ` /5` (8.5pt). Label: `WEIGHTED SCORE · ADVANCE AT {advance_threshold:.1f}` (5.9pt, light blue). If no factor is scored, the value is `—`.
  - Tile 2: `{evidence_coverage}` + ` /100`. Label: `EVIDENCE COVERAGE`.
- If no company name is provided, it renders as `Unnamed company`.

### 4.2 Company Snapshot (4 × 2 grid)

Each cell: an uppercase muted label on top, with a bold value below it (≤ 48 chars unless noted).

| Row | Col 1 | Col 2 | Col 3 | Col 4 |
|---|---|---|---|---|
| 1 | `SECTOR · SUBSECTOR` ← `sector` · `subsector` (≤ 60) | `STAGE` ← `stage` | `GEOGRAPHY` ← `geography` | `REVENUE / TRACTION` ← `revenue` · `key_traction` (≤ 60) |
| 2 | `RAISE · INSTRUMENT` ← `raise_amount` · `instrument` (≤ 60) | `VALUATION` ← `valuation` + ` {valuation_basis}` | `COMMITTED · LEAD` ← `amount_committed` · `lead_investor` (≤ 60) | `OWNERSHIP AT CHECK` ← computed (§6) |

Cell rules:
- Not provided → muted italic `Not provided`.
- Classification `INFERENCE` → the value is followed by a small muted `(inferred)`.
- A computed value is followed by a small muted `(computed)`.
- Combined cells join their two parts with ` · ` and omit whichever part is missing. If both parts are missing, the cell shows `Not provided`.

Grid: background tint, 0.4pt rules between cells and rows.

### 4.3 Factor score strip

One boxed row with one equal-width cell per Criteria Pack factor, in pack order. Each cell,
centered:

```
{short_label}             muted, small − 0.3pt  (≤ 12 chars, defined in the pack)
{score}/5 · {weight}%     score 9.5pt bold, colored by SCORE_COLORS; suffix 5.6pt grey
unscored                  4.8pt grey — when score is null (value shows "—", greyed)
below floor               4.8pt, SCORE_COLORS[1] — when score < factor floor
```

### 4.4 Hard Criteria | Factor Evidence

Each line renders as `**{Label}:** {text}`, with the label in bold navy. Text is truncated to the
density limit. The literals `UNVERIFIED`, `Unscored`, and `NOT PROVIDED` inside text are
rendered bold orange.

**Left column: Hard Criteria** (limit `criteria_chars`). One line per pack hard criterion, in
pack order:

```
**{label}:** <b color=RESULT_COLORS[result]>{result}</b> — {deck_evidence} (S{n}, S{n})
```

- `UNVERIFIED` lines state what the deck does not show instead of quoting evidence.
- When `not_applied_line` is on and the pack has `not_applied` entries, the column ends with
  a muted line `Not applied: {label}, {label}`.

**Right column: Factor Evidence** (limit `factor_chars`). One line per pack factor, in pack order:

| State | Line |
|---|---|
| Scored | `**{label} {score}/5:** {evidence_summary} (S{n}, S{n})` |
| Scored, below floor | the same line, plus muted ` · below floor {floor}` |
| Unscored | `**{label} —/5:** Unscored — {gap}` |

### 4.5 Deal-Breakers & Concerns table

Column widths: 58pt | 256pt | remainder. The header row has bold small caps with a 0.5pt navy
rule under it.

Row order: every triggered deal-breaker (never capped), then concerns sorted HIGH → MEDIUM →
LOW, capped at `concerns`.

| Column | Content |
|---|---|
| `SEVERITY` | White bold chip on `SEVERITY_COLORS[severity]`: `DEAL-BREAKER`, `HIGH`, `MEDIUM`, or `LOW` |
| `ISSUE & EVIDENCE` | **`{issue}`** (≤ `issue_chars`), then a muted line `{classification} · S{slide}: "{excerpt}"` (≤ `evidence_chars`; omitted when 0) |
| `IMPACT ON SCREEN & RESOLUTION` | Deal-breaker: `Walk-away condition: {pack condition}`. Concern: `Lowers {factor label}. {consequence}`. Both ≤ `impact_chars`. Then bold navy `Resolve:` + `{resolution}` (≤ `resolution_chars`; omitted when 0) |

Even rows get a tinted background, with a 0.3pt rule under each row. If there are no
deal-breakers and no concerns, show one row: `—` | `No deal-breakers triggered and no concerns identified from deck evidence.` | `Verify deck claims against source documents.`

### 4.6 Evidence Gaps & Bias Flags | Evidence to Request

**Left: Evidence Gaps & Bias Flags**
1. A coverage sentence, assembled in code and never truncated:
   `{unscored_count} of {factor_count} factors unscored ({unscored_weight_pct}% of weight; limit {max_unscored_weight_pct}%). {unverified_count} hard criteria unverified.`
2. Up to `bias_flags` bullet lines: `•` (orange) **`{signal}`** (≤ `bias_chars`), then muted `› {bias type} · S{n}`. If a flag names an affected factor, the muted text also shows ` · {factor short_label}`.
3. If there are no bias flags, a muted line `No bias signals flagged.`

**Right: Evidence to Request**
Up to 5 lines: `{priority}.` (orange bold) `{request}` (≤ `request_chars`), then muted `[{audience}]`.

Priority order, assigned in code:
1. Requests linked to UNVERIFIED hard criteria.
2. Requests linked to unscored factors, heaviest weight first.
3. Requests linked to concerns, HIGH first.

### 4.7 Screening Decision panel

A 4pt orange bar on the left and a tinted panel with 9pt inner padding.

- Heading: `SCREENING DECISION`.
- Three chips (150pt, 150pt, remainder). Each has a small muted label above a bold value (body + 1.6pt):
  - `DECISION` → `{decision}`, colored by DECISION_COLORS.
  - `HARD CRITERIA` → `{met} MET · {unverified} UNVERIFIED · {not_met} NOT MET`, colored by the worst result present (RESULT_COLORS).
  - `RULE APPLIED` → `Rule {rule} — {rule_label}`, navy.
- Rationale paragraph (≤ `rationale_chars`): the code-assembled rule sentence (§6), then the model's `screening_summary`.
- `Thesis fit:` (bold navy) + `{thesis_fit}` (≤ `thesis_fit_chars`).
- Reviewer line (small; never dropped):
  `Reviewer decision: {final_decision|________}   Override: {Yes|No|____}   Reason: {exception_reason|____________________}   Initials / date: {initials} {date}|__________`.
  Values come from the decision log when present, and blanks otherwise.
- A small italic muted label, right-aligned in the heading row: `AI-assisted screening — verify against source`.

### 4.8 Evidence basis line (5.6pt muted)

```
Evidence basis: {FACT count} facts · {INFERENCE count} inferences · {NOT PROVIDED count} items not provided ·
{scored} of {factors} factors scored · {unverified} criteria unverified · {deal_breakers} deal-breakers /
{concerns} concerns · {bias} bias flags · slide refs S# · Criteria Pack v{version} #{hash8} ·
engine: Claude ({model}). {DISCLAIMER}
```

### 4.9 Page footer (house standard, per the parent CLAUDE.md)

`Investor Screening Scorecard          {page}          Compiled on {Month} {D}, {YYYY} by TEN Capital Network    [logo]`

The footer is Open Sans 7pt, muted, and horizontally centered as a unit (text + logo). The logo is
`TEN_Capital_logo_footer.png` at 48 × 18pt, aspect ratio preserved, drawn only if the file
exists.

### 4.10 Blank template variant (`icb criteria template`)

The same renderer, the same blocks, with no deck. It is populated from the Criteria Pack alone:

| Block | Blank rendering |
|---|---|
| Header | Company name `Company name`. Meta line 1 is ruled blanks. Meta line 2 is filled from the pack. Tiles show `__ /5` and `__ /100` |
| Snapshot | Labels with ruled blank values |
| Factor strip | Pack short labels, with `__/5 · {weight}%` |
| Hard criteria | `**{label}:** {requirement}  [ ] MET  [ ] NOT MET  [ ] UNVERIFIED` |
| Factor evidence | `**{label} __/5:**` + ruled blank, with the floor noted when set |
| Table | Three empty rows |
| Gaps / requests | Five numbered ruled blanks |
| Decision panel | `[ ] ADVANCE  [ ] PASS  [ ] HOLD — REQUEST EVIDENCE`, the advance threshold, and the reviewer line |

---

## 5. Data contract

**Snapshot field.** Every company-snapshot value uses this wrapper:

| Key | Meaning |
|---|---|
| `value` | Display string, or `null`. `null` renders as `Not provided`. |
| `classification` | `FACT` \| `INFERENCE` \| `NOT PROVIDED` |
| `confidence` | 0.0–1.0 (0.9–1.0 stated verbatim; 0.6–0.89 stated but ambiguous; 0.3–0.59 inferred; below 0.3 → null) |
| `slides` | 1-based slide numbers, deduplicated, sorted, and within the deck's page range |
| `excerpt` | Verbatim supporting text, ≤ 25 words |

**Company snapshot:** `name`, `sector`, `subsector`, `stage`, `geography`, `revenue`,
`key_traction`, `raise_amount`, `instrument`, `valuation`, `valuation_basis`,
`amount_committed`, `lead_investor`. Currency fields also carry `amount_usd: int | null`.
Normalization follows the deckpager rules.

**Hard criterion result:** `{criterion_id, label, requirement, result, deck_evidence,
classification, slides[], excerpt}`. `label` and `requirement` are copied from the pack.

**Factor result:** `{factor_id, label, short_label, weight, floor, score: 1–5 | null,
rubric_level_matched, evidence_summary, evidence[] {quote, slide, evidence_type},
evidence_standard_met, gap}`. `label`, `short_label`, `weight`, and `floor` are copied from the
pack. `score` is null whenever `evidence_standard_met` is false.

**Triggered deal-breaker:** `{deal_breaker_id, issue, walk_away_condition, classification,
excerpt, slides[], resolution}`. `walk_away_condition` is copied from the pack.

**Concern:** `{factor_id, severity: HIGH | MEDIUM | LOW, issue, consequence, resolution,
classification, excerpt, slides[]}`.

**Bias flag:** `{type, signal, slides[], affected_factor_id | null}`.

**Evidence request:** `{priority, request, audience, reason, linked_to: criterion_id |
factor_id | concern}`.

**Narrative (model):** `screening_summary` (analytical; must not state a decision),
`thesis_fit` (≤ 160 chars).

**Decision (code):** `{decision, rule: 1–5, rule_label, rule_sentence, weighted_score | null,
advance_threshold, evidence_coverage, unscored_weight_pct, max_unscored_weight_pct,
floor_breaches[], criteria_counts {met, not_met, unverified}}`.

**Review (log, optional):** `{final_decision, override, exception_reason, reviewer_initials,
decided_at}`.

**Provenance:** `source {filename, slide_count, parse_warnings[]}`, `engine {model, effort}`,
`criteria_pack {investor_name, version, hash}`, `generated_at`, `schema_version`,
`truncations[]` (every density step and every shortened field), `warnings[]`.

**Grounding rules:**
- A `FACT` carries at least one slide and a verbatim excerpt.
- Anything the deck does not state is `NOT PROVIDED`. It is never filled with a plausible value.
- Absence of evidence yields `UNVERIFIED` or `Unscored`, never a low score.

---

## 6. Derived values (computed in code, never by the model)

| Value | Rule |
|---|---|
| `weighted_score` | `Σ(score × weight) / Σ(weight of scored factors)`, shown to 1 decimal. `null` if nothing is scored. |
| `unscored_weight_pct` | `Σ(weight of unscored factors)` (weights are integers summing to 100) |
| `evidence_coverage` | `100 − unscored_weight_pct` |
| `floor_breaches` | Scored factors with `score < floor` |
| `ownership_at_check` | Post-money = `valuation` if basis is post-money; `valuation + raise_amount` if pre-money. Rendered as `{check_min / post:.1%}–{check_max / post:.1%}`. `Not provided` if the valuation or its basis is not stated. |
| `criteria_counts` | Count of hard-criterion results by value |

**Decision rules.** Apply in order; the first match wins.

| Rule | Condition | Decision | `rule_label` |
|---|---|---|---|
| 1 | Any deal-breaker triggered | `PASS` | `Deal-breaker triggered` |
| 2 | Any hard criterion `NOT MET` | `PASS` | `Hard criterion not met` |
| 3 | Any hard criterion `UNVERIFIED`, or `unscored_weight_pct > max_unscored_weight_pct` | `HOLD — REQUEST EVIDENCE` | `Evidence insufficient` |
| 4 | `weighted_score ≥ advance_threshold` and no floor breaches | `ADVANCE` | `Meets threshold and floors` |
| 5 | Otherwise | `PASS` | `Below threshold or floor` |

`rule_sentence` is assembled from the rule and its inputs. Examples:
- `Rule 3: 2 hard criteria unverified.`
- `Rule 4: weighted score 3.8 meets the 3.5 threshold with no floor breaches.`

---

## 7. Vocabularies

| Vocabulary | Values |
|---|---|
| Classification | `FACT`, `INFERENCE`, `NOT PROVIDED` |
| Hard-criterion result | `MET`, `NOT MET`, `UNVERIFIED` (display-only: `NOT APPLIED`) |
| Decision | `ADVANCE`, `PASS`, `HOLD — REQUEST EVIDENCE` |
| Severity | `DEAL-BREAKER`, `HIGH`, `MEDIUM`, `LOW` |
| Factor state | `SCORED`, `UNSCORED` |
| Bias type | `Momentum`, `Social proof`, `Overconfidence` |
| Evidence type | `deck_statement`, `financials`, `cap_table`, `customer_reference`, `third_party_data`, `legal_doc` |
| Request audience | `Founder`, `Investor`, `Legal counsel`, `Financial advisor`, `Technical advisor` |
| Valuation basis | `pre-money`, `post-money`, `not stated` |

Never write "pass/fail" anywhere on the page: "PASS" means *decline*.

---

## 8. Density ladder

The renderer measures the layout at level 0 and steps down until it fits within the frame
(4pt tolerance). If level 5 still overflows, the content is shrunk as a whole to fit. If that
still yields more than one page, the renderer raises `OnePageError`. Every step taken is
recorded in `provenance.truncations`.

| Level | Body pt | Small pt | Criteria | Factor | Concerns | Issue | Evidence | Impact | Resolution | Request | Bias flags | Bias | Rationale | Thesis fit | Not-applied line | Gap pt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 7.3 | 6.1 | 150 | 140 | 4 | 110 | 130 | 150 | 110 | 180 | 4 | 80 | 420 | 160 | ✓ | 6.0 |
| 1 | 7.1 | 6.0 | 130 | 120 | 4 | 100 | 100 | 130 | 90 | 165 | 4 | 70 | 390 | 160 | ✓ | 5.5 |
| 2 | 6.9 | 5.9 | 110 | 100 | 3 | 95 | 80 | 115 | 70 | 150 | 3 | 65 | 360 | 140 | ✓ | 5.0 |
| 3 | 6.7 | 5.8 | 95 | 85 | 3 | 90 | 60 | 100 | 0 | 135 | 3 | 60 | 320 | 120 | — | 4.5 |
| 4 | 6.5 | 5.6 | 80 | 72 | 2 | 85 | 45 | 90 | 0 | 120 | 2 | 55 | 290 | 110 | — | 4.0 |
| 5 | 6.3 | 5.5 | 65 | 60 | 2 | 80 | 0 | 80 | 0 | 110 | 2 | 50 | 260 | 100 | — | 3.5 |

Numeric columns other than point sizes are character limits or item counts. Truncation
always ends with an ellipsis. The `Concerns` cap never applies to deal-breakers.

---

## 9. Fixed strings

| String | Where |
|---|---|
| `Investor Screening Scorecard` | Document title: header eyebrow (uppercased), PDF metadata title, first footer cell |
| `WEIGHTED SCORE · ADVANCE AT {t}` · `EVIDENCE COVERAGE` | Header tile labels |
| `Screened for {investor_name}  ·  Criteria Pack v{N}  ·  #{hash8}` | Header meta line 2 |
| `COMPANY SNAPSHOT` · `HARD CRITERIA` · `FACTOR EVIDENCE` · `DEAL-BREAKERS & CONCERNS` · `EVIDENCE GAPS & BIAS FLAGS` · `EVIDENCE TO REQUEST` · `SCREENING DECISION` | Section headings |
| `SEVERITY` · `ISSUE & EVIDENCE` · `IMPACT ON SCREEN & RESOLUTION` | Table header |
| `Walk-away condition:` · `Lowers {factor}.` · `Resolve:` | Table impact cell |
| `DECISION` · `HARD CRITERIA` · `RULE APPLIED` | Decision chips |
| `Thesis fit:` | Decision panel |
| `Reviewer decision:` · `Override:` · `Reason:` · `Initials / date:` | Reviewer line |
| `AI-assisted screening — verify against source` | Decision panel label |
| `Not provided` | Empty snapshot cell |
| `NOT PROVIDED` · `UNVERIFIED` · `Unscored` | Inline markers (bold orange) |
| `(inferred)` · `(computed)` | Snapshot value suffixes |
| `unscored` · `below floor` | Factor strip notes |
| `Not applied:` | Hard-criteria column, last line |
| `No deal-breakers triggered and no concerns identified from deck evidence.` | Empty table |
| `No bias signals flagged.` | Empty bias list |
| `Unnamed company` | Missing company name |
| `Compiled on {date} by TEN Capital Network` | Page footer |
| `{DISCLAIMER}` = `AI-assisted screening against the investor's approved criteria; not investment, legal, or tax advice. Verify all findings against source documents.` | End of the evidence basis line |

---

## 10. Palette

All colors live in `src/icb/render/theme.py`; nothing else hard-codes a color.

| Token | Hex | Use |
|---|---|---|
| `NAVY` | `#1B2A4A` | Header band, section headings, labels |
| `NAVY_LIGHT` | `#26395F` | Score tiles |
| `ORANGE` | `#E85D26` | Accent rules, eyebrow, request numbers, inline markers |
| `LIGHT_BLUE` | `#C8D6E8` | Header meta and tile labels |
| `BACKGROUND` | `#F7F9FC` | Snapshot grid, alternate table rows |
| `TINT` | `#EEF3F9` | Decision panel |
| `INK` | `#1F2733` | Body text |
| `MUTED` | `#5B6573` | Labels, secondary text, footer |
| `RULE` | `#D5DDE8` | Hairlines |

| Scale | Colors |
|---|---|
| Score 5 → 1 | `#1F7A4D` · `#3F8A3A` · `#A86B12` · `#D9531E` · `#B42318` (unscored `#8A94A3`) |
| Severity DEAL-BREAKER · HIGH · MEDIUM · LOW | `#B42318` · `#E85D26` · `#A86B12` · `#5B7083` |
| Result MET · UNVERIFIED · NOT MET · NOT APPLIED | `#1F7A4D` · `#A86B12` · `#B42318` · `#5B6573` |
| Decision ADVANCE · HOLD — REQUEST EVIDENCE · PASS | `#1F7A4D` · `#A86B12` · `#B42318` |

---

## 11. Text safety

- Every model-supplied string is XML-escaped before it reaches a reportlab `Paragraph`.
- Glyphs missing from Open Sans are substituted (e.g. `≠` → `!=`, `→` → `->`). With the
  fallback fonts, text is additionally reduced to cp1252.
- Company names, excerpts, evidence, and requests are always truncated to their limits,
  never wrapped past them.
