"""FastAPI application factory for Khalid Leads Agent (local only: 127.0.0.1)."""
from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import PROJECT_ROOT, EnvSettings
from app.container import AppContainer, build_container
from app.errors import AgentError
from app.remote_access import COOKIE, COOKIE_MAX_AGE, LOCAL_ONLY_PATHS, LOCAL_OPEN_PATHS, PUBLIC_PATHS, RemoteAccess, is_loopback, is_tailscale, valid_pin
from app.login_service import COOKIE as LOGIN_COOKIE, LoginService
from app.repositories.log_repo import LogRepository
from app.utils.logging import setup_logging

log = logging.getLogger("app")
APP_DIR = PROJECT_ROOT / "app"
from app.version import VERSION  # noqa: E402,F401 - re-exported
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

    login = LoginService(env.data_path)
    app.state.login = login
    app.state.templates.env.globals["login_enabled"] = lambda: login.enabled
    remote = None
    if env.remote_access:
        if valid_pin(env.access_pin) or login.enabled:
            remote = RemoteAccess(env.access_pin, env.data_path / "remote-secret.bin")
            log.info("Remote access over Tailscale is ON (%s)", "sign-in" if login.enabled else "PIN protected")
        else:
            log.error("REMOTE_ACCESS=true ignored: set ACCESS_PIN (6+ digits) or a sign-in password")
    app.state.remote = remote

    # Remote mode is reached by Tailscale IP or name: the client-address check below replaces the host list.
    hosts = allowed_hosts or (["*"] if remote else ["127.0.0.1", "localhost"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    def _need_login(path: str, message: str):
        if path.startswith("/api/"):
            return JSONResponse({"error": {"code": "LOGIN_REQUIRED", "message": message, "actions": []}}, status_code=401)
        nxt = path if path.startswith("/") and not path.startswith("//") else "/"
        return RedirectResponse(f"/login?next={quote(nxt)}", status_code=303)

    @app.middleware("http")
    async def access_guard(request: Request, call_next):
        """Who may use the agent.

        * PC (loopback): free, unless a sign-in password is set (then the login cookie is needed, except
          for the stop/version endpoints the .bat files call).
        * Tailscale devices (remote access on): sign-in cookie, or the PIN cookie when no password is set.
        * Anything else: refused.
        """
        client = request.client.host if request.client else ""
        path = request.url.path
        local = is_loopback(client)
        if remote is not None and local and request.url.hostname not in ("127.0.0.1", "localhost"):
            # The PC keeps the local-only host check (blocks DNS-rebinding pages in the PC's browser).
            return PlainTextResponse("Forbidden", status_code=403)
        if not local:
            if remote is None:
                return await call_next(request)  # only reachable in tests (the server listens on 127.0.0.1)
            if not is_tailscale(client) or path.startswith(LOCAL_ONLY_PATHS):
                log.warning("Refused %s %s from %s", request.method, path, client)
                return PlainTextResponse("Forbidden", status_code=403)
        if path.startswith(PUBLIC_PATHS) or (local and path.startswith(LOCAL_OPEN_PATHS)):
            return await call_next(request)
        if login.enabled:
            if login.authenticated(request.cookies.get(LOGIN_COOKIE)):
                return await call_next(request)
            return _need_login(path, "سجّل الدخول أولًا.")
        if local or remote.authenticated(request.cookies.get(COOKIE)):
            return await call_next(request)
        return _need_login(path, "أدخل رمز الدخول (PIN) أولًا.")

    def _safe_next(value: str) -> str:
        return value if value.startswith("/") and not value.startswith("//") and "\\" not in value else "/"

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_page(request: Request, error: str = "", next: str = "/"):
        mode = "password" if login.enabled else "pin" if remote is not None else ""
        if not mode:
            return RedirectResponse("/", status_code=303)
        return app.state.templates.TemplateResponse(
            request, "login.html", {"error": error, "version": VERSION, "mode": mode, "next": _safe_next(next),
                                    "username": login.username if is_loopback(request.client.host if request.client else "") else ""})

    @app.post("/login", include_in_schema=False)
    async def login_submit(request: Request):
        client = request.client.host if request.client else ""
        form = parse_qs((await request.body()).decode("utf-8", "replace"))
        field = lambda k: form.get(k, [""])[0]  # noqa: E731
        nxt = _safe_next(field("next") or "/")
        back = f"&next={quote(nxt)}"
        if login.enabled:
            wait = login.locked_for(client)
            if wait:
                return RedirectResponse(f"/login?error=locked{wait // 60 + 1}{back}", status_code=303)
            if not login.check(client, field("username"), field("password")):
                return RedirectResponse(f"/login?error=wrong{back}", status_code=303)
            value, ttl = login.token(remember=field("remember") == "1")
            resp = RedirectResponse(nxt, status_code=303)
            resp.set_cookie(LOGIN_COOKIE, value, max_age=ttl if field("remember") == "1" else None,
                            httponly=True, samesite="strict")
            return resp
        if remote is None:
            return RedirectResponse("/", status_code=303)
        wait = remote.locked_for(client)
        if wait:
            return RedirectResponse(f"/login?error=locked{wait // 60 + 1}{back}", status_code=303)
        if not remote.check_pin(client, field("pin")):
            return RedirectResponse(f"/login?error=wrong{back}", status_code=303)
        resp = RedirectResponse(nxt, status_code=303)
        resp.set_cookie(COOKIE, remote.token(), max_age=COOKIE_MAX_AGE, httponly=True, samesite="strict")
        return resp

    @app.post("/logout", include_in_schema=False)
    async def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(LOGIN_COOKIE)
        return resp

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

    from app.api import auth_api, diagnostics_api, history_api, leads, pages, reports_api, settings_api

    app.include_router(auth_api.router)
    app.include_router(leads.router)
    app.include_router(settings_api.router)
    app.include_router(history_api.router)
    app.include_router(diagnostics_api.router)
    app.include_router(reports_api.router)
    app.include_router(pages.router)
    return app
