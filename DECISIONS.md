# Decisions

Design decisions taken where the build spec (`CLAUDE.md`) was silent, and places where the spec
met reality. Newest first.

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
