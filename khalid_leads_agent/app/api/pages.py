"""HTML pages (Jinja2, Arabic RTL)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import container
from app.container import AppContainer
from app.remote_access import tailscale_ips

router = APIRouter()

PAGES = {
    "history": ("history.html", "سجل المتابعات"),
    "skipped": ("skipped.html", "العملاء المتخطون"),
    "errors": ("errors.html", "الأخطاء"),
    "settings": ("settings.html", "الإعدادات"),
    "diagnostics": ("diagnostics.html", "التشخيص (للمطور)"),
    "setup": ("setup.html", "معالج الإعداد"),
}


def _render(request: Request, c: AppContainer, template: str, title: str, active: str) -> HTMLResponse:
    s = c.settings.get()
    phone_urls = []
    if getattr(request.app.state, "remote", None) is not None:
        phone_urls = [f"http://{ip}:{c.env.app_port}" for ip in tailscale_ips()] or ["(شغّل Tailscale على هذا الجهاز)"]
    return request.app.state.templates.TemplateResponse(
        request, template, {"title": title, "active": active, "owner": s.agent_owner, "dry_run": s.dry_run,
                            "version": request.app.version, "phone_urls": phone_urls},
    )


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, c: AppContainer = Depends(container)):
    s = c.settings.get()
    if not s.setup_completed or s.missing_basics():
        return RedirectResponse("/setup", status_code=303)
    return _render(request, c, "dashboard.html", "الرئيسية", "dashboard")


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse("/static/favicon.svg")


@router.get("/{page}", response_class=HTMLResponse)
def page(page: str, request: Request, c: AppContainer = Depends(container)):
    if page not in PAGES:
        return HTMLResponse("<h1 dir='rtl'>الصفحة غير موجودة</h1>", status_code=404)
    template, title = PAGES[page]
    return _render(request, c, template, title, page)
