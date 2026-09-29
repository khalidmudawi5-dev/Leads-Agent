"""History (سجل المتابعات), skipped leads, errors and audit API."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import container
from app.container import AppContainer
from app.errors import AgentError
from app.repositories.lead_repo import SkipRepository
from app.repositories.log_repo import LogRepository
from app.repositories.result_repo import CallResultRepository
from app.services.settings_service import RESULT_LABELS
from app.repositories.lead_repo import LeadCacheRepository
from app.utils.phone import format_phone, normalize_phone
from app.utils.timeutils import fmt_local, start_of_local_day_utc, start_of_local_week_utc, utcnow

router = APIRouter(prefix="/api")


def _bool(v: str | None) -> bool | None:
    return {"1": True, "true": True, "0": False, "false": False}.get((v or "").lower())


@router.get("/history")
def history(period: str = "", name: str = "", phone: str = "", result: str = "", odoo_ok: str = "",
            sheet_ok: str = "", c: AppContainer = Depends(container)) -> dict:
    since = {"today": start_of_local_day_utc(), "week": start_of_local_week_utc()}.get(period)
    with c.db.session() as s:
        rows = CallResultRepository(s).search(
            since=since, name=name.strip(), phone_norm=normalize_phone(phone) if phone.strip() else "",
            result_code=result, odoo_ok=_bool(odoo_ok), sheet_ok=_bool(sheet_ok),
        )
        # Older rows saved without a sheet number: show the lead's Odoo number instead.
        phones: dict[int, str] = {}
        leads = LeadCacheRepository(s)
        for r in rows:
            phone = r.phone or ""
            if not phone.strip() and r.fingerprint:
                cache = leads.get(r.fingerprint)
                odoo = (cache.odoo_data or {}) if cache else {}
                phone = (cache.phone_raw if cache else "") or odoo.get("phone") or odoo.get("mobile") or ""
            phones[r.id] = format_phone(phone)
    return {"items": [{
        "id": r.id, "time": fmt_local(r.created_at), "company": r.company_name, "phone": phones[r.id],
        "result": RESULT_LABELS.get(r.result_code, r.result_code), "result_code": r.result_code, "note": r.note,
        "odoo": r.odoo_note_status, "activity": r.odoo_activity_status, "google": r.sheet_status,
        "duration": r.duration_seconds, "errors": r.errors or [], "warnings": r.warnings or [],
        "dry_run": r.dry_run, "manual": r.manual_mode, "status": r.status, "followup_at": r.followup_at,
        "can_retry": (not r.dry_run) and (r.odoo_note_status == "failed" or r.odoo_activity_status == "failed"
                                          or r.sheet_status in ("failed", "blocked")),
    } for r in rows], "result_labels": RESULT_LABELS}


@router.get("/history/{result_id}")
def history_detail(result_id: int, c: AppContainer = Depends(container)) -> dict:
    with c.db.session() as s:
        r = CallResultRepository(s).get(result_id)
        if r is None:
            raise AgentError("NOT_FOUND", "السجل غير موجود.")
        syncs = LogRepository(s).syncs_for(r.idempotency_key)
        return {"preview": r.preview, "sync_logs": [
            {"time": fmt_local(x.created_at), "row": x.sheet_row, "column": x.column, "cell": x.cell,
             "old": x.old_value, "new": x.new_value, "status": x.status} for x in syncs]}


@router.post("/history/{result_id}/retry")
async def history_retry(result_id: int, c: AppContainer = Depends(container)) -> dict:
    return await c.results.retry(result_id)


@router.get("/skipped")
def skipped(c: AppContainer = Depends(container)) -> dict:
    now = utcnow()
    sess = c.sessions.active()
    with c.db.session() as s:
        rows = SkipRepository(s).list_recent()
    labels = {"10m": "10 دقائق", "30m": "30 دقيقة", "today": "اليوم", "session": "الجلسة الحالية"}
    items = []
    for r in rows:
        live = r.active and ((r.mode == "session" and sess is not None and r.session_id == sess.id)
                             or (r.until is not None and r.until > now))
        items.append({"id": r.id, "time": fmt_local(r.created_at), "company": r.company_name, "phone": r.phone,
                      "row": r.sheet_row, "mode": labels.get(r.mode, r.mode), "until": fmt_local(r.until),
                      "reason": r.reason, "active": live})
    return {"items": items}


@router.post("/skipped/{skip_id}/restore")
def restore_skipped(skip_id: int, c: AppContainer = Depends(container)) -> dict:
    c.workflow.restore_skip(skip_id)
    return {"ok": True}


@router.get("/errors")
def errors(all: bool = False, c: AppContainer = Depends(container)) -> dict:  # noqa: A002
    with c.db.session() as s:
        rows = LogRepository(s).errors(include_resolved=all)
    return {"items": [{"id": r.id, "time": fmt_local(r.created_at), "code": r.code, "message": r.message,
                       "context": r.context, "screenshot": r.screenshot, "resolved": r.resolved} for r in rows]}


@router.post("/errors/resolve-all")
def resolve_errors(c: AppContainer = Depends(container)) -> dict:
    with c.db.session() as s:
        LogRepository(s).resolve_all()
    return {"ok": True}


@router.get("/audit")
def audit(c: AppContainer = Depends(container)) -> dict:
    with c.db.session() as s:
        rows = LogRepository(s).audits()
    return {"items": [{"id": r.id, "action_id": r.action_id, "time": fmt_local(r.created_at), "system": r.system,
                       "action": r.action, "record": r.record, "before": r.before, "after": r.after,
                       "success": r.success, "dry_run": r.dry_run, "error": r.error} for r in rows]}
