"""Saving a call result: Odoo Log Note (+ Activity) and Google Sheet update.

Guarantees:

* **Dry Run** (default ON): nothing external is written; a "Would update" preview is returned.
* **Idempotency**: every save carries an ``idempotency_key``; replaying it returns the first
  outcome. The same lead + same result within ``duplicate_window_seconds`` is not written again.
* **Partial failures** never lose data: each step's status is stored and can be retried
  from History (only the failed steps run again; the Odoo note is de-duplicated by its ref).

V2 TODO – Voice input (not implemented in V1, no paid AI dependency):
    Voice Note → transcription → AI extraction → status → notes → follow-up date.
    A voice pipeline must only *pre-fill* a :class:`ResultIn` (``input_channel="voice"``)
    that the user confirms in the result panel. Identity, row matching, source mapping and
    the result code stay deterministic and user-confirmed (no LLM decisions).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from app.db import Database
from app.errors import AgentError
from app.models import CallResult
from app.repositories.lead_repo import LeadCacheRepository
from app.repositories.result_repo import CallResultRepository
from app.schemas.api import ResultIn
from app.services.google_sheets_service import LeadRef, format_note_entry
from app.services.mapping_service import MappingService
from app.services.session_service import SessionService
from app.services.settings_service import SettingsService
from app.services.sync_service import SyncService
from app.utils.phone import normalize_phone
from app.utils.timeutils import localnow, utcnow

log = logging.getLogger(__name__)


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_note(template: str, **values: str) -> str:
    """Render the configurable Odoo note template; unknown placeholders stay as-is."""
    return template.format_map(_SafeDict({k: (v or "-") for k, v in values.items()}))


class ResultService:
    def __init__(self, db: Database, settings: SettingsService, mappings: MappingService, sync: SyncService,
                 sessions: SessionService) -> None:
        self.db = db
        self.settings = settings
        self.mappings = mappings
        self.sync = sync
        self.sessions = sessions
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _ref_code(key: str) -> str:
        return "KLA-" + "".join(ch for ch in key if ch.isalnum())[:10].upper()

    def _validate(self, inp: ResultIn) -> None:
        if inp.result_code == "FOLLOW_UP" and not inp.followup_date:
            raise AgentError("FOLLOWUP_DATE_REQUIRED", "حدد تاريخ المتابعة.")
        for value, label in ((inp.followup_date, "تاريخ المتابعة"), (inp.subscription_expiry, "تاريخ انتهاء الاشتراك")):
            if value:
                try:
                    datetime.strptime(value, "%Y-%m-%d")
                except ValueError as exc:
                    raise AgentError("BAD_DATE", f"صيغة {label} غير صحيحة.") from exc

    def _response(self, row: CallResult, *, duplicate: bool = False) -> dict:
        s = self.settings.get()
        ok_steps = {"success", "dry_run", "skipped", "nochange"}
        all_ok = row.odoo_note_status in ok_steps and row.sheet_status in ok_steps
        if row.dry_run:
            message = "Dry Run: لم يتم تعديل Odoo أو Google Sheet. هذه معاينة لما كان سيتم."
        elif all_ok:
            message = "تم حفظ النتيجة في Odoo وGoogle Sheet"
        else:
            message = "تم الحفظ جزئيًا؛ راجع التنبيهات. يمكنك إعادة المحاولة من سجل المتابعات."
        return {
            "result_id": row.id, "status": row.status, "dry_run": row.dry_run, "duplicate": duplicate,
            "odoo_note_status": row.odoo_note_status, "odoo_activity_status": row.odoo_activity_status,
            "sheet_status": row.sheet_status, "warnings": row.warnings or [], "errors": row.errors or [],
            "preview": row.preview or {}, "message": message,
            "next_delay": s.next_lead_delay_seconds if s.auto_load_next else None,
        }

    # ------------------------------------------------------------------- save
    async def save(self, inp: ResultIn) -> dict:
        with self.db.session() as s:
            existing = CallResultRepository(s).by_key(inp.idempotency_key)
        if existing:
            return self._response(existing, duplicate=True)
        lock_key = inp.fingerprint or f"odoo:{inp.odoo_lead_id}" or inp.idempotency_key
        async with self._locks[lock_key]:
            with self.db.session() as s:
                existing = CallResultRepository(s).by_key(inp.idempotency_key)
            if existing:
                return self._response(existing, duplicate=True)
            return await self._save_locked(inp)

    async def _save_locked(self, inp: ResultIn) -> dict:
        s = self.settings.get()
        self._validate(inp)
        status_value = self.mappings.status_sheet_value(inp.result_code)
        result_label = self.mappings.status_label(inp.result_code)

        with self.db.session() as db:
            cache = LeadCacheRepository(db).get(inp.fingerprint) if inp.fingerprint else None
        if inp.fingerprint and cache is None:
            raise AgentError("LEAD_NOT_IN_QUEUE", "لم يتم العثور على العميل في قائمة العمل. حدّث القائمة ثم أعد المحاولة.",
                             actions=["retry"])
        manual = cache is None
        company = cache.company_name if cache else inp.manual_company
        phone = cache.phone_raw if cache else inp.manual_phone
        phone_norm = cache.phone_norm if cache else normalize_phone(inp.manual_phone)
        odoo_id = inp.odoo_lead_id or (cache.odoo_lead_id if cache else None)
        dry_run = s.dry_run or inp.preview_only
        update_sheet = inp.update_sheet and not manual  # manual mode never writes the sheet
        warnings: list[str] = []
        if inp.update_sheet and manual:
            warnings.append("وضع البحث اليدوي: لن يتم تحديث Google Sheet لأن العميل غير مربوط بصف مؤكد.")

        # Duplicate protection (same lead + same result within the window).
        if not dry_run and s.duplicate_window_seconds:
            since = utcnow() - timedelta(seconds=s.duplicate_window_seconds)
            with self.db.session() as db:
                dup = CallResultRepository(db).recent_same(inp.fingerprint, phone_norm, inp.result_code, since)
            if dup:
                return self._response(dup, duplicate=True)

        now = localnow()
        ref = self._ref_code(inp.idempotency_key)
        followup_at = f"{inp.followup_date} {inp.followup_time}".strip() if inp.result_code == "FOLLOW_UP" else ""
        note_text = inp.note.strip()
        if inp.result_code == "NOT_INTERESTED" and inp.not_subscribed_reason.strip():
            note_text = (note_text + "\n" if note_text else "") + f"سبب عدم الاشتراك: {inp.not_subscribed_reason.strip()}"
        if followup_at:
            note_text = (note_text + "\n" if note_text else "") + f"موعد المتابعة: {followup_at}" + (
                f" – {inp.followup_note.strip()}" if inp.followup_note.strip() else "")
        source_value = inp.source_value.strip()
        odoo_body = render_note(
            s.odoo_note_template, result=result_label, notes=note_text, date=now.strftime("%d/%m/%Y %H:%M"),
            source=source_value or (cache.sheet_source if cache else ""), ref=ref, owner=s.agent_owner,
            company=company, phone=phone,
        )
        if inp.trial_registered.strip():
            odoo_body += f"\nالتسجيل بالنسخة التجريبية: {inp.trial_registered.strip()}"
        if "{ref}" not in s.odoo_note_template:
            odoo_body += f"\n{ref}"  # the ref is required for de-duplication

        sheet_changes: dict[str, str] = {"followup_status": status_value}
        if source_value:
            sheet_changes["source"] = source_value
        if inp.not_subscribed_reason.strip():
            sheet_changes["not_subscribed_reason"] = inp.not_subscribed_reason.strip()
        if inp.trial_registered.strip():
            sheet_changes["trial_registered"] = inp.trial_registered.strip()
        if inp.result_code == "SUBSCRIBED" and inp.subscription_expiry:
            sheet_changes["subscription_expiry"] = inp.subscription_expiry
        entry_text = note_text or result_label
        note_entry = format_note_entry(entry_text, s.agent_owner, now, s.note_stamp_format)

        activity = None
        if inp.result_code == "FOLLOW_UP" and inp.followup_date:
            activity = {"date_deadline": inp.followup_date,
                        "summary": f"متابعة {company}".strip() + (f" {inp.followup_time}" if inp.followup_time else ""),
                        "note": inp.followup_note or note_text}

        row = CallResult(
            idempotency_key=inp.idempotency_key, fingerprint=inp.fingerprint if not manual else None,
            sheet_row=cache.sheet_row if cache else None, company_name=company, phone=phone, phone_norm=phone_norm,
            odoo_lead_id=odoo_id, result_code=inp.result_code, note=inp.note, source_value=source_value,
            not_subscribed_reason=inp.not_subscribed_reason, subscription_expiry=inp.subscription_expiry,
            followup_at=followup_at, followup_note=inp.followup_note, call_started_at=inp.call_started_at,
            duration_seconds=((inp.call_ended_at - inp.call_started_at).total_seconds()
                              if inp.call_started_at and inp.call_ended_at else None),
            dry_run=dry_run, manual_mode=manual, update_sheet=update_sheet, add_odoo_note=inp.add_odoo_note,
            status="processing", errors=[], warnings=warnings,
        )
        preview: dict = {"odoo_note": odoo_body if inp.add_odoo_note and odoo_id else "",
                         "activity": activity, "sheet": [], "sheet_error": "", "ref": ref,
                         "note_entry": note_entry}
        lead_ref = LeadRef(cache.fingerprint, cache.sheet_row, cache.company_name, cache.phone_norm) if cache else None

        if dry_run:
            if update_sheet and lead_ref:
                step = await asyncio.to_thread(self.sync.plan_sheet, lead_ref, sheet_changes, note_entry)
                if step.plan:
                    preview["sheet"] = [c.to_dict() for c in step.plan.changes]
                    warnings += step.warnings
                    if not inp.preview_only:  # a Dry Run save is audited; a plain preview is not
                        self.sync.sheets.apply(step.plan, dry_run=True, action_id=inp.idempotency_key)
                else:
                    preview["sheet_error"] = step.message
            if inp.preview_only:
                return {"preview": preview, "warnings": warnings, "dry_run": True, "status": "preview"}
            if inp.add_odoo_note and odoo_id:
                await self.sync.odoo_note(odoo_id, odoo_body, ref, dry_run=True, action_id=inp.idempotency_key)
            if activity and odoo_id:
                await self.sync.odoo_activity(odoo_id, activity["date_deadline"], activity["summary"],
                                              activity["note"], dry_run=True, action_id=inp.idempotency_key)
            row.odoo_note_status = "dry_run" if inp.add_odoo_note and odoo_id else "skipped"
            row.odoo_activity_status = "dry_run" if activity and odoo_id else "skipped"
            row.sheet_status = ("blocked" if preview["sheet_error"] else "dry_run") if update_sheet else "skipped"
            row.status = "done"
            row.preview, row.warnings = preview, warnings
            self._maybe_save_mapping(inp)
            return self._finish(row, inp, company)

        # ---- real execution: Odoo first, then Google Sheet (as in the workflow)
        errors: list[str] = []
        if inp.add_odoo_note and odoo_id:
            step = await self.sync.odoo_note(odoo_id, odoo_body, ref, dry_run=False, action_id=inp.idempotency_key)
            row.odoo_note_status = step.status
            if step.status == "failed":
                errors.append(step.message)
        else:
            row.odoo_note_status = "skipped"
            if inp.add_odoo_note and not odoo_id:
                warnings.append("لم يتم ربط العميل بـLead في Odoo؛ لم تتم إضافة Log Note.")
        if activity and odoo_id:
            step = await self.sync.odoo_activity(odoo_id, activity["date_deadline"], activity["summary"],
                                                 activity["note"], dry_run=False, action_id=inp.idempotency_key)
            row.odoo_activity_status = step.status
            if step.status == "failed":
                warnings.append("تعذر إنشاء Activity في Odoo (Activity creation failed)؛ تم إكمال الملاحظة وتحديث Sheet.")
        if update_sheet and lead_ref:
            step = await asyncio.to_thread(self.sync.update_sheet, lead_ref, sheet_changes, note_entry,
                                           dry_run=False, action_id=inp.idempotency_key)
            row.sheet_status = step.status
            warnings += step.warnings
            if step.plan:
                preview["sheet"] = [c.to_dict() for c in step.plan.changes]
            if step.status in ("failed", "blocked"):
                errors.append(step.message)
        else:
            row.sheet_status = "skipped"
        ok = {"success", "skipped", "nochange"}
        if row.odoo_note_status in ok and row.sheet_status in ok:
            row.status = "done"
        elif row.odoo_note_status in ok or row.sheet_status in ok:
            row.status = "partial"
        else:
            row.status = "failed"
        row.errors, row.warnings, row.preview = errors, warnings, preview
        self._maybe_save_mapping(inp)
        return self._finish(row, inp, company, status_value if row.sheet_status == "success" else None)

    def _maybe_save_mapping(self, inp: ResultIn) -> None:
        if inp.save_source_mapping and inp.source_odoo_value.strip() and inp.source_value.strip():
            self.mappings.save_source(inp.source_odoo_value, inp.source_value)

    def _finish(self, row: CallResult, inp: ResultIn, company: str, new_status: str | None = None) -> dict:
        with self.db.session() as db:
            CallResultRepository(db).add(row)
            if row.fingerprint and new_status:
                cache = LeadCacheRepository(db).get(row.fingerprint)
                if cache:
                    cache.followup_status = new_status
        if row.fingerprint and row.status != "failed":
            self.sessions.mark_completed(row.fingerprint)
        for err in row.errors or []:
            self.sessions.add_error(row.fingerprint, err)
        log.info("Result saved id=%s lead=%s code=%s status=%s dry_run=%s", row.id, company, row.result_code,
                 row.status, row.dry_run)
        return self._response(row)

    # ------------------------------------------------------------------ retry
    async def retry(self, result_id: int) -> dict:
        """Re-run only the failed external steps of a saved result."""
        with self.db.session() as db:
            row = CallResultRepository(db).get(result_id)
        if row is None:
            raise AgentError("NOT_FOUND", "السجل غير موجود.")
        if row.dry_run:
            raise AgentError("DRY_RUN_RESULT", "هذا السجل تم في وضع Dry Run؛ لا يوجد ما يعاد تنفيذه.")
        s = self.settings.get()
        if s.dry_run:
            raise AgentError("DRY_RUN_ON", "أوقف Dry Run من الإعدادات أولًا لإعادة تنفيذ التحديثات.", actions=["open_settings"])
        preview = dict(row.preview or {})
        errors: list[str] = []
        warnings = list(row.warnings or [])
        if row.odoo_note_status == "failed" and row.odoo_lead_id and preview.get("odoo_note"):
            step = await self.sync.odoo_note(row.odoo_lead_id, preview["odoo_note"], preview.get("ref", ""),
                                             dry_run=False, action_id=row.idempotency_key)
            row.odoo_note_status = step.status
            if step.status == "failed":
                errors.append(step.message)
        activity = preview.get("activity")
        if row.odoo_activity_status == "failed" and row.odoo_lead_id and activity:
            step = await self.sync.odoo_activity(row.odoo_lead_id, activity["date_deadline"], activity["summary"],
                                                 activity["note"], dry_run=False, action_id=row.idempotency_key)
            row.odoo_activity_status = step.status
        if row.sheet_status in ("failed", "blocked") and row.fingerprint:
            with self.db.session() as db:
                cache = LeadCacheRepository(db).get(row.fingerprint)
            if cache:
                changes = {c["key"]: c["new"] for c in preview.get("sheet", []) if c["key"] != "notes"}
                if not changes:
                    changes = {"followup_status": self.mappings.status_sheet_value(row.result_code)}
                    if row.source_value:
                        changes["source"] = row.source_value
                entry = preview.get("note_entry") or format_note_entry(
                    row.note or self.mappings.status_label(row.result_code), s.agent_owner, localnow(),
                    s.note_stamp_format)
                ref = LeadRef(cache.fingerprint, cache.sheet_row, cache.company_name, cache.phone_norm)
                step = await asyncio.to_thread(self.sync.update_sheet, ref, changes, entry, dry_run=False,
                                               action_id=row.idempotency_key)
                row.sheet_status = step.status
                warnings += [w for w in step.warnings if w not in warnings]
                if step.status in ("failed", "blocked"):
                    errors.append(step.message)
        ok = {"success", "skipped", "nochange", "dry_run"}
        row.status = "done" if row.odoo_note_status in ok and row.sheet_status in ok else "partial"
        row.errors, row.warnings = errors, warnings
        with self.db.session() as db:
            db.merge(row)
        return self._response(row)
