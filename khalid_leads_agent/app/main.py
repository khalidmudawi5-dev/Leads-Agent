"""FastAPI application factory for Khalid Leads Agent (local only: 127.0.0.1)."""
from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import PROJECT_ROOT, EnvSettings
from app.container import AppContainer, build_container
from app.errors import AgentError
from app.repositories.log_repo import LogRepository
from app.utils.logging import setup_logging

log = logging.getLogger("app")
APP_DIR = PROJECT_ROOT / "app"
VERSION = "1.3.3"
CSRF_HEADER = "x-kla"
_QUIET_CODES = {"CONFIG_INCOMPLETE", "QUERY_TOO_SHORT", "FOLLOWUP_DATE_REQUIRED", "STATUS_FILTER_EMPTY", "PHONE_INVALID"}


def _record_error(c: AppContainer, code: str, message: str, path: str, technical: str = "", screenshot: str = "") -> None:
    try:
        with c.db.session() as s:
            LogRepository(s).add_error(code=code, message=message, context={"path": path}, technical=technical,
                                       screenshot=screenshot or "")
    except Exception:  # noqa: BLE001 - never fail the response because of logging
        log.exception("Could not store error log")


def create_app(container: AppContainer | None = None, *, allowed_hosts: list[str] | None = None) -> FastAPI:
    env = container.env if container else EnvSettings()
    setup_logging(env.logs_path, env.log_level)
    c = container or build_container(env)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("Khalid Leads Agent %s started (dry_run=%s)", VERSION, c.settings.get().dry_run)
        yield
        try:
            await c.odoo.adapter.close()
        except Exception:  # noqa: BLE001
            log.warning("Browser close failed", exc_info=True)

    app = FastAPI(title="Khalid Leads Agent", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.container = c
    app.state.templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    hosts = allowed_hosts or ["127.0.0.1", "localhost"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        """State-changing API calls must come from the agent's own pages (custom header + same origin)."""
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            if request.headers.get(CSRF_HEADER) != "1" or (origin and origin.split("://", 1)[-1] != host):
                return JSONResponse({"error": {"code": "FORBIDDEN", "message": "طلب غير مسموح.", "actions": []}},
                                    status_code=403)
        return await call_next(request)

    @app.exception_handler(AgentError)
    async def agent_error_handler(request: Request, exc: AgentError):
        log.warning("%s %s -> %s: %s", request.method, request.url.path, exc.code, exc.message_ar)
        if exc.code not in _QUIET_CODES:
            _record_error(c, exc.code, exc.message_ar, request.url.path, technical=repr(exc.details),
                          screenshot=str(exc.details.get("screenshot", "")))
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        log.info("Validation error on %s: %s", request.url.path, exc.errors())
        return JSONResponse({"error": {"code": "VALIDATION", "message": "البيانات المرسلة غير مكتملة أو غير صحيحة.",
                                       "actions": [], "details": {"errors": str(exc.errors())[:800]}}}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception):
        tb = "".join(traceback.format_exception(exc))
        log.error("Unhandled error on %s %s\n%s", request.method, request.url.path, tb)
        _record_error(c, "UNEXPECTED", "حدث خطأ غير متوقع. تم تسجيل التفاصيل في ملف السجل.", request.url.path, tb)
        return JSONResponse({"error": {"code": "UNEXPECTED",
                                       "message": "حدث خطأ غير متوقع. تم تسجيل التفاصيل في ملف السجل (logs/agent.log).",
                                       "actions": ["retry"]}}, status_code=500)

    from app.api import diagnostics_api, history_api, leads, pages, settings_api

    app.include_router(leads.router)
    app.include_router(settings_api.router)
    app.include_router(history_api.router)
    app.include_router(diagnostics_api.router)
    app.include_router(pages.router)
    return app
