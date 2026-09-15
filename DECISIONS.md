# Decisions

Design decisions taken where the build spec (`CLAUDE.md`) was silent, and places where the spec
met reality. Newest first.

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
