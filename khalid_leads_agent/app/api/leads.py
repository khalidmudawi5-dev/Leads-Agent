"""Daily workflow API: status, session, queue, lead actions, results, manual mode."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import container
from app.container import AppContainer
from app.schemas.api import ManualOpenIn, ResultIn, SearchIn, SelectCandidateIn, SessionStartIn, SkipIn

router = APIRouter(prefix="/api")


@router.get("/status")
def status(c: AppContainer = Depends(container)) -> dict:
    s = c.settings.get()
    g = c.auth.status(s.google_auth_mode)
    login = c.odoo.last_login
    return {
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
    await c.workflow._refresh(strict=True)
    return await c.workflow.current()


@router.get("/stats")
def stats(c: AppContainer = Depends(container)) -> dict:
    return c.workflow.stats()


@router.post("/lead/{fingerprint}/search")
async def lead_search(fingerprint: str, body: SearchIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.search_odoo(fingerprint, body.query)


@router.post("/lead/{fingerprint}/select")
async def lead_select(fingerprint: str, body: SelectCandidateIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.select_candidate(fingerprint, body.odoo_id, body.ui_index, body.ui_query)


@router.post("/lead/{fingerprint}/open")
async def lead_open(fingerprint: str, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.open_in_odoo(fingerprint)


@router.post("/lead/{fingerprint}/call")
async def lead_call(fingerprint: str, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.call(fingerprint=fingerprint)


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
async def manual_call(body: ManualOpenIn, c: AppContainer = Depends(container)) -> dict:
    return await c.workflow.call(odoo_id=body.odoo_id)
