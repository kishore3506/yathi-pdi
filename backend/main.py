import os
import logging
import secrets
import threading
import time
import sqlite3
import uvicorn
from logging.handlers import RotatingFileHandler
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path

try:
    from .settings import (
        BACKUP_DIR,
        LOG_BACKUP_COUNT,
        LOG_DIR,
        LOG_MAX_BYTES,
        MAX_UPLOAD_BYTES,
        SESSION_MAX_AGE_SECONDS,
        ensure_data_directories,
    )
except ImportError:
    from settings import (
        BACKUP_DIR,
        LOG_BACKUP_COUNT,
        LOG_DIR,
        LOG_MAX_BYTES,
        MAX_UPLOAD_BYTES,
        SESSION_MAX_AGE_SECONDS,
        ensure_data_directories,
    )

logger = logging.getLogger(__name__)


def _configure_logging():
    ensure_data_directories()
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(
            LOG_DIR / "pdi.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        ),
    ]
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


_configure_logging()
_gemini_health_lock = threading.Lock()
_gemini_health_result = None
_gemini_health_checked_at = 0.0
_gemini_health_probe_running = False
_GEMINI_HEALTH_CACHE_SECONDS = 60
_GEMINI_HEALTH_RETRY_SECONDS = 10


try:
    from .auth import router as auth_router
except ImportError:
    from auth import router as auth_router

try:
    from .database import get_db, init_db
    from .routes import requirements, templates, reports, dashboard, chat, admin
    from .services.gemini_service import GeminiService
    from .services.excel_data_backup import ExcelDataBackup, FILENAME as EXCEL_DATA_FILENAME
except (ImportError, ValueError):
    from database import get_db, init_db
    from routes import requirements, templates, reports, dashboard, chat, admin
    from services.gemini_service import GeminiService
    from services.excel_data_backup import ExcelDataBackup, FILENAME as EXCEL_DATA_FILENAME

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_directories()
    init_db()
    excel_data = ExcelDataBackup(get_db, BACKUP_DIR / EXCEL_DATA_FILENAME)
    app.state.excel_data = excel_data
    excel_data.start()
    try:
        yield
    finally:
        await run_in_threadpool(excel_data.close)

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
PUBLIC_APP_ORIGIN = os.getenv("PUBLIC_APP_ORIGIN", "").strip().rstrip("/")
if APP_ENV == "production" and len(SESSION_SECRET) < 32:
    raise RuntimeError("SESSION_SECRET must contain at least 32 characters in production.")
if APP_ENV == "production":
    origin_parts = urlsplit(PUBLIC_APP_ORIGIN)
    if (
        origin_parts.scheme != "https"
        or not origin_parts.netloc
        or origin_parts.path not in {"", "/"}
        or origin_parts.query
        or origin_parts.fragment
    ):
        raise RuntimeError("PUBLIC_APP_ORIGIN must be the HTTPS origin used by employee browsers.")

app = FastAPI(
    title="Yathi Pumps PDI Automation",
    description="Automated PDI Report Generation for Yathi Pumps (Customers: Havells, Crompton, KSB, KOEL) with Gemini API, Excel Template Preservation, and Gmail SMTP Email Integration",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(auth_router)
app.include_router(requirements.router)
app.include_router(templates.router)
app.include_router(reports.router)
app.include_router(dashboard.router)
app.include_router(chat.router)
app.include_router(admin.router)

_PUBLIC_API_PATHS = {
    "/api/health",
    "/api/version",
    "/api/auth/login",
    "/api/auth/setup/status",
    "/api/auth/logout",
}
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _api_error(detail: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"detail": detail},
        status_code=status_code,
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


def _required_role(path: str, method: str):
    if path == "/api/templates/match":
        return {"inspector", "approver", "administrator"}
    if path.startswith("/api/admin/"):
        return {"administrator"}
    if path.startswith("/api/auth/users"):
        return {"administrator"}
    if path.startswith("/api/templates/") and method != "GET":
        return {"administrator"}
    if path.startswith("/api/requirements/") and method != "GET":
        return {"inspector", "administrator"}
    if path == "/api/reports/generate":
        return {"inspector", "administrator"}
    if path.startswith("/api/reports/") and method == "PATCH":
        return {"inspector", "approver", "administrator"}
    if path.endswith("/approve") or path.endswith("/legal/agree"):
        return {"approver", "administrator"}
    if path == "/api/reports/email":
        return {"approver", "administrator"}
    if path.startswith("/api/chat/") or path == "/api/chat":
        return {"inspector", "approver", "administrator"}
    if method not in {"GET", "HEAD", "OPTIONS"}:
        return {"administrator"}
    return {"inspector", "approver", "administrator"}


@app.middleware("http")
async def protect_api(request: Request, call_next):
    path = request.url.path
    local_access = (
        APP_ENV == "development"
        and request.client is not None
        and request.client.host in _LOOPBACK_HOSTS
        and request.url.hostname in _LOOPBACK_HOSTS
    )
    if local_access and path.startswith("/api/"):
        origin = request.headers.get("origin")
        same_origin = f"{request.url.scheme}://{request.url.netloc}"
        if (origin and origin != same_origin) or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            return _api_error("Request origin is not permitted.", 403)
        if path.startswith("/api/auth/") and path != "/api/auth/me":
            return _api_error("Employee accounts are unavailable in the local app.", 404)

    if (
        APP_ENV == "production"
        and path.startswith("/api/")
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.headers.get("origin") != PUBLIC_APP_ORIGIN
    ):
        return _api_error("Request origin is not permitted.", 403)
    if request.method in {"POST", "PUT", "PATCH"} and path != "/api/admin/import":
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_UPLOAD_BYTES:
            return _api_error("Request exceeds the configured upload limit.", 413)

    if local_access and path.startswith("/api/"):
        request.state.user = {"role": "administrator", "local_access": True}
    elif path.startswith("/api/") and path not in _PUBLIC_API_PATHS:
        user = None
        try:
            user_id = request.session.get("user_id")
        except (AttributeError, KeyError):
            user_id = None
        if user_id is not None:
            try:
                from .database import get_db
            except ImportError:
                from database import get_db
            conn = get_db()
            try:
                user = conn.execute(
                    "SELECT id, email, display_name, role, is_active FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
            finally:
                conn.close()
        if not user or not user["is_active"]:
            request.session.clear()
            return _api_error("Login required.", 401)
        if user["role"] not in _required_role(path, request.method):
            return _api_error("Your role is not permitted to perform this action.", 403)
        request.state.user = user

    response = await call_next(request)
    if path.startswith("/api/") or path in {"/", "/index.html", "/manifest.webmanifest", "/sw.js"}:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    elif response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    elif path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    logger.error(
        "Unhandled request failure on %s (%s)",
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        {"detail": "The request could not be completed."},
        status_code=500,
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET or secrets.token_urlsafe(32),
    session_cookie="pdi_session",
    max_age=SESSION_MAX_AGE_SECONDS,
    same_site="lax",
    https_only=APP_ENV == "production",
)


def _refresh_gemini_health():
    global _gemini_health_result, _gemini_health_checked_at, _gemini_health_probe_running
    try:
        result = GeminiService().check_health()
    except Exception:
        logger.exception("Gemini health probe failed")
        result = {
            "status": "error",
            "provider": "Google Gemini API",
            "active_model": GeminiService().model,
            "api_key_configured": True,
            "message": "Gemini health probe failed. Check the backend logs.",
        }
    with _gemini_health_lock:
        _gemini_health_result = result
        _gemini_health_checked_at = time.monotonic()
        _gemini_health_probe_running = False


@app.get("/api/health")
def health_check():
    global _gemini_health_probe_running
    conn = get_db()
    try:
        conn.execute("SELECT 1")
    except sqlite3.Error:
        logger.exception("Database health check failed")
        return JSONResponse(
            {"status": "unhealthy", "detail": "The application database is unavailable."},
            status_code=503,
        )
    finally:
        conn.close()

    ai = GeminiService()
    if not ai.api_key:
        gemini_status = ai.check_health()
    else:
        now = time.monotonic()
        with _gemini_health_lock:
            cache_ttl = (
                _GEMINI_HEALTH_CACHE_SECONDS
                if _gemini_health_result and _gemini_health_result.get("status") == "connected"
                else _GEMINI_HEALTH_RETRY_SECONDS
            )
            cache_is_fresh = (
                _gemini_health_result is not None
                and now - _gemini_health_checked_at < cache_ttl
            )
            if cache_is_fresh:
                gemini_status = _gemini_health_result
            else:
                if not _gemini_health_probe_running:
                    _gemini_health_probe_running = True
                    threading.Thread(target=_refresh_gemini_health, daemon=True).start()
                gemini_status = {
                    "status": "checking",
                    "provider": "Google Gemini API",
                    "active_model": ai.model,
                    "api_key_configured": True,
                }
    return {
        "status": "healthy",
        "service": "Yathi Pumps PDI Automation",
        "gemini": gemini_status
    }


@app.get("/api/version")
def version_check():
    return {
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "commit": os.getenv("RENDER_GIT_COMMIT", "local"),
    }


# Mount frontend production build if available
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if os.path.exists(frontend_dist):
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found."}, status_code=404)
        root = frontend_dist.resolve()
        file_path = (root / full_path).resolve()
        if file_path.is_relative_to(root) and file_path.is_file():
            return FileResponse(file_path)
        index_path = root / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return JSONResponse({"detail": "Frontend build is unavailable."}, status_code=503)

HOST = os.getenv("HOST", "0.0.0.0" if APP_ENV == "production" else "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
APP_IMPORT = "backend.main:app"

if __name__ == "__main__":
    uvicorn.run(
        APP_IMPORT,
        host=HOST,
        port=PORT,
        reload=False,
        log_config=None,
        access_log=False,
    )
