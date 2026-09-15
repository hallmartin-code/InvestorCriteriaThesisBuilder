"""Web entry point for the Investor Criteria Builder (CLAUDE.md §15).

This is the deployable shell: it serves the UI, the icon set and the health check, and
enforces the password gate. The analysis API arrives in Phase 7; until then every /api
route answers 503 with a readable message, so a deployment never pretends to work.

Local:   uvicorn app:app --reload --env-file .env
Railway: python app.py   (see railway.json)
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("icb.web")

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
PUBLIC_DIR = WEB_DIR / "public"

CONFIG_TAG = '<script id="app-config" type="application/json">{{CONFIG_JSON}}</script>'
INDEX_TEMPLATE = (WEB_DIR / "index.html").read_text(encoding="utf-8")
if CONFIG_TAG not in INDEX_TEMPLATE:
    raise RuntimeError("web/index.html is missing the app-config placeholder.")

DECK_TYPES = [".pdf", ".pptx", ".docx"]
RAILWAY_MARKERS = ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID")
NOT_BUILT = "The screening engine is not deployed yet. This build serves the interface only."
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


# --- auth ---------------------------------------------------------------------------------

security = HTTPBasic(auto_error=False)


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    password = os.getenv("APP_PASSWORD", "")
    if not password:
        if on_railway():
            raise HTTPException(status_code=503, detail="Set APP_PASSWORD before using this deployment.")
        return  # local development runs without a password
    username = os.getenv("APP_USERNAME", "ten")
    valid = credentials is not None and all((
        secrets.compare_digest(credentials.username.encode(), username.encode()),
        secrets.compare_digest(credentials.password.encode(), password.encode()),
    ))
    if not valid:
        raise HTTPException(status_code=401, detail="Sign in to use this app.",
                            headers={"WWW-Authenticate": 'Basic realm="TEN Capital", charset="UTF-8"'})


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
    if on_railway():
        if not os.getenv("APP_PASSWORD"):
            log.warning("APP_PASSWORD is not set: every page except /healthz answers 503.")
        if not data_dir_persistent():
            log.warning("No Railway volume holds ICB_DATA_DIR: investor data will be lost on redeploy.")
    yield


app = FastAPI(title="TEN Capital Investor Screening", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


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
        "auth_enabled": bool(os.getenv("APP_PASSWORD")),
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


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def index() -> HTMLResponse:
    page = INDEX_TEMPLATE.replace(CONFIG_TAG, config_script())
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
               dependencies=[Depends(require_auth)], include_in_schema=False)
def api_not_built(path: str) -> JSONResponse:
    return JSONResponse({"error": NOT_BUILT}, status_code=503)


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")),  # noqa: S104 - container
                proxy_headers=True, forwarded_allow_ips="*", timeout_keep_alive=120)
