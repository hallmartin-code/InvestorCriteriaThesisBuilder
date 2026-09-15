"""Web entry point for the Investor Criteria Builder (CLAUDE.md §15).

This is the deployable shell: it serves the UI, the icon set and the health check. Access is
open to anyone, with no sign-in (operator decision, see DECISIONS.md). The analysis API
arrives in Phase 7; until then every /api route answers 503 with a readable message, so a
deployment never pretends to work.

Local:   uvicorn app:app --reload --env-file .env
Railway: python app.py   (see railway.json)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("icb.web")

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
PUBLIC_DIR = WEB_DIR / "public"

sys.path.insert(0, str(ROOT / "src"))  # src/icb is importable without installing the package
from icb.profile import store, validate  # noqa: E402
from icb.profile.models import ProfileDocument  # noqa: E402

MAX_PROFILE_BYTES = 512 * 1024

CONFIG_TAG = '<script id="app-config" type="application/json">{{CONFIG_JSON}}</script>'
INDEX_TEMPLATE = (WEB_DIR / "index.html").read_text(encoding="utf-8")
if CONFIG_TAG not in INDEX_TEMPLATE:
    raise RuntimeError("web/index.html is missing the app-config placeholder.")

DECK_TYPES = [".pdf", ".pptx", ".docx"]
RAILWAY_MARKERS = ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID")
NOT_BUILT = "Saving and screening are not deployed yet. This build serves the interface only."
KEY_CHECK_TTL_S = 60.0


# --- settings (read per request, so tests and Railway variable changes need no reload) ----


def on_railway() -> bool:
    return any(os.getenv(name) for name in RAILWAY_MARKERS)


def max_upload_mb() -> int:
    try:
        return max(1, int(os.getenv("MAX_UPLOAD_MB", "25")))
    except ValueError:
        return 25


def soffice_available() -> bool:
    return bool(shutil.which("soffice") or shutil.which("libreoffice"))


def email_enabled() -> bool:
    return bool(os.getenv("RESEND_API_KEY") and os.getenv("ICB_REPORT_EMAIL_TO"))


def data_dir_persistent() -> bool:
    """True when investor data survives a redeploy: always locally, on Railway only on a volume."""
    if not on_railway():
        return True
    mount, data_dir = os.getenv("RAILWAY_VOLUME_MOUNT_PATH"), os.getenv("ICB_DATA_DIR")
    if not mount or not data_dir:
        return False
    return Path(data_dir).resolve().is_relative_to(Path(mount).resolve())


def client_config() -> dict[str, object]:
    return {
        "max_mb": max_upload_mb(),
        "accept": DECK_TYPES + ([".ppt"] if soffice_available() else []),
        "email_enabled": email_enabled(),
        "email_to": os.getenv("ICB_REPORT_EMAIL_TO", "") if email_enabled() else "",
        "data_dir_persistent": data_dir_persistent(),
        "soffice_available": soffice_available(),
    }


def config_script() -> str:
    # Escape <, > and & so no configured value can close the <script> tag.
    raw = json.dumps(client_config())
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return CONFIG_TAG.replace("{{CONFIG_JSON}}", raw)


# --- API key check ------------------------------------------------------------------------

_key_check: tuple[float, bool | None] = (0.0, None)


def api_key_valid() -> bool | None:
    """Check the key against the models endpoint, which costs no tokens. None means unreachable."""
    global _key_check
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return False
    checked_at, cached = _key_check
    if cached is not None and time.monotonic() - checked_at < KEY_CHECK_TTL_S:
        return cached
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/models?limit=1",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    result: bool | None
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed https URL
            result = response.status == 200
    except urllib.error.HTTPError as exc:
        result = False if exc.code in (401, 403) else None
    except (urllib.error.URLError, TimeoutError):
        result = None
    _key_check = (time.monotonic(), result)
    return result


# --- app ----------------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if on_railway() and not data_dir_persistent():
        log.warning("No Railway volume holds ICB_DATA_DIR: investor data will be lost on redeploy.")
    yield


app = FastAPI(title="TEN Capital Investor Screening", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


def readable_errors(errors: list[dict[str, object]]) -> str:
    """One sentence from a pydantic/FastAPI error list, for the UI's error line."""
    first = errors[0] if errors else {}
    where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")  # type: ignore[attr-defined]
    message = str(first.get("msg", "The request is not valid.")).removeprefix("Value error, ")
    return f"{where}: {message}" if where else message


@app.exception_handler(store.StoreError)
async def store_error(_request: Request, exc: store.StoreError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def request_invalid(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse({"error": readable_errors(list(exc.errors()))}, status_code=422)


@app.middleware("http")
async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.get("/healthz", include_in_schema=False)
def healthz(deep: bool = False) -> dict[str, object]:
    body: dict[str, object] = {
        "status": "ok",
        "api_key_set": bool(os.getenv("ANTHROPIC_API_KEY")),
        "data_dir_persistent": data_dir_persistent(),
        "soffice_available": soffice_available(),
        "email_enabled": email_enabled(),
        "analysis_available": False,
    }
    if deep:
        body["api_key_valid"] = api_key_valid()
    return body


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "favicon.ico", media_type="image/x-icon",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = INDEX_TEMPLATE.replace(CONFIG_TAG, config_script())
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


# --- investor profiles (§6, §15) — registered before the not-built catch-all ------------


async def json_body(request: Request, limit: int) -> object:
    body = await request.body()
    if len(body) > limit:
        raise store.InvalidInput("The request is too large.")
    try:
        return json.loads(body or b"null")
    except ValueError:
        raise store.InvalidInput("The request body is not valid JSON.") from None


@app.get("/api/investors")
def investors_list() -> list[dict[str, object]]:
    return store.list_investors()


@app.post("/api/investors", status_code=201)
async def investors_create(request: Request) -> JSONResponse:
    payload = await json_body(request, 4096)
    if not isinstance(payload, dict):
        raise store.InvalidInput('Send the investor as {"slug": ..., "name": ...}.')
    created = store.create_investor(str(payload.get("slug") or ""), str(payload.get("name") or ""))
    return JSONResponse(created, status_code=201)


@app.get("/api/investors/{slug}/profile")
def profile_get(slug: str) -> dict[str, object]:
    profile = store.read_profile(slug)
    if profile is None:  # the investor exists, but no inputs have been saved yet
        investor = store.read_investor(slug)
        return {"schema_version": 1, "slug": slug, "display_name": investor["name"], "updated_at": None, "fields": {}}
    return profile


@app.put("/api/investors/{slug}/profile")
async def profile_put(slug: str, request: Request) -> dict[str, object]:
    store.investor_path(slug)
    body = await request.body()
    if len(body) > MAX_PROFILE_BYTES:
        raise store.InvalidInput("The profile is too large to save.")
    try:
        document = ProfileDocument.model_validate_json(body)
    except ValidationError as exc:
        raise store.InvalidInput(readable_errors(list(exc.errors()))) from None
    if document.slug != slug:
        raise store.InvalidInput("The profile ID in the document does not match the investor being saved.")
    result = validate.normalize(document, store.note_files(slug))
    saved_at = store.now_iso()
    store.write_profile(slug, {
        "schema_version": 1, "slug": slug, "display_name": document.display_name,
        "updated_at": saved_at, "fields": result["fields"],
    })
    return {"saved_at": saved_at, "questions": result["questions"], "issues": result["issues"]}


@app.post("/api/investors/{slug}/profile/notes")
async def notes_post(slug: str, files: list[UploadFile] = File(...)) -> dict[str, object]:
    store.investor_path(slug)
    if len(files) > store.MAX_NOTE_FILES:
        raise store.InvalidInput(f"Attach at most {store.MAX_NOTE_FILES} files at a time.")
    limit = max_upload_mb() * 1024 * 1024
    uploads = [(upload.filename or "", await upload.read(limit + 1)) for upload in files]
    saved = store.save_notes(slug, uploads, limit)
    return {"saved": saved, "files": store.note_files(slug)}


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_not_built(path: str) -> JSONResponse:
    return JSONResponse({"error": NOT_BUILT}, status_code=503)


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")),  # noqa: S104 - container
                proxy_headers=True, forwarded_allow_ips="*", timeout_keep_alive=120)
