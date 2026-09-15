# Build Spec — Investor Criteria Builder + Deck Screening One-Pager (Python)

The parent `Claude Cowork folder\CLAUDE.md` also applies. Its **TEN Capital Footer** and
**Logo Asset** sections are binding for every PDF this app produces.

## 1. Role

You are a senior Python engineer and a venture investment strategist, building a production
tool for TEN Capital. You write typed, tested, dependency-light code. You do not invent
business logic or investor preferences that are not in this spec or in the investor's own
inputs. When the spec is ambiguous, stop and ask one specific question before proceeding.

## 2. Objective

Build `icb` (Investor Criteria Builder), a Python CLI with two jobs:

1. **Define the standard (once per investor, revised on a schedule).** Collect an investor's
   profile, then produce a versioned **Criteria Pack**: written thesis, hard criteria,
   weighted scoring rubric, deal-breakers, evidence standard, consistency controls, a
   screening scorecard template, and a review cadence. The investor must approve the pack
   before it can be used.
2. **Apply the standard (once per deal).** Ingest a pitch deck (.pdf, .pptx, .ppt, .docx), screen
   it against an approved Criteria Pack, and render a **one-page Screening Scorecard PDF**.

Both jobs run through two front ends that share one core:
- the `icb` CLI
- a public web app deployed on Railway, with no sign-in (§15)

The Claude API performs the analysis, using the operator's Anthropic Console API key. The
key is held server-side only. Every generated result is emailed to TEN Capital via Resend
(§16).

**The product is the one-page scorecard.** Success means a partner can drop in any real
founder deck and get back one page that shows:
- whether the deal meets the investor's own written standard
- the evidence (with slide numbers) behind every score
- what is missing
- the reason for the decision

Two different decks screened against the same pack must be directly comparable.

## 3. Non-negotiables

- **Never invent investor preferences.** Every criterion, weight, threshold, and filter in a
  Criteria Pack must trace to a profile input or be explicitly approved by the investor. A
  value the model cannot ground is marked `needs_input` with a specific question, and it
  blocks approval. Code enforces this; prompt wording alone is not enough.
- **"Not provided" is different from "no preference."** Every profile field records one of
  `provided`, `no_preference` (the criterion is deliberately not applied), or
  `not_provided` (blocks the build). Never default a `not_provided` field.
- **Never invent deal facts.** A deck fact the model cannot ground is null and renders as `Not provided`.
  Every score and hard-criterion result cites 1-based source slides; code rejects citations
  outside the deck's page range.
- **Absence of evidence is not a low score.** If the evidence standard for a factor is not
  met, the factor is `unscored`, not scored 1. Unscored factors are listed as evidence gaps.
- **Decisions are computed in code, not by the model.** The model extracts evidence and
  proposes rubric scores. `decision.py` applies the pack's rules (§9) as a pure function.
- **One page, always.** Overflow is resolved by a reduction ladder, never by a second page.
  This is a test-enforced invariant (§12).
- **Approved packs are immutable.** Each has a SHA-256 hash of its canonical JSON. Every
  scorecard and log entry stamps the pack version and hash.
- **Data egress:** exactly two destinations:
  - the Anthropic API, for analysis
  - Resend, for result emails to the configured `ICB_REPORT_EMAIL_TO` (§16)

  No telemetry and no other recipients. Investor profiles, packs, and decision logs are
  confidential: the `investors/` directory is gitignored, except `investors/example/`.
- Secrets come from the environment or `.env` only (on Railway, the service Variables).
  Never log, print, or return an API key (Anthropic or Resend); never accept one from the browser; never log
  full deck text.
- Professional, analytical language in all generated text. No promotional tone.

## 4. Tech stack

Reuse before rebuilding. These sibling projects already solve parts of this problem:

| Concern | Use | Reuse from |
|---|---|---|
| CLI | typer + rich | `../deckpager/src/deckpager/cli.py` patterns |
| Deck ingest (.pdf/.pptx/.ppt) | pymupdf, pdfplumber, python-pptx, LibreOffice headless | `../deckpager/src/deckpager/ingest/` (native PDF `document` blocks as the primary path, rasterization as the fallback) |
| Thesis-notes ingest (.pdf/.docx/.md/.txt) | same + python-docx | `../deckpager/src/deckpager/ingest/docx.py` |
| Extraction cache | content-hash JSON cache | `../deckpager/src/deckpager/cache.py` |
| LLM | `anthropic` official SDK | `../ConvictionLadder/engine.py` |
| Schemas | pydantic v2, pydantic-settings | — |
| Profile file | PyYAML (human-editable) | — |
| PDF render | **reportlab** (no GTK on this machine; do not use WeasyPrint) | Layout, density ladder, footer: `../TechDiligenceIPRisk/app/reporting/pdf_generator.py` + `templates.py` (the format `templates/one_pager.md` replicates) |
| Fonts | Open Sans TTF (Regular/SemiBold/Bold/Italic) | copy from `../BoardReadinessAdvisor/board_readiness/assets/fonts/` |
| Logo | `TEN_Capital_logo_footer.png` | copy from `../TEN_Capital_logo_footer.png` into `assets/` |
| Web app | fastapi, uvicorn[standard], python-multipart | `../ConvictionLadder/web.py` + `index.html` (job API, polling UI), `../deckpager/app.py` |
| Deployment | Railway, Railpack builder | `../deckpager/railway.json`, `Procfile`, pinned `requirements.txt` |
| Email | Resend REST API via stdlib `urllib` (no SDK) | `../deckpager/src/deckpager/mailer.py`, `../ConvictionLadder/mailer.py` |
| Tests | pytest, pytest-cov, pypdf, httpx (FastAPI TestClient) | — |

Read those files before writing the equivalent module. Copy and adapt them; don't import
across projects. Pin versions in `requirements.txt` to match `../deckpager/requirements.txt`.
Ask before adding any dependency not listed here.

**Model conventions** (load the `claude-api` skill before writing `llm/client.py`):
- Default model: `claude-opus-5`, overridable with `--model` or `ICB_MODEL`. Stream the
  response, use adaptive thinking, and set `output_config.effort` (default `high`).
- Do not send `temperature`, `top_p`, or `thinking.budget_tokens`. This model rejects them.
- Use structured outputs via `output_config.format`, with a JSON schema generated from the
  pydantic models. Never regex JSON out of prose. Check the skill for which JSON-schema
  keywords structured outputs support. Enforce the rest (e.g. weights summing to 100) in
  pydantic validators.
- `icb check` and `GET /healthz?deep=1` verify the key with `client.models.list()`, which
  costs no tokens. Report only whether the key is set and valid, never its value.
- Retry 429/5xx with exponential backoff (max 4 attempts). On a validation error, retry once
  with the error appended as a correction turn, then fail loudly.

## 5. Repository layout

```
InvestorCriteriaThesisBuilder/
├── CLAUDE.md  README.md  DECISIONS.md  pyproject.toml  requirements.txt  .env.example
├── app.py                      # FastAPI entry point (Railway start command: app:app)
├── railway.json  Procfile  .python-version
├── web/                        # index.html (the whole UI; working prototype exists), public/ (favicon set, site.webmanifest, fonts)
├── assets/                     # fonts/, TEN_Capital_logo_footer.png
├── templates/one_pager.md       # scorecard document contract (§9) — binding
├── investors/example/          # profile.yaml + approved pack + sample deck JSON (fixtures)
├── src/icb/
│   ├── cli.py  config.py  errors.py  cache.py
│   ├── pipeline.py             # shared core (build, approve, screen, decide, render); CLI and web both call it
│   ├── profile/   models.py  intake.py  validate.py      # §6
│   ├── criteria/  models.py  build.py  approve.py  revise.py  prompts.py   # §7
│   ├── ingest/    router.py  pdf.py  pptx.py  legacy_ppt.py  notes.py
│   ├── screen/    models.py  extract.py  prompts.py  decision.py  log.py    # §8–§10
│   ├── review/    stats.py  report.py                    # §11
│   ├── llm/       client.py
│   ├── mail/      mailer.py  content.py                 # §16
│   └── render/    theme.py  footer.py  scorecard.py  criteria_pack.py  review.py
└── tests/
```

Per-investor working data, all confidential:

```
investors/<slug>/
├── profile.yaml
├── criteria/v1.draft.json  v1.approved.json  v1.pdf  CHANGELOG.md
├── decisions.jsonl             # append-only screening log
├── outcomes.csv                # investor-maintained portfolio outcomes
└── scorecards/<Company>-<date>-scorecard.pdf (+ .json)
```

## 6. Investor profile: ask, never assume

`icb profile init <slug>` runs an interactive intake (rich prompts) and writes `profile.yaml`.
`icb profile validate <slug>` lists every `not_provided` field as a named question and exits 5.

**Tier 1: required before any criteria build.**

| Field | Shape |
|---|---|
| `investor_type` | `angel` \| `family_office` \| `fund` \| `corporate` |
| `capital_available_usd` | int |
| `check_size` | `{min_usd, max_usd}` |
| `return_objective` | text, plus an optional target multiple / IRR stated by the investor |
| `liquidity_objective` | text (e.g. need for distributions, secondary appetite) |
| `time_horizon_years` | int or range |
| `prior_investments` | list of `{company, year, stage, sector, check_usd, outcome: active\|exited\|written_off\|unknown, multiple?, lesson?}`. An empty list must be explicitly affirmed as "no prior investments". |
| `thesis_notes` | free text and/or file paths; may be `no_preference` ("none yet") |

**Tier 2: hard-criteria parameters.** The original intake does not ask for these, but §7
needs them. For each one: if the thesis notes state it explicitly, pre-fill it with a quote
and source, then have the investor confirm it. Otherwise ask.

`stages`, `sectors` (with subsectors), `geographies`, `round_size {min_usd, max_usd}`,
`ownership_target_pct`, `instruments_accepted`, `minimum_traction` (metric + threshold),
`instant_no_filters` (list), `follow_on_reserve_policy`.

Every field is stored as `{status, value, source}`, where `source` is `intake` or
`thesis_notes:<file>#<quote>`. Non-interactive runs (`--no-input`) never prompt. They print the
questions and exit 5.

## 7. Criteria Pack

`icb criteria build <slug>` runs profile validation (no API call if it fails), ingests the
thesis notes, makes one structured-output call, and writes `vN.draft.json` + `vN.pdf`.

**Data model** (`criteria/models.py`). Every generated element carries `grounded_in: list[str]`
(the profile field paths it derives from) or `needs_input: str` (a specific question).

1. **Investment Thesis** (`thesis.text`, 150–250 words, validated by word count), covering:
   what the investor believes, where the opportunity is mispriced, the investor's edge, and
   why now. The edge must come from `prior_investments`, `thesis_notes`, or `investor_type`.
   If none of these supports one, set `needs_input` rather than writing a generic edge.
2. **Hard Criteria**: a list of `{criterion_id, label, requirement, test, evidence_required}` covering
   stage, sector/subsector, geography, check size, round size, ownership target, instrument,
   minimum traction/revenue, and instant-no filters. A `no_preference` field produces no
   criterion and is listed as "not applied".
3. **Weighted Scoring Criteria**: 6–10 factors drawn from team, market, traction, unit
   economics, defensibility, valuation, exit path, and strategic fit. Each factor has:
   - `label`, and `short_label` (≤ 12 chars, shown in the scorecard's factor strip)
   - `weight`: integer; all weights sum to 100
   - `weight_rationale`: tied to a profile input
   - `rubric`: exactly 5 levels, each describing *observable evidence* (not adjectives)
   - `floor`: optional minimum score for that factor

   The pack also sets `advance_threshold` (weighted 1.0–5.0) and `max_unscored_weight_pct`.
   Weights and thresholds are *proposals* and are shown to the investor as such at approval.
4. **Deal-Breakers vs. Score-Lowering Concerns**: two separate lists. A deal-breaker
   (`{deal_breaker_id, walk_away_condition, trigger}`) is a walk-away condition with an
   observable trigger. A concern names the factor it lowers.
5. **Evidence Standard**: for each hard criterion and factor, the acceptable evidence types
   (`deck_statement`, `financials`, `cap_table`, `customer_reference`, `third_party_data`,
   `legal_doc`, …) and the minimum needed before a score may be assigned.
6. **Consistency Controls**: rationale-recording rules, bias checks (momentum, social proof,
   overconfidence) stated as observable tests, and an exception/override procedure. §10
   implements these; the pack states them in the investor's terms.
7. **Screening Scorecard Template**: rendered as a blank version of the §9 one-pager by the
   same renderer (`icb criteria template <slug>`; `templates/one_pager.md` §4.10).
8. **Review Cadence**: review triggers (calendar interval and/or N screened deals), the
   minimum sample size before changing a weight, which outcome data is reviewed, and how
   changes are versioned.

Also: `open_questions: list[str]`, `not_applied: list[str]`, `version`, `created_at`, `model`.

**Approval.** `icb criteria approve <slug>` refuses (exit 6) while any `needs_input` or
`open_questions` remain. Otherwise it prints a summary table (weights, thresholds,
deal-breakers), requires explicit confirmation, freezes `vN.approved.json`, and records the
hash. Investors edit drafts by hand; `icb criteria validate` re-checks the edited file.

**Builder system prompt** (`criteria/prompts.py`). Use verbatim; tune only if tests demand it:

> You are a venture investment strategist helping an investor define the explicit criteria
> and written thesis that every incoming deal will be screened against. You are given the
> investor's profile and any thesis materials they supplied.
>
> Rules:
> - Do not invent the investor's preferences. Every criterion, weight, threshold, and filter
>   must be derived from a specific profile field or thesis-note passage; record those
>   field paths in `grounded_in`.
> - Where a required input is missing, ambiguous, or contradictory (for example, a check
>   size that cannot reach the ownership target at the stated round sizes), do not resolve it
>   yourself. Set `needs_input` to one specific question the investor can answer, and add it
>   to `open_questions`.
> - Fields marked `no_preference` produce no criterion. List them in `not_applied`.
> - Rubric levels must describe observable evidence a reviewer could verify in documents,
>   not qualitative adjectives. Level 1 and level 5 must be clearly distinguishable by
>   evidence alone.
> - Separate deal-breakers (walk away regardless of other scores) from concerns (lower a
>   named factor's score). Do not put the same condition in both.
> - The thesis must state what the investor believes, where the opportunity is mispriced, why
>   this investor has an edge, and why now, in 150–250 words. Base the edge only on the
>   investor's actual record and resources. If none is evident, ask.
> - Weights and thresholds are proposals for the investor to approve. Give each a one-line
>   rationale tied to their stated return, liquidity, and time-horizon objectives.
> - Write in professional, analytical language with no promotional tone.

## 8. Deck screening

`icb screen <slug> DECK [--pack vN]` uses the latest approved pack by default. If none exists,
it exits 6.

**Ingest.** Use the deckpager contract unchanged: PDF as a native `document` block;
PPTX/PPT converted via LibreOffice; DOCX via `../deckpager/src/deckpager/ingest/docx.py`, citing
section numbers where a deck would cite slides; image-dominant slide handling and slide caps as deckpager
implements them.

**Extraction.** One structured-output call. The pack is sent as the criteria; the deck is the
only source of facts. The model returns a `Screening`, whose fields are defined in the data
contract (§5) of `templates/one_pager.md`:
- the company snapshot, as `{value, classification, confidence, slides, excerpt}` fields
- one hard-criterion result per pack criterion (`MET` / `NOT MET` / `UNVERIFIED`)
- one factor result per pack factor, with `score: 1–5 | null` and verbatim evidence quotes
- triggered deal-breakers, concerns (with severity and resolution), and bias flags
- evidence requests, each with an audience
- `screening_summary` and `thesis_fit`

Code fills in the fields the template marks as copied from the pack (labels, weights, floors,
walk-away conditions) after the call; the model does not supply them. The model never
returns a decision.

**Screening system prompt** (`screen/prompts.py`). Use verbatim:

> You are screening a startup pitch deck against an investor's approved Criteria Pack. The
> pack is the only standard; the deck is the only source of facts.
>
> Rules:
> - Extract only what the deck states. Never guess a number, name, valuation, or metric.
>   Every result cites 1-based slide numbers.
> - For each factor, match the deck's evidence to the rubric level whose observable-evidence
>   description it satisfies. If the pack's evidence standard for that factor is not met by
>   the deck, set `score` to null and `evidence_standard_met` to false, and state
>   the gap. Do not score a factor low because evidence is absent.
> - A hard criterion is MET or NOT MET only when the deck states the relevant fact.
>   Otherwise it is UNVERIFIED.
> - Founder assertions, projections, and "oversubscribed", deadline, or named-investor
>   signals are not evidence of quality. Record them in `bias_flags`. They may not raise a
>   score unless the pack's evidence standard explicitly accepts them.
> - Record a deal-breaker only when its trigger is observably present in the deck.
> - Do not recommend advance or pass. That decision is computed from your structured
>   results.

Cache key: deck content hash + pack hash + model + prompt version + schema hash. A re-screen
of the same deck against the same pack must be free and identical.

## 9. The one-page scorecard

**`templates/one_pager.md` is the binding document contract.** `tests/test_template.py`
enforces its block order, fields, vocabularies, fixed strings, palette, and density ladder.
If this section and the template disagree, the template wins. Propose a change to the
template rather than working around it.

The template reuses the format of TEN Capital's one-page diligence report:
- a header band with score tiles
- a snapshot grid and a score strip
- a two-column assessment
- a severity table
- a two-column gaps and requests block
- a conclusion panel, an evidence-basis line, and the house footer

Those blocks are filled with the screening fields from §8.

**`screen/decision.py`** is a pure function `(Screening, CriteriaPack) -> Decision`. It
implements the decision rules in §6 of the template exactly. Apply them in order; the first
match wins:

1. Any deal-breaker triggered → **PASS**
2. Any hard criterion NOT MET → **PASS**
3. Any hard criterion UNVERIFIED, or unscored weight > `max_unscored_weight_pct` →
   **HOLD — REQUEST EVIDENCE**
4. Weighted score ≥ `advance_threshold` and no floor breaches → **ADVANCE**
5. Otherwise → **PASS**

It also computes every other derived value in §6 of the template: weighted score, evidence
coverage, ownership at check, criteria counts, and the rule sentence. Use these words
exactly: MET / NOT MET / UNVERIFIED for criteria, and ADVANCE / PASS / HOLD — REQUEST
EVIDENCE for decisions. Never write "pass/fail", because "pass" means *decline* in this
domain.

**Rendering rules outside the template:**
- Build the renderer by adapting the TechDiligenceIPRisk generator (§4). Measure the story at
  each density level before rendering, and never accept a second page.
- Colors, font paths, and the logo path live only in `render/theme.py`.
- Every model string is escaped and glyph-substituted (§11 of the template). Reconfigure
  stdout/stderr to UTF-8 so Windows consoles don't crash after the PDF has been written.
- The blank template (`icb criteria template`) uses the same renderer (§4.10 of the
  template).

## 10. Consistency controls (implemented, not just described)

- **Decision log.** Every `icb screen` appends to `decisions.jsonl`: timestamp, deck hash,
  company, pack version + hash, model, every score and result, rule fired, decision, bias
  flags, evidence gaps. The log is append-only; code never rewrites past lines.
- **Rationale required.** `icb decide <slug> <company> --final ADVANCE|PASS|HOLD --rationale "…"`
  records the human decision. If it differs from the computed decision, it is an
  **override** and requires `--exception-reason` naming the specific evidence that justifies
  it. The scorecard can be re-rendered to show it (`icb redraw`).
- **Same standard, every deal.** A screen always runs against a frozen, hashed pack. Packs are
  never modified during a screening. `icb batch` screens a directory against one pack
  version.
- **Bias surfacing.** The review report (§11) shows override rate, overrides by direction,
  and how often advanced deals carried social-proof or momentum flags.

## 11. Review cadence (drift-resistant)

- `icb review <slug>` reads `decisions.jsonl` + `outcomes.csv` and renders a review PDF
  (multi-page is fine), with the same footer. Contents: decisions by outcome; score
  distributions per factor; HOLD rate and the most common evidence gaps; override rate and
  outcomes of overridden deals; factors whose scores did not separate good from bad outcomes.
  All statistics are computed in code. An optional model narrative must cite the computed
  numbers only.
- The report is flagged **below minimum sample** if the pack's minimum sample size is not
  met, and no weight changes are proposed in that case.
- `icb criteria revise <slug>` creates `v(N+1).draft.json` from the latest approved pack. It
  requires a `CHANGELOG.md` entry citing the review that motivated each change. If run
  outside the pack's review trigger, it requires `--exception-reason`, so criteria cannot
  drift deal by deal. The new version goes through the same approval gate.

## 12. Errors, exit codes, tests

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | bad input / unsupported file |
| 2 | extraction failed |
| 3 | render failed |
| 4 | config / environment |
| 5 | investor input missing (blocked) |
| 6 | no approved criteria pack |

Every user-caused failure prints one actionable sentence, with tracebacks only under `-v`.
Explicitly cover: encrypted PDF, scanned/no-text PDF, corrupt file, missing `soffice` for
.ppt, missing API key, schema-invalid output twice, non-pitch-deck document, and non-English
deck (proceed and note it in the evidence gaps).

**Tests.** Write these alongside the code. Mock the Anthropic client everywhere except one
opt-in live test.

- `test_profile`: `not_provided` never defaults. `no_preference` produces no criterion. An
  empty `prior_investments` without affirmation blocks the build. `--no-input` exits 5 and
  lists the questions.
- `test_criteria`: weights must sum to 100; 6–10 factors; exactly 5 rubric levels; thesis
  150–250 words; approval refuses while `needs_input` remains; the hash is stable across
  key ordering; an approved file is never overwritten.
- `test_decision`: a table-driven test of every rule in §9, including ties at the threshold,
  a floor breach with a high average, all factors unscored, and rule precedence. **This is
  the most important test file.**
- `test_screen`: out-of-range slide citations are rejected; a null score with
  `evidence_standard_met=false` is excluded from the weighted average; a cache hit makes no
  API call.
- `test_render`: **exactly one page for a worst-case Screening** (every field at maximum
  length). Measure layout geometry, not just pypdf page count, because reportlab paints past
  the bottom edge without adding a page. Also check: the footer text and logo are present;
  nulls render as `Not provided`; the blank template renders. Deal-breakers, hard-criterion
  results, factor cells, and the decision panel all survive density level 5.
- `test_template`: the block order, vocabularies, fixed strings, palette tokens, and density
  ladder in `templates/one_pager.md` match the code (parse its Markdown tables).
- `test_log`: append-only; overrides require an exception reason.
- `test_cli`: each exit code.
- `test_web`: see §15.
- `test_mailer`: see §16.
- Coverage ≥ 80% on `src/icb/`.

## 13. Build order: stop for review after each phase

- **Phase 0 — Scaffold.** pyproject, package skeleton, `icb check` (API key set, soffice,
  fonts, logo), empty test suite passing. Copy fonts and logo into `assets/`. Run
  `git init` in this folder so the project has its own repository (the enclosing repository
  is the user's home directory). Confirm `git check-ignore .env` before the first commit.
- **Phase 1 — Profile.** Models, intake, validation, `investors/example/profile.yaml`. No LLM.
- **Phase 2 — Criteria Pack.** Models + validators + hashing + approval gate, tested against
  a hand-written example pack. Then the builder call: run it once live on the example profile
  and **show me the raw draft JSON** before rendering anything.
- **Phase 3 — Decision engine.** `decision.py` + its full test table. No LLM, no rendering.
- **Phase 4 — Scorecard layout.** Implement `templates/one_pager.md` against a hardcoded
  sample `Screening` and add `test_template`. Iterate visually until it's right, including
  the worst-case one-page test and the blank template.
- **Phase 5 — Screening.** Reuse deckpager ingest, add the extraction call, run live on one
  real deck from the parent folder, and show me the JSON. Then wire extract → decide →
  render → log.
- **Phase 6 — Consistency and review.** `decide`, `redraw`, `batch`, `review`,
  `criteria revise`. Also the Criteria Pack PDF.
- **Phase 6b — Result emails.** Build `mail/` and `test_mailer` per §16, and wire them into
  the CLI. Send the first real email only after I approve it.
- **Phase 7 — Web app.** Build `app.py` and the job API. Wire the existing `web/index.html`
  prototype to them, then add auth, persistence checks, and `test_web`, per §15. Run it locally with `uvicorn app:app --reload` against the
  real API, and screen one real deck end to end through the browser.
- **Phase 8 — Railway deployment.** Follow the §15 runbook. Ask before every command that
  creates a project, sets variables, or deploys.

At each phase boundary: run the tests, show the diff summary in ≤ 5 lines, report anything
that departs from this spec, and wait.

## 14. Working style

- Small commits, conventional-commit messages, one concern per commit.
- Show a plan before editing more than 3 files at once.
- If a test fails, fix the code. Never weaken an assertion, especially the one-page, decision
  rule, and no-default-preference tests.
- When this spec conflicts with reality (a library behaves differently, a layout won't fit, a
  schema keyword isn't supported), say so and propose the tradeoff. Record the agreed outcome
  in `DECISIONS.md`. Do not silently work around it.

## 15. Web app and Railway deployment

Follow `../ConvictionLadder/CLAUDE.md` "Web app conventions" unless this section says
otherwise.

### Architecture

- `app.py` already exists as a deployable shell. It serves:
  - the UI, with injected config
  - the icons, `/favicon.ico`, and `/healthz`

  Every `/api/*` route answers 503 until Phase 7 implements it, and
  `tests/test_app_shell.py` covers the shell. Extend this file rather than replacing it, and
  keep its health check.
- `src/icb/pipeline.py` is the only place analysis logic lives. `cli.py` and `app.py` are thin
  wrappers, so the two front ends cannot drift apart.
- `web/index.html` is the whole UI, with no frontend framework. It already exists as a
  working prototype of the operator's design. See "UI design" below.

### Screens

1. **Investors**: list, select, or create an investor (slug + display name).
2. **Profile**: a form for every §6 field.
   - Each field has a status selector: provided / no preference / not provided.
   - Thesis-notes upload (.pdf/.docx/.md/.txt).
   - "Validate" lists missing inputs as named questions; the build button stays disabled
     until none remain.
3. **Criteria Pack**:
   - "Build draft" runs as a job.
   - The draft shows thesis, hard criteria, weights with rationales, rubrics, deal-breakers,
     concerns, evidence standard, and review cadence.
   - Open questions and `needs_input` items are shown inline with answer boxes. Answering
     updates the profile and re-runs the build.
   - "Approve" stays disabled while any remain, and requires an explicit confirmation
     checkbox.
   - Downloads: pack PDF, blank scorecard template.
4. **Screen a deck**:
   - Upload a deck and pick the approved pack version (latest by default).
   - A progress view shows the stages: Reading deck → Screening against criteria → Applying
     decision rules → Rendering scorecard.
   - The result view shows the decision, the scorecard PDF inline, and PDF + JSON downloads.
   - It also shows the email status: `sent to {recipient}`, `not configured`, or
     `failed: {reason}`.
5. **Record decision**: final decision and reviewer initials. An override requires an exception
   reason (§10). The scorecard is then re-rendered with the reviewer line filled in.
6. **Review**: generate the §11 review PDF.

### UI design

`web/index.html` implements the operator-supplied design: a dark navy card, a coral → amber →
teal accent, and Sora / Inter / JetBrains Mono type. It is the starting point, not a sketch.
Keep its tokens, components, and copy tone. Wire it to the API; don't restyle it.

**The prototype already has:**
- Four view states in one card:
  - **upload**: investor select, Criteria Pack status chip, drag-and-drop dropzone,
    selected-file row, inline validation, "Email this result" checkbox
  - **progress**: four stages and an elapsed clock
  - **result**: decision, rule sentence, score / coverage / criteria stats, PDF and JSON
    downloads, inline preview, "Record decision" form with an override reason
  - **error**: one sentence and "Try again"
- Client-side validation that mirrors the server's type and size limits.
- The no-volume banner.

**Server config injection.**
- `app.py` replaces `{{CONFIG_JSON}}` with
  `{max_mb, accept[], email_enabled, email_to, data_dir_persistent, soffice_available}`.
- Serialize with `<`, `>`, and `&` escaped as `\u003c`, `\u003e`, and `\u0026`, so a value can
  never close the `<script>` tag.
- `accept` includes `.ppt` only when `soffice_available` is true.
- If the page is opened without injection, it runs in **preview mode** with sample data and a
  "Preview mode" tag. Served pages must never reach preview mode.

**Data the UI reads.**
- `job.stage` is one of `reading`, `screening`, `deciding`, `rendering`.
- `job.result` is `{company, investor_name, source_filename, decision, rule_sentence,
  weighted_score, advance_threshold, evidence_coverage, criteria_counts {met, unverified,
  not_met}, pack {version, hash}}`.
- `job.email` is `{status: sent | skipped | not_configured | failed, recipient, reason}`.
- All text is set with `textContent`. Never insert server or model text as HTML.

**Rules carried over from the design review.**
- **Recipient.** The recipient shown on the page comes only from the injected `email_to`. The
  original mockup hardcoded a personal address; no address may be hardcoded in the HTML.
- **Fonts.** Self-host Sora, Inter, and JetBrains Mono (OFL) under `web/public/fonts` and
  remove the Google Fonts `<link>`s, so the browser makes no third-party requests.
- **Icons.**
  - `web/public/` holds the favicon set generated from `ten-capital-icon.png` (the TEN
    Capital mark): `favicon.ico` (16/32/48), 16 and 32 PNGs, `apple-touch-icon.png` (180, on
    navy), `icon-192.png`, `icon-512.png`, `icon-512-maskable.png`, and `site.webmanifest`.
  - `index.html` references them with relative `public/...` paths.
  - `app.py` mounts `web/public` at `/public` and serves `GET /favicon.ico` from it.
  - Do not regenerate the icons from a smaller source.
- **Colors.** UI colors are separate from the PDF palette in `render/theme.py`. Decision
  colors: ADVANCE teal, HOLD amber, PASS coral.
- **Accessibility.**
  - Keep: a keyboard-reachable file input, visible focus, `aria-live` progress, focus moving
    to the heading on each view change, reduced-motion support, and AA contrast (footer text
    uses `--ink-500`, not `--ink-600`).
- **Other screens.** Investors, Profile, Criteria Pack, and Review reuse the same card, field,
  chip, button, panel, and status components. Add a nav in the brand row when they are built.

### API

| Method | Path | Notes |
|---|---|---|
| GET | `/healthz` | Returns `{status, api_key_set, data_dir_persistent, soffice_available, email_enabled, analysis_available}`. With `?deep=1` it also returns `api_key_valid` (via `models.list()`). |
| GET | `/` | The UI |
| GET/POST | `/api/investors` | List returns `[{slug, name, approved_pack: {version, hash} or null}]`; create |
| GET/PUT | `/api/investors/{slug}/profile` | PUT returns validation questions |
| POST | `/api/investors/{slug}/criteria/build` | Returns `{job_id}` |
| GET/PUT | `/api/investors/{slug}/criteria/draft` | Review / answer open questions |
| POST | `/api/investors/{slug}/criteria/approve` | 409 while open questions remain |
| GET | `/api/investors/{slug}/criteria/{version}/pdf` · `/template.pdf` | |
| POST | `/api/investors/{slug}/screen` | Multipart fields: `deck`, `email` (`true`/`false`), `pack_version`. Returns `{job_id}`; 409 if no approved pack |
| GET | `/api/jobs/{job_id}` | `{id, state, stage, progress, error, result, email}`; shapes under "UI design" |
| GET | `/api/jobs/{job_id}/pdf` · `/json` | Artifacts |
| POST | `/api/investors/{slug}/decisions` | JSON `{job_id, final_decision: ADVANCE or HOLD or PASS, reviewer_initials, exception_reason}` (§10) |
| POST | `/api/investors/{slug}/review` | Returns `{job_id}` |

Errors return `{error: <one actionable sentence>}` with the HTTP status matching the CLI exit
code category. Tracebacks are never returned.

### Jobs

- Requests stay short: model calls run as background jobs, and the client polls every 2s.
  No endpoint blocks for the length of a model call (an Opus run on a large deck can exceed
  100s).
- Jobs are in-memory and single-instance, so keep `numReplicas` at 1. Keep background task
  references in `_TASKS` (asyncio holds only weak references).
- Concurrency is bounded by `MAX_CONCURRENT_JOBS`. Temporary job artifacts are swept after
  `JOB_TTL_MINUTES`. Persistent records (profiles, packs, decision log, scorecards) live in
  `ICB_DATA_DIR` and are never swept.

### Security

- **Public access.** The app has no sign-in; anyone with the URL can use every screen and
  API route. This was the operator's decision on 2026-09-15 (see `DECISIONS.md`). Do not add
  authentication back unless the operator asks. The build must still account for the
  consequences:
  - **Spend.** Every screening and criteria build spends the Anthropic key. Before Phase 7
    enables any endpoint that starts a model call, stop and ask the operator whether to add
    per-client rate limits and a daily job cap, and what values to use. Do not pick
    defaults. `MAX_UPLOAD_MB` and `MAX_CONCURRENT_JOBS` still apply.
  - **Email volume.** Every result emails `ICB_REPORT_EMAIL_TO` (§16), so anyone can trigger
    those emails. Include this in the same question.
  - **Confidentiality.** Investor profiles, criteria packs, decision logs, and scorecards on
    the volume are readable by any visitor. The UI must not describe the app as
    confidential or access-controlled.
  - `/public` holds brand assets only (icons, manifest, fonts).
- **API key.** Read only from `ANTHROPIC_API_KEY`. Never accepted from the client, never
  logged, never included in any response or error. There is no UI field for it.
- **Uploads.** The server enforces an extension + magic-byte check and `MAX_UPLOAD_MB`.
  Uploaded decks are deleted as soon as they are ingested.
- **Egress.** The Anthropic API and Resend only (§3, §16).

### Persistence on Railway

- The container filesystem is wiped on redeploy. Attach a Railway volume mounted at `/data`
  and set `ICB_DATA_DIR=/data/investors` and `ICB_CACHE_DIR=/data/cache`.
- `data_dir_persistent` is true only when `ICB_DATA_DIR` is under `RAILWAY_VOLUME_MOUNT_PATH`
  (or when not running on Railway).
- When it is false, log a warning at startup and show a persistent red banner in the UI:
  "No volume attached. Profiles, criteria packs and decision logs will be lost on redeploy."

### Known platform limits

- The Railpack image has no LibreOffice. On Railway, `.ppt` uploads are rejected with a clear
  message, and `.pptx` decks are ingested from text, tables, and speaker notes without slide
  images. The UI states this next to the upload control when `soffice_available` is false.

### Deployment files

- `railway.json`: already present.
  - Builder `RAILPACK`, Railway's current default. Nixpacks is deprecated, and Railpack could
    not build the repository before a Python entry point existed.
  - Start command `python app.py`, which runs uvicorn on `$PORT` with proxy headers and a
    120s keep-alive.
  - `healthcheckPath: /healthz`, `numReplicas: 1`.
  - Once `src/icb` exists, make it importable, e.g. `sys.path` in `app.py` or an installed
    package. Do not add a shell-dependent `PYTHONPATH=src` prefix.
- `Procfile`: `web: python app.py`.
- `requirements.txt`: exact pins matching `../deckpager/requirements.txt`, plus `pyyaml`
  and `httpx` pinned. Never use loose `>=` bounds (a floating major version broke a sibling
  deploy).
- `.python-version`: `3.12` (matches `../ConvictionLadder`).

### Deployment runbook (Phase 8)

1. `git init` in this folder. Run `git check-ignore .env investors/` and **stop if either is
   not ignored**. Commit.
2. Create a **private** GitHub repository and push.
3. In Railway: New Project → Deploy from GitHub repo → select it. (CLI alternative: `railway init`,
   then `railway up`.)
4. Service → Settings → Volumes: add a volume mounted at `/data`.
5. Service → Variables:

   | Variable | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | the Console key |
   | `ICB_DATA_DIR` | `/data/investors` |
   | `ICB_CACHE_DIR` | `/data/cache` |
   | `ICB_MODEL` | `claude-opus-5` |
   | `RESEND_API_KEY` | the Resend key |
   | `ICB_REPORT_EMAIL_TO` | `Info@tencapital.group` |
   | `ICB_REPORT_EMAIL_FROM` | a sender on the Resend-verified domain |
   | `MAX_UPLOAD_MB` · `MAX_CONCURRENT_JOBS` · `JOB_TTL_MINUTES` | defaults from `.env.example` |

   Set the keys in the dashboard, or from the local `.env` without echoing it. Never type the
   key literally into a shell command, commit, log, or chat message.
6. Settings → Networking → Generate Domain.
7. Verify: `GET /healthz?deep=1` must report `api_key_set`, `api_key_valid`,
   `data_dir_persistent`, and `email_enabled` all true. Then create the example investor, approve its pack,
   and screen one real deck through the browser.
8. Record the deployment URL, volume, and any departures from this runbook in `DECISIONS.md`.

### `test_web`

- Use `with TestClient(app) as c:` so background jobs complete.
- Stub `pipeline` functions; make no network calls.
- Cover:
  - every page and API route works without credentials, on Railway or locally, even if an
    old `APP_PASSWORD` variable is still set
  - upload size and type limits
  - `.ppt` rejected when soffice is unavailable
  - 409 screening without an approved pack
  - 409 approving with open questions
  - the full job lifecycle through PDF download
  - an override without a reason is rejected
  - the API key value never appears in any response body, header, or log record
    (set a sentinel key and scan)
  - the served `/` has `{{CONFIG_JSON}}` replaced, carries no preview-mode
    config, and contains no email address other than `ICB_REPORT_EMAIL_TO`
  - an injected config value containing `</script>` cannot break out of the script tag
  - icons, following `../EarlyTractionValidation/tests/test_favicon.py`:
    - every icon and apple-touch-icon `href` in the page, and every manifest icon, returns
      200 with a PNG or ICO signature
    - `GET /favicon.ico` works
    - all of them load without credentials

## 16. Result emails (Resend)

Follow the "Emailing each result" section of `../deckpager/README.md`, and the email rules in
`../ConvictionLadder/CLAUDE.md`: emailing is a side errand, never a gate, and the recipient
is always operator-configured.

Reuse the structure of `../deckpager/src/deckpager/mailer.py`: a stdlib `urllib` POST to
`https://api.resend.com/emails`, with `build_html`, `build_text`, `build_payload`, and `send`
returning an `EmailOutcome`.

### Configuration

| Variable | Meaning |
|---|---|
| `RESEND_API_KEY` | Resend key with Sending access |
| `ICB_REPORT_EMAIL_TO` | Recipient(s), comma-separated. Operator setting: `Info@tencapital.group` |
| `ICB_REPORT_EMAIL_FROM` | Sender. Must be on a Resend-verified domain |

- Emailing is **on only when `RESEND_API_KEY` and `ICB_REPORT_EMAIL_TO` are both set.** There is
  no separate on/off switch.
- The recipient comes only from configuration. It is never hardcoded as a code default and
  never taken from the browser or a request. No CC, no BCC.
- Opting out of a single run: the CLI takes `--no-email`; the web upload form has an
  "Email this result" checkbox, checked by default.

### What is emailed

One email per completed generation. Failed runs are not emailed; the error is shown where
the run started. Blank templates and plain re-downloads are not emailed.

**Screening** (`icb screen`, the web screen, and each deck in `icb batch`)
- Subject: `[ICB] {DECISION} — {Company} · {Investor} · {weighted_score}/5`
- Body:
  - decision and rule sentence
  - weighted score vs. threshold, and evidence coverage
  - hard-criteria counts, with every criterion that is NOT MET or UNVERIFIED
  - triggered deal-breakers, and the top 3 concerns
  - evidence to request, bias flags, and thesis fit
  - pack version + hash, and warnings/truncations
  - a "cached result" note when applicable
- Attachments: scorecard PDF, screening JSON

**Criteria Pack draft built**
- Subject: `[ICB] Criteria Pack v{N} draft — {Investor}`
- Body: factors and weights, advance threshold, deal-breaker count, every open question, and
  `Approval blocked: {n} open questions` when any remain
- Attachments: pack PDF, draft JSON

**Criteria Pack approved**
- Subject: `[ICB] Criteria Pack v{N} approved — {Investor}`
- Body: hash, weights table, changelog entry
- Attachments: pack PDF

**Decision recorded** (§10)
- Subject: `[ICB] Decision recorded: {final} — {Company}`, with ` (OVERRIDE)` appended when it
  is one
- Body: computed vs. final decision, exception reason, reviewer initials
- Attachments: re-rendered scorecard PDF

**Criteria review** (§11)
- Subject: `[ICB] Criteria review — {Investor} · {date}`
- Body: key statistics, and the below-minimum-sample flag
- Attachments: review PDF

### Content rules

- Every number and label comes from the same validated objects the PDF renders. Never make an
  extra model call to write the email.
- Send HTML and a plain-text alternative. HTML-escape every model string.
- Color the decision with the scorecard palette. No remote images, no tracking pixels.
- First line of every email: `Confidential — TEN Capital internal. AI-assisted analysis; verify against source documents.`
- Attachments are base64-encoded. If the payload would exceed 30 MB:
  1. Drop the JSON.
  2. If it is still too large, send without attachments and say so in the body.

### Delivery rules

- **Never a gate.** Send only after the artifacts are written and the job is marked done.
  - On failure, record `email: {status: failed, reason}` on the job and the CLI result, and
    log a WARNING.
  - A failure never changes the job state or the exit code.
- **No duplicates.** Send an `Idempotency-Key` header of `sha256(trigger + artifact hash)`, so
  retries and double-submits don't send twice.
- **Retries.** Retry 429/5xx with exponential backoff, max 3 attempts, 15s timeout each.
  Batch sends are throttled to ≤ 2 requests/second.
- **Logging.** Log only the recipient domain and the Resend message id. Never log the key or
  the email body.
- **Decision log.** `decisions.jsonl` records the email outcome (status, message id) for each
  screening.

### Setup

1. In Resend → API Keys, create a key with **Sending access**.
2. In Resend → Domains, add `tencapital.group` and publish its DNS records (MX + SPF/DKIM TXT).
   Until the domain is verified, Resend rejects sends from `@tencapital.group`. The rejection is
   reported but not fatal.
3. To test before verification, set `ICB_REPORT_EMAIL_FROM=onboarding@resend.dev`. It delivers
   only to the Resend account owner's address.
4. `icb check` and `/healthz` report `email_enabled`, the recipient, and the sender. With a
   full-access key they also report whether the sender domain is verified.
5. `icb email test` sends one test email to the configured recipient. Run it only when the
   operator asks.

### `test_mailer`

Stub `urlopen`; make no network calls. Cover:
- A missing key or recipient sends nothing and gives status `not_configured`.
- The recipient comes only from settings.
- Subjects follow the formats above for each trigger.
- The HTML escapes `<script>` and `&`, and a plain-text part is present.
- Attachments have the right filenames and base64 content, and oversize payloads degrade as
  specified.
- A Resend 4xx, 5xx, or timeout leaves the job `done` and the CLI exit code 0, with outcome
  `failed` and a readable reason.
- The idempotency key is stable for the same artifact.
- A sentinel key never appears in logs, outcomes, job JSON, or the decision log.
