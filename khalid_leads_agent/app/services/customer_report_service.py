"""Customer list by follow-up status (e.g. «مهتم», «لم يتم الرد»), enriched from Odoo, as Excel or PDF.

Read-only: the sheet rows of the agent owner are filtered by «حالة المتابعة»; company, contact, e-mail,
phones, stage and UTM Source are then read from Odoo (linked leads in one batch, the others matched by
phone / exact company like the queue). Nothing is written to Google Sheets or Odoo.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.adapters.odoo.base import OdooLead
from app.config import EMPTY_TOKEN
from app.db import Database
from app.errors import AgentError
from app.repositories.lead_repo import LeadCacheRepository
from app.services.google_sheets_service import NOTE_SEPARATOR
from app.services.lead_queue_service import LeadQueueService
from app.services.odoo_service import OdooService
from app.services.settings_service import SettingsService
from app.utils.phone import format_phone
from app.utils.text import normalize_text
from app.utils.timeutils import localnow
from app.utils.xlsx import write_xlsx

log = logging.getLogger(__name__)

MAX_SEARCH = 150  # unlinked customers searched in Odoo per report (each is one search)
CACHE_SECONDS = 300
COLUMNS = [("company", "المنشأة"), ("contact", "جهة الاتصال"), ("phone", "الجوال"), ("email", "الإيميل"),
           ("status", "حالة المتابعة"), ("utm_source", "المصدر (UTM Source)"), ("stage", "المرحلة في Odoo"),
           ("salesperson", "المسؤول في Odoo"), ("last_note", "آخر ملاحظة"), ("row", "صف Sheet"),
           ("odoo_url", "رابط Odoo")]
_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def last_note(notes: str) -> str:
    text = (notes or "").strip()
    if not text:
        return ""
    parts = [p.strip() for p in text.replace("\r", "").split("\n\n") if p.strip()]
    last = parts[-1] if parts else text
    last = last.split(NOTE_SEPARATOR)[-1].strip()
    last = re.sub(r"^\[[^\]\n]{0,60}\]\s*", "", last)  # an old "[date - name]" stamp
    return " ".join(last.split())[:300]


class CustomerReportService:
    def __init__(self, db: Database, settings: SettingsService, queue: LeadQueueService, odoo: OdooService) -> None:
        self.db = db
        self.settings = settings
        self.queue = queue
        self.odoo = odoo
        self._cache: tuple[tuple, float, dict] | None = None
        self._jinja = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=select_autoescape(["html"]))

    @staticmethod
    def _keys(statuses: list[str]) -> set[str]:
        return {"" if v.strip() in ("", EMPTY_TOKEN) else normalize_text(v) for v in statuses}

    async def build(self, statuses: list[str], use_odoo: bool = True, search_unlinked: bool = True,
                    fresh: bool = True) -> dict:
        if not statuses:
            raise AgentError("NO_STATUS", "اختر حالة متابعة واحدة على الأقل.")
        key = (tuple(sorted(self._keys(statuses))), use_odoo, search_unlinked)
        if not fresh and self._cache and self._cache[0] == key and time.monotonic() - self._cache[1] < CACHE_SECONDS:
            return self._cache[2]
        warnings: list[str] = []
        try:
            await asyncio.to_thread(self.queue.refresh)
        except AgentError as exc:
            if not self.queue.loaded:
                raise
            warnings.append(f"تعذر تحديث البيانات من Google Sheet؛ استُخدمت آخر نسخة. ({exc.message_ar})")
        wanted = self._keys(statuses)
        leads = [lead for lead in self.queue.owner_leads if normalize_text(lead.followup_status) in wanted]
        leads.sort(key=lambda lead: (normalize_text(lead.followup_status), lead.sheet_row))
        with self.db.session() as s:
            repo = LeadCacheRepository(s)
            linked = {lead.fingerprint: c.odoo_lead_id for lead in leads
                      if (c := repo.get(lead.fingerprint)) is not None and c.odoo_lead_id}
        odoo: dict[str, OdooLead] = {}
        odoo_read = False
        if use_odoo and leads:
            try:
                odoo, more = await self._read_odoo(leads, linked, search_unlinked)
                warnings += more
                odoo_read = True
            except AgentError as exc:
                warnings.append(f"لم تتم قراءة بيانات Odoo: {exc.message_ar} — التقرير من Google Sheet فقط.")
        rows = []
        for lead in leads:
            o = odoo.get(lead.fingerprint)
            phones = [p for p in ((o.phone, o.mobile) if o else ()) if p and p.strip()]
            rows.append({
                "company": (o.company_name if o and o.company_name else "") or lead.company_name,
                "contact": o.contact_name if o else "",
                "phone": " / ".join(dict.fromkeys(format_phone(p) for p in phones)) or format_phone(lead.phone_raw),
                "email": o.email if o else "",
                "status": lead.followup_status.strip() or "(فارغة)",
                "utm_source": (o.utm_source if o and o.utm_source else "") or lead.source,
                "stage": o.stage if o else "",
                "salesperson": o.salesperson if o else "",
                "last_note": last_note(lead.notes),
                "row": lead.sheet_row,
                "odoo_url": self.settings.get().lead_url(o.id) if o and o.id else "",
                "in_odoo": bool(o),
            })
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        report = {
            "statuses": [("(فارغة)" if v.strip() in ("", EMPTY_TOKEN) else v.strip()) for v in statuses],
            "rows": rows, "counts": counts, "total": len(rows), "warnings": warnings,
            "odoo_read": odoo_read, "in_odoo": sum(1 for r in rows if r["in_odoo"]),
            "with_email": sum(1 for r in rows if r["email"]),
            "generated_at": localnow().strftime("%d/%m/%Y %H:%M"), "owner": self.settings.get().agent_owner,
            "columns": [{"key": k, "label": label} for k, label in COLUMNS],
        }
        self._cache = (key, time.monotonic(), report)
        return report

    async def _read_odoo(self, leads, linked: dict[str, int], search_unlinked: bool) -> tuple[dict[str, OdooLead], list[str]]:
        warnings: list[str] = []
        by_id = {lead.id: lead for lead in await self.odoo.adapter.read_leads(sorted(set(linked.values())))}
        out = {fp: by_id[i] for fp, i in linked.items() if i in by_id}
        if not search_unlinked:
            return out, warnings
        todo = [lead for lead in leads if lead.fingerprint not in out]
        if len(todo) > MAX_SEARCH:
            warnings.append(f"تم البحث في Odoo عن أول {MAX_SEARCH} عميل غير مربوط فقط (من {len(todo)}).")
            todo = todo[:MAX_SEARCH]
        found_ids: dict[str, int] = {}
        for lead in todo:
            try:
                match = await self.odoo.find_match(lead.company_name, lead.phone_norm)
            except AgentError as exc:
                if exc.code == "ODOO_LOGIN_REQUIRED":
                    raise
                log.info("Report: search failed for row %s: %s", lead.sheet_row, exc.message_ar)
                continue
            if match.status == "matched" and match.lead and match.lead.id:
                found_ids[lead.fingerprint] = match.lead.id
                out[lead.fingerprint] = match.lead
        # Search results may lack fields (UI fallback): read the found leads in one batch.
        if found_ids:
            fresh = {lead.id: lead for lead in await self.odoo.adapter.read_leads(sorted(set(found_ids.values())))}
            out.update({fp: fresh[i] for fp, i in found_ids.items() if i in fresh})
        return out, warnings

    # ---------------------------------------------------------------- export
    def filename(self, report: dict, ext: str) -> str:
        names = "-".join(s.replace("/", "-").replace(" ", "_") for s in report["statuses"])[:60] or "customers"
        return f"customers-{names}-{localnow().strftime('%Y%m%d-%H%M')}.{ext}"

    def to_xlsx(self, report: dict) -> bytes:
        head = [label for _, label in COLUMNS]
        rows = [head] + [[r[k] for k, _ in COLUMNS] for r in report["rows"]]
        summary = [["البيان", "القيمة"], ["الحالات", "، ".join(report["statuses"])],
                   ["عدد العملاء", report["total"]], ["موجود في Odoo", report["in_odoo"]],
                   ["لديه إيميل", report["with_email"]], ["تاريخ التقرير", report["generated_at"]],
                   ["المسؤول", report["owner"]]]
        summary += [[f"الحالة: {k}", v] for k, v in report["counts"].items()]
        return write_xlsx([("العملاء", rows, [30, 20, 24, 28, 16, 22, 16, 16, 50, 9, 40]),
                           ("الملخص", summary, [26, 40])])

    def to_html(self, report: dict, auto_print: bool = False) -> str:
        return self._jinja.get_template("report_customers_print.html").render(r=report, auto_print=auto_print)

    async def to_pdf(self, report: dict) -> bytes:
        return await self.odoo.adapter.render_pdf(self.to_html(report))

