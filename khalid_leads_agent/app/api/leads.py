"""Daily workflow API: status, session, queue, lead actions, results, manual mode."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import container
from app.container import AppContainer
from app.errors import AgentError
from app.remote_access import is_loopback
from app.version import VERSION
from app.schemas.api import CallIn, CreateLeadIn, WhatsAppIn, ManualOpenIn, ResultIn, SearchIn, SelectCandidateIn, SessionStartIn, SkipIn, StatusFilterIn

router = APIRouter(prefix="/api")


@router.get("/status")
def status(request: Request, c: AppContainer = Depends(container)) -> dict:
    s = c.settings.get()
    g = c.auth.status(s.google_auth_mode)
    login = c.odoo.last_login
    return {
        "version": VERSION,
        "remote": not is_loopback(request.client.host if request.client else ""),
        "owner": s.agent_owner,
        "dry_run": s.dry_run,
        "setup_completed": s.setup_completed,
        "missing": s.missing_basics(),
        "google": {"connected": (bool(g["configured"]) or c.env.use_mocks) and not c.sheets.last_error,
                   "configured": g["configured"] or c.env.use_mocks,
                   "error": c.sheets.last_error, "mode": s.google_auth_mode},
        "odoo": {"checked": login is not None, "logged_in": bool(login and login.logged_in),
                 "browser_open": bool(login and login.browser_open), "user": login.user_name if login else "",
                 "message": login.message if login else ""},
        "use_mocks": c.env.use_mocks,
    }


@router.get("/session")
def session_status(c: AppContainer = Depends(container)) -> dict:
    return c.sessions.status()


@router.post("/session/start")
def session_start(body: SessionStartIn, c: AppContainer = Depends(container)) -> dict:
    sess = c.sessions.start(body.resume)
    return {"session": c.sessions.to_dict(sess)}


@router.get("/lead/current")
async def lead_current(c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.current()


@router.post("/lead/next")
async def lead_next(c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.next()


@router.post("/queue/refresh")
async def queue_refresh(c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.refresh_queue()


@router.get("/queue/check")
async def queue_check(c: AppContainer = Depends(container)) -> dict:
    """Polled by the dashboard every «sheet_poll_minutes»: new customers in the sheet."""
    return await c.workflow.check_new()


@router.get("/queue/list")
async def queue_list(kind: str = "pending", c: AppContainer = Depends(container)) -> dict:
    if kind not in ("pending", "all", "match_errors", "followups", "duplicates"):
        raise AgentError("BAD_KIND", "نوع قائمة غير معروف.")
    return await c.workflow.queue_list(kind)


@router.post("/lead/{fingerprint}/goto")
async def lead_goto(fingerprint: str, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.goto(fingerprint)


@router.get("/queue/filter")
async def queue_filter(c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.status_filter()


@router.put("/queue/filter")
async def set_queue_filter(body: StatusFilterIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.set_status_filter(body.values)


@router.get("/stats")
def stats(c: AppContainer = Depends(container)) -> dict:
    return c.workflow.stats()


@router.post("/lead/{fingerprint}/search")
async def lead_search(fingerprint: str, body: SearchIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.search_odoo(fingerprint, body.query)


@router.post("/lead/{fingerprint}/select")
async def lead_select(fingerprint: str, body: SelectCandidateIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.select_candidate(fingerprint, body.odoo_id, body.ui_index, body.ui_query)


@router.post("/lead/{fingerprint}/create-odoo")
async def lead_create_odoo(fingerprint: str, body: CreateLeadIn, c: AppContainer = Depends(container)) -> dict:
    """Add a customer missing from Odoo as a new opportunity/lead (after a fresh duplicate check)."""
    return await c.workflow.create_in_odoo(fingerprint, body.company, body.phone, body.contact_name, body.force,
                                           source=body.source)


@router.get("/lead/{fingerprint}/whatsapp")
def lead_whatsapp_options(fingerprint: str, c: AppContainer = Depends(container)) -> dict:
    return c.whatsapp.options(fingerprint)


@router.post("/lead/{fingerprint}/whatsapp")
async def lead_whatsapp(fingerprint: str, body: WhatsAppIn, request: Request,
                       c: AppContainer = Depends(container)) -> dict:
    """Returns the wa.me link (the page opens it) and records the message in Odoo/Sheet when enabled.
    With an attachment, the file goes on this PC's clipboard (not when the request comes from the phone)."""
    local = is_loopback(request.client.host if request.client else "")
    return await c.whatsapp.send(fingerprint, body.tel, body.text, body.template, body.log,
                                 file_id=body.file, file_name=body.file_name, clipboard=local and body.agent_copy)


@router.post("/lead/{fingerprint}/open")
async def lead_open(fingerprint: str, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.open_in_odoo(fingerprint)


@router.post("/lead/{fingerprint}/call")
async def lead_call(fingerprint: str, body: CallIn | None = None, c: AppContainer = Depends(container)) -> dict:
    body = body or CallIn()
    return await c.workflow.call(fingerprint=fingerprint, target=body.target, force=body.force,
                                 client_dial=body.client_dial)


@router.post("/lead/{fingerprint}/refresh")
async def lead_refresh(fingerprint: str, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.refresh_lead(fingerprint)


@router.get("/lead/{fingerprint}/live")
async def lead_live(fingerprint: str, since: str = "", c: AppContainer = Depends(container)) -> dict:
    """Polled by the dashboard: returns the refreshed lead when it changed in Odoo."""
    return await c.workflow.live(fingerprint, since)


@router.post("/lead/{fingerprint}/skip")
async def lead_skip(fingerprint: str, body: SkipIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.skip(fingerprint, body.mode, body.reason)


@router.post("/result")
async def save_result(body: ResultIn, c: AppContainer = Depends(container)) -> dict:
    body.preview_only = False
    return await c.results.save(body)


@router.post("/result/preview")
async def preview_result(body: ResultIn, c: AppContainer = Depends(container)) -> dict:
    body.preview_only = True
    return await c.results.save(body)


@router.post("/odoo/open-crm")
async def open_crm(c: AppContainer = Depends(container)) -> dict:
    await c.workflow.open_crm()
    return {"ok": True}


@router.post("/manual/search")
async def manual_search(body: SearchIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.manual_search(body.query)


@router.post("/manual/open")
async def manual_open(body: ManualOpenIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.manual_open(body.odoo_id)


@router.get("/manual/{odoo_id}/live")
async def manual_live(odoo_id: int, since: str = "", c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.manual_live(odoo_id, since)


@router.post("/manual/call")
async def manual_call(body: CallIn, c: AppContainer = Depends(container)) -> dict:
    if not body.odoo_id:
        raise AgentError("NOT_MATCHED", "لا يوجد عميل محدد للاتصال.")
    return await c.workflow.call(odoo_id=body.odoo_id, target=body.target, force=body.force,
                                 client_dial=body.client_dial)
