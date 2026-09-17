# Decisions

Design decisions taken where the build spec (`CLAUDE.md`) was silent, and places where the spec
met reality. Newest first.

## 2026-09-17 - Result emails were blocked by Cloudflare, not by the key

**Symptom.** Every result email failed with "Resend rejected the API key", while the same key
worked from curl and from `GET /domains`.

**Cause.** Resend is behind Cloudflare, which answers Python's default `Python-urllib/3.x`
user-agent with **403 error code 1010**. Our own error mapping then reported any 403 as a bad
key, which hid it.

**Fix**

1. `mailer.USER_AGENT = "icb/1.0 (TEN Capital Network)"` is sent on every request. Verified:
   the identical payload returns 403 with the default agent and 200 with a real one.
2. A 403 now reports Resend's own response; only a 401 is called a rejected key.
3. `tests/test_mailer.py` asserts the user-agent is sent and that a 1010 block is reported as
   itself.

**Worth checking elsewhere:** `../deckpager` and `../ConvictionLadder` send through Resend with
stdlib urllib too, so their result emails may be failing the same way.

## 2026-09-17 - Answering the pack's questions in the app

**What happened.** A real build for a CPG angel came back with 17 blocking questions, and the
page had nowhere to answer them. Two faults: the prompt told the model to record each question
in `needs_input` *and* `open_questions`, so most were listed twice; and answers had no home.

**Decisions**

1. **Answers are investor input**, stored on the profile as `clarifications`
   (`POST /api/investors/{slug}/clarifications`), not as a side file. Re-answering replaces;
   clearing removes. Saving them never disturbs the form's fields.
2. **The builder reads them back** under ANSWERS TO EARLIER QUESTIONS, and is told to use them
   and not ask again.
3. **Ask once**: the prompt now says a question belongs on its element *or* in
   `open_questions`, never both.
4. **Near-duplicates collapse** in `blocking_questions()` at a 0.3 Jaccard threshold over
   content words. On the real 17 questions this leaves exactly the 9 distinct ones; the closest
   genuinely different pair scored 0.09, so the margin is wide.
5. **The UI** renders each question with its own box, pre-filled from saved answers, and one
   "Save answers & rebuild" button.

## 2026-09-16 - Schemas reshaped to fit the API's grammar limit

**The 400.** Building a pack failed with "The Claude API returned an error (400)", which hid the
API's own explanation. Three faults, found by probing (rejected requests are free):

1. `output_config.format.name` is not a permitted key.
2. The screening schema had 28 nullable parameters; the limit is 16.
3. Both schemas compiled to an over-large grammar.

**What the limit actually charges for** (probed on `claude-opus-5`): arrays of objects - 6 were
accepted, 10 rejected. Forty strings, forty integers, ten enums and arrays of strings were all
fine; a single float tipped a borderline schema over.

**Decisions**

1. **The schemas are flat by design**, and the richer shape is rebuilt in pydantic
   `mode="before"` validators: the snapshot is one repeated `{field, ...}` shape, deal-breakers
   and concerns share one `findings` list, rubric levels are `rubric_1..rubric_5`, and evidence,
   bias flags and requests are `"a | b | c"` strings.
2. **No nullable types**: `""` and `0` mean "not stated", converted back to `None` on the way in.
3. **Integers, not floats**: the advance threshold crosses the wire in tenths (35 = 3.5), and
   confidence as 0-100.
4. **The API's message is now surfaced** in `ModelError` and logged, so the next rejection says
   what was wrong instead of just its status code.
5. **`tests/test_schemas.py` guards the budget offline** so a schema change fails a test rather
   than a deploy.

**Verified against the real API:** a pack built in 79s (8 factors summing to 100, 228-word
thesis, 11 open questions on a placeholder profile - the model asked rather than inventing), and
a screening returned HOLD in 17s on a contentless deck.

## 2026-09-16 - Result emails built

**What shipped.** `src/icb/mail/` (Resend over stdlib HTTP, plus the per-trigger content), wired
into criteria drafts, approvals, screenings and recorded decisions. Covered by
`tests/test_mailer.py` with no network.

**Decisions where the spec was silent**

1. **Attachment trimming order is PDF-last.** Callers pass the PDF first and the JSON second, so
   the JSON is dropped first; if the PDF alone still exceeds 30 MB after base64, it goes too and
   the body says so.
2. **Every email carries an idempotency key** derived from the trigger and the artifact, so a
   retry or a double-click cannot send twice.
3. **Email outcomes are recorded**: on the job (for the UI), in the run result, and in
   `decisions.jsonl` as status plus message id. The key itself is never logged or returned.
4. **A send failure never raises**: `pipeline._email` catches everything, so the artifacts and
   the log always survive a Resend outage.
5. **The web form's "Email this result" checkbox** maps to `send_email=False`, which reports
   status `skipped` rather than pretending nothing was configured.

**Not yet built:** review reports (§11), the Criteria Pack PDF, batch, and the `icb` CLI.

## 2026-09-16 - Criteria packs and screening built

**What shipped.** The standard is now written from the saved inputs and applied to decks:
`criteria/` (build + approve, structural rules in code), `ingest/` (PDF sent whole; PPTX/DOCX as
text), `screen/` (extraction, alignment, the five decision rules), `render/` (the one-page
scorecard), `pipeline.py`, and the job endpoints.

**Decisions where the spec was silent**

1. **A pack cannot be built until every input is answered**, and cannot be approved while any
   element carries `needs_input` or an open question. Both gates are in code.
2. **The model never supplies labels, weights, floors or walk-away conditions.** `align()` copies
   them from the pack, fills in results the model omitted, drops ids the pack does not define,
   and clears any score whose evidence standard was not met.
3. **Slide citations outside the deck's range are rejected**, which costs one correction retry.
4. **Screening needs both gates**: complete inputs *and* an approved pack.
5. **The scorecard's ownership-at-check cell** is computed from the deck's valuation and the
   investor's check size, and is blank unless the deck states the valuation basis.
6. **Artifacts** live in `investors/<slug>/scorecards/<Company>-<date>-<pack hash>.{pdf,json}`;
   every screening and every recorded decision appends to `decisions.jsonl`.
7. **New pins:** `anthropic==0.125.0`, `reportlab==5.0.0`, `pymupdf`, `python-pptx`,
   `python-docx`, `pypdf`.

**Not yet built:** result emails (§16), review reports (§11), the Criteria Pack PDF, batch, and
the `icb` CLI.

## 2026-09-15 — Screening is closed until the inputs are complete

**Decision (operator):** an investor cannot be screened until every §6 input is answered or
marked No preference.

- `GET /api/investors` reports `inputs_complete` and `open_questions` per investor, counted
  from the stored profile (a missing profile counts as every field open).
- The screening tab shows how many inputs are missing, links to the criteria form, and keeps
  the upload button disabled. The CLI and `POST …/screen` refuse in the same state.
- This gate is separate from the Criteria Pack approval gate, which arrives with Phase 2.

## 2026-09-15 — No rate limits or daily cap

**Decision (operator):** do not add per-client rate limits or a daily job cap, and do not ask
about them. This supersedes the "Spec change" item in the open-access entry below.
`CLAUDE.md` §15 now says so. Spend is bounded only by `MAX_UPLOAD_MB`, `MAX_CONCURRENT_JOBS`,
and any spend limit set on the key in the Anthropic Console.

## 2026-09-15 — Investor profiles saved on the server

**What shipped.** Four endpoints, ahead of the Phase 0–6 order, because the operator wanted the
criteria form to save:
- `GET/POST /api/investors`
- `GET/PUT /api/investors/{slug}/profile`
- `POST /api/investors/{slug}/profile/notes`

The code is in `src/icb/profile/` (`models.py`, `validate.py`, `store.py`), tested in
`tests/test_profile_api.py`. `app.py` puts `src/` on `sys.path` rather than installing the
package, per the Railpack entry below.

**Decisions where the spec was silent**

1. **The server decides every field's status.** A field is stored as `provided` only when its
   value is complete, whatever the client sent. `no_preference` is honored only for fields that
   allow it; on a Tier 1 field it is a 422. This enforces "never default a `not_provided` field"
   in code, not just in the UI.
2. **Consistency issues warn but never block a save.** They come back in the PUT response as
   `issues`. Incomplete profiles save too, with their open `questions`, so work isn't lost.
3. **`investor.json` holds the investor's name**, separate from `profile.yaml`. An investor
   exists, and appears in lists, from the moment it is created, before any inputs are saved.
   A PUT with a new `display_name` updates it.
4. **Storage is atomic** (temp file + rename). A damaged `investor.json` is skipped in the list,
   so it can't hide every other investor.
5. **Limits, because the app is open to anyone:**
   - text fields ≤ 5,000 characters (thesis text ≤ 50,000), lists capped
   - profile body ≤ 512 KB
   - ≤ 20 note files per investor, each ≤ `MAX_UPLOAD_MB`
   - note files checked by extension and content: `%PDF` for .pdf, a zip header for .docx,
     UTF-8 for .md/.txt
   - one bad file in an upload saves none
   - filenames reduced to their base name and safe characters, so a path in the name cannot
     escape the notes folder
6. **`approved_pack` is always `null`** until Phase 2 builds and approves Criteria Packs.
7. **New pins:** `pydantic==2.13.4` (as deckpager) and `pyyaml==6.0.3`.

## 2026-09-15 — Sign-in removed: open access

**Decision (operator):** remove the username/password sign-in and make the app open to anyone.
This supersedes the §15 password gate and the auth items verified in the deployment entry below.

- `app.py` no longer has HTTP Basic auth or the "Set APP_PASSWORD" 503 gate. `/healthz` no longer
  reports `auth_enabled`.
- `APP_USERNAME` and `APP_PASSWORD` were removed from `.env`, `.env.example`, and the Railway
  service.
- **Accepted consequences, recorded so they are not rediscovered later:**
  - Anyone with the URL can spend the Anthropic key once screening exists.
  - Anyone can trigger result emails to `ICB_REPORT_EMAIL_TO`.
  - Anyone can read investor data stored on the volume.
- **Spec change.** `CLAUDE.md` §15 now requires Phase 7 to ask the operator about rate limits
  and a daily job cap before enabling any endpoint that starts a model call. No defaults were
  chosen.

## 2026-09-15 — Railway deployment (interface-only shell)

**Deployment**

| Item | Value |
|---|---|
| Railway project | `airy-art` (id `4317c0de-9931-441f-82c9-c98daf53e807`) |
| Service / environment | `InvestorCriteriaThesisBuilder` / `production` |
| URL | https://investorcriteriathesisbuilder-production.up.railway.app |
| Volume | `investorcriteriathesisbuilder-volume`, mounted at `/data` (50 GB) |
| Data paths | `ICB_DATA_DIR=/data/investors`, `ICB_CACHE_DIR=/data/cache` |
| Variables set | `APP_USERNAME`, `APP_PASSWORD`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `ICB_REPORT_EMAIL_TO`, `ICB_REPORT_EMAIL_FROM`, `ICB_MODEL`, `ICB_DATA_DIR`, `ICB_CACHE_DIR`, plus defaults from `.env.example` |

Secrets were set from the local `.env` via `railway variable set --stdin`, never typed on a
command line. `APP_PASSWORD` was generated locally and lives only in `.env` and Railway.

**Verified live** (`/healthz?deep=1` and direct requests):
- `auth_enabled`, `api_key_set`, `api_key_valid`, `data_dir_persistent`, and `email_enabled` are
  all true.
- `/` returns 401 without a login and 200 with one.
- `/favicon.ico` loads without a login.
- `/api/*` answers 503 "not deployed yet".

**Departures from the spec, agreed before they were made**

1. **Railpack instead of Nixpacks.** Railway now builds with Railpack by default. The first
   deploy failed because the repository had no Python entry point. `railway.json` uses
   `"builder": "RAILPACK"`.
2. **Start command `python app.py`, not `PYTHONPATH=src uvicorn …`.** `app.py` reads `$PORT`
   itself, so the start command does not depend on shell expansion. When `src/icb` exists, make
   it importable from `app.py` instead of prefixing `PYTHONPATH`.
3. **The web shell shipped before Phases 0–6.** `app.py` serves the UI, icons, `/healthz`, and
   the password gate so the deployment could be proven early. Phase 7 extends it; the gate and
   health check stay.
4. **Railway detection uses several markers.** `RAILWAY_ENVIRONMENT`,
   `RAILWAY_ENVIRONMENT_NAME`, and `RAILWAY_PROJECT_ID` are all checked, because Railway does not
   guarantee the legacy `RAILWAY_ENVIRONMENT` name.
5. **The placeholder rule is "no `{{CONFIG_JSON}}`", not "no `{{`".** The page's own preview-mode
   detection legitimately contains `{{`.

**Not yet done:** the project has no git repository of its own (the enclosing repository is
the user's home directory). The deploy was uploaded directly, not from GitHub. Phase 0 runs
`git init` in this folder.
