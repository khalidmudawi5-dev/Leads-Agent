"""WhatsApp from the dashboard: a template is filled in, WhatsApp opens with the text ready
(``https://wa.me/<number>?text=…``) and the user presses Send there. The agent never sends by itself.

When ``whatsapp_log`` is on, the message is also recorded: an Odoo Log note and a short line in the
sheet's notes column (Dry Run: preview only). The follow-up status in the sheet is not changed.

A template can carry an image or a PDF (see ``attachment_service``): it is put on the clipboard when
WhatsApp opens and the user pastes it into the chat (Ctrl+V).
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from urllib.parse import quote

from app.adapters.odoo.base import OdooLead
from app.db import Database
from app.errors import AgentError
from app.models import OutreachMessage
from app.repositories.lead_repo import LeadCacheRepository
from app.services.attachment_service import AttachmentService
from app.services.call_result_service import _SafeDict, note_signature
from app.services.google_sheets_service import LeadRef, format_note_entry
from app.services.settings_service import SettingsService
from app.services.sync_service import SyncService
from app.utils.phone import check_phone
from app.utils.timeutils import localnow

log = logging.getLogger(__name__)


def render_template(text: str, **values: str) -> str:
    return text.format_map(_SafeDict({k: v or "" for k, v in values.items()})).strip()


def wa_url(tel: str, text: str) -> str:
    digits = re.sub(r"\D", "", tel)
    return f"https://wa.me/{digits}?text={quote(text)}"


class WhatsAppService:
    def __init__(self, db: Database, settings: SettingsService, sync: SyncService,
                 attachments: AttachmentService) -> None:
        self.db = db
        self.settings = settings
        self.sync = sync
        self.attachments = attachments

    def _cache(self, fingerprint: str):
        with self.db.session() as s:
            row = LeadCacheRepository(s).get(fingerprint)
        if row is None:
            raise AgentError("LEAD_NOT_IN_QUEUE", "العميل غير موجود في قائمة العمل. حدّث القائمة.", actions=["retry"])
        return row

    def options(self, fingerprint: str) -> dict:
        """Numbers to choose from and the templates filled in for this customer."""
        c = self._cache(fingerprint)
        s = self.settings.get()
        odoo = OdooLead.from_dict(c.odoo_data) if c.odoo_data else None
        numbers: list[dict] = []
        for label, raw in (("Mobile في Odoo", odoo.mobile if odoo else ""), ("Phone في Odoo", odoo.phone if odoo else ""),
                           ("Google Sheet", c.phone_raw)):
            chk = check_phone(raw)
            if chk["tel"] and chk["kind"] in ("mobile", "international") and all(n["tel"] != chk["tel"] for n in numbers):
                numbers.append({"label": label, "raw": raw.strip(), "tel": chk["tel"]})
        values = {"company": c.company_name, "owner": s.agent_owner, "contact": odoo.contact_name if odoo else "",
                  "date": localnow().strftime("%d/%m/%Y")}
        templates = [{"name": t.get("name", ""), "text": render_template(t.get("text", ""), **values),
                      "file": self.attachments.describe(t.get("file", ""), t.get("file_name", ""))}
                     for t in s.whatsapp_templates if (t.get("text") or "").strip() or t.get("file")]
        return {"numbers": numbers, "templates": templates, "log": s.whatsapp_log, "dry_run": s.dry_run}

    async def send(self, fingerprint: str, tel: str, text: str, template: str = "", log_it: bool | None = None,
                   file_id: str = "", file_name: str = "", clipboard: bool = True) -> dict:
        c = self._cache(fingerprint)
        s = self.settings.get()
        text = text.strip()
        file = self.attachments.describe(file_id, file_name) if file_id else None
        if file_id and file is None:
            raise AgentError("FILE_NOT_FOUND", "مرفق القالب غير موجود. ارفعه مرة أخرى من الإعدادات › واتساب.")
        if not text and not file:
            raise AgentError("WA_EMPTY", "اكتب نص الرسالة.")
        chk = check_phone(tel)
        if not chk["tel"]:
            raise AgentError("PHONE_INVALID", f"رقم الواتساب ({tel or '—'}) غير صحيح.")
        log_it = s.whatsapp_log if log_it is None else log_it
        dry_run = s.dry_run
        action_id = uuid.uuid4().hex
        row = OutreachMessage(fingerprint=c.fingerprint, company_name=c.company_name, phone=chk["raw"],
                              odoo_lead_id=c.odoo_lead_id, template=template[:100], text=text, dry_run=dry_run)
        warnings: list[str] = []
        if log_it:
            if c.odoo_lead_id:
                body = f"تم إرسال رسالة واتساب إلى {chk['raw']}:\n{text}"
                if file:
                    body += f"\nمرفق: {file['name']}"
                step = await self.sync.odoo_note(c.odoo_lead_id, body, note_signature(body), dry_run=dry_run,
                                                 action_id=action_id)
                row.odoo_status = step.status
                if step.status == "failed":
                    warnings.append(f"لم تُسجّل الرسالة في Odoo: {step.message}")
            else:
                warnings.append("العميل غير مربوط بـLead في Odoo؛ لم تُسجّل الرسالة في Odoo.")
            label = f"واتساب: {template or 'رسالة'}" + (f" + {'صورة' if file['kind'] == 'image' else 'PDF'}" if file else "")
            entry = format_note_entry(label, s.agent_owner, localnow(), s.note_stamp_format)
            ref = LeadRef(c.fingerprint, c.sheet_row, c.company_name, c.phone_norm)
            step = await asyncio.to_thread(self.sync.update_sheet, ref, {}, entry, dry_run=dry_run, action_id=action_id)
            row.sheet_status = step.status
            if step.status in ("failed", "blocked"):
                warnings.append(f"لم تُسجّل الرسالة في Google Sheet: {step.message}")
        with self.db.session() as db:
            db.add(row)
        if file:
            # Last, right before the page opens WhatsApp, so nothing else replaces the clipboard meanwhile.
            file["copied"] = clipboard and await asyncio.to_thread(self.attachments.copy_to_clipboard, file["id"])
        log.info("WhatsApp opened for %s (%s) dry_run=%s logged=%s", c.company_name, chk["tel"], dry_run, log_it)
        return {"url": wa_url(chk["tel"], text), "dry_run": dry_run, "logged": log_it,
                "odoo_status": row.odoo_status, "sheet_status": row.sheet_status, "warnings": warnings, "file": file}
