"""Orchestrates the daily workflow: queue → Odoo match → open/call → skip/refresh → manual mode."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta

from app.adapters.odoo.base import OdooLead
from app.config import EMPTY_TOKEN
from app.db import Database
from app.errors import AgentError
from app.models import LeadCache
from app.repositories.lead_repo import LeadCacheRepository, SkipRepository
from app.repositories.result_repo import CallResultRepository
from app.services.google_sheets_service import SheetService
from app.services.lead_queue_service import LeadQueueService
from app.services.mapping_service import MappingService
from app.services.odoo_service import MatchResult, OdooService
from app.services.session_service import SessionService
from app.services.settings_service import SettingsService
from app.utils.phone import check_phone, normalize_phone, phones_match, to_ascii_digits
from app.utils.text import normalize_company, normalize_text
from app.utils.timeutils import end_of_local_day_utc, start_of_local_day_utc, utcnow

log = logging.getLogger(__name__)


FIELD_LABEL = {"phone": "Phone", "mobile": "Mobile", "sheet": "Google Sheet"}


def phone_report(sheet_raw: str, odoo: OdooLead | None) -> dict:
    """Which number to call and what is wrong with the numbers (deterministic, no guessing)."""
    sheet = check_phone(sheet_raw)
    fields: list[dict] = []
    if odoo is not None:
        for name in ("phone", "mobile"):
            value = getattr(odoo, name) or ""
            if value.strip():
                chk = check_phone(value)
                chk.update(field=name, matches_sheet=bool(sheet["valid"] and chk["valid"] and chk["norm"] == sheet["norm"]))
                fields.append(chk)
    # Target: the Odoo number equal to the sheet number, else the first valid one, else the first one.
    target = (next((f for f in fields if f["matches_sheet"]), None)
              or next((f for f in fields if f["severity"] != "error"), None)
              or (fields[0] if fields else None))
    problems: list[str] = []
    for f in fields:
        for issue in f["issues"]:
            problems.append(f"رقم {FIELD_LABEL[f['field']]} في Odoo ({f['raw']}): {issue}")
    if odoo is not None and not fields:
        problems.append("لا يوجد رقم هاتف أو جوال على العميل في Odoo")
    if sheet["valid"] and fields and not any(f["matches_sheet"] for f in fields):
        problems.append(f"رقم Odoo يختلف عن رقم Google Sheet ({sheet['raw']})")
    if target is None or target["severity"] == "error":
        status = "error"
    elif problems:
        status = "warning"
    else:
        status = "ok"
    return {"status": status, "problems": problems, "sheet": sheet, "fields": fields,
            "target": {k: target[k] for k in ("field", "raw", "tel", "severity", "kind", "issues")} if target else None}


def last_note(notes: str) -> str:
    chunks = [c.strip() for c in re.split(r"\n\s*\n", notes or "") if c.strip()]
    return chunks[-1][:600] if chunks else ""


class LeadWorkflowService:
    def __init__(self, db: Database, settings: SettingsService, sheets: SheetService, queue: LeadQueueService,
                 sessions: SessionService, odoo: OdooService, mappings: MappingService) -> None:
        self.db = db
        self.settings = settings
        self.sheets = sheets
        self.queue = queue
        self.sessions = sessions
        self.odoo = odoo
        self.mappings = mappings

    # ------------------------------------------------------------ helpers
    def _cache(self, fingerprint: str) -> LeadCache:
        with self.db.session() as s:
            row = LeadCacheRepository(s).get(fingerprint)
        if row is None:
            raise AgentError("LEAD_NOT_IN_QUEUE", "العميل غير موجود في قائمة العمل. حدّث القائمة.", actions=["retry"])
        return row

    def _update_cache(self, fingerprint: str, **fields) -> None:
        with self.db.session() as s:
            row = LeadCacheRepository(s).get(fingerprint)
            if row:
                for k, v in fields.items():
                    setattr(row, k, v)

    def lead_view(self, fingerprint: str) -> dict:
        c = self._cache(fingerprint)
        s = self.settings.get()
        odoo = OdooLead.from_dict(c.odoo_data) if c.odoo_data else None
        resolution = self.mappings.resolve_source(odoo)
        prefill = resolution.sheet_value if (resolution.mapped and s.auto_sync_source) else c.sheet_source
        return {
            "fingerprint": c.fingerprint, "sheet_row": c.sheet_row, "company_name": c.company_name,
            "phone": c.phone_raw, "phone_norm": c.phone_norm, "owner": c.owner,
            "followup_status": c.followup_status, "sheet_source": c.sheet_source, "notes": c.notes,
            "last_note": last_note(c.notes), "odoo_lead_id": c.odoo_lead_id, "odoo": c.odoo_data,
            "match_status": c.match_status, "candidates": c.match_candidates or [],
            "source": {**resolution.to_dict(), "prefill": prefill, "sheet_current": c.sheet_source},
            "phone_check": phone_report(c.phone_raw, odoo) if odoo else None,
        }

    def stats(self) -> dict:
        since = start_of_local_day_utc()
        with self.db.session() as s:
            counts = CallResultRepository(s).counts_since(since)
            match_errors = LeadCacheRepository(s).count_by_match_status(("not_found", "error"))
        pending = len(self.queue.queue()) if self.queue.loaded else 0
        return {
            "owner_total": len(self.queue.owner_leads), "pending": pending,
            "contacted": sum(counts.values()), "no_answer": counts.get("NO_ANSWER", 0),
            "interested": counts.get("INTERESTED", 0), "not_interested": counts.get("NOT_INTERESTED", 0),
            "follow_up": counts.get("FOLLOW_UP", 0), "subscribed": counts.get("SUBSCRIBED", 0),
            "invalid": counts.get("INVALID_NUMBER", 0), "match_errors": match_errors,
        }

    async def _refresh(self, strict: bool) -> list[str]:
        """Reload the sheet. With a cached queue, Google errors become warnings."""
        try:
            await asyncio.to_thread(self.queue.refresh)
            return []
        except AgentError as exc:
            if strict or not self.queue.loaded:
                raise
            return [f"تعذر تحديث القائمة من Google Sheet؛ يتم استخدام آخر نسخة. ({exc.message_ar})"]

    def _payload(self, fingerprint: str | None, warnings: list[str] | None = None) -> dict:
        sess = self.sessions.ensure()
        return {
            "lead": self.lead_view(fingerprint) if fingerprint else None,
            "done": fingerprint is None,
            "stats": self.stats(),
            "session": self.sessions.to_dict(sess),
            "warnings": warnings or [],
        }

    # ------------------------------------------------------------- queue
    async def current(self) -> dict:
        warnings: list[str] = []
        if not self.queue.loaded:
            warnings = await self._refresh(strict=True)
        sess = self.sessions.ensure()
        fp = sess.current_fingerprint
        if fp and self.queue.find(fp):
            return self._payload(fp, warnings)
        return await self.next(refresh=False)

    async def next(self, refresh: bool = True) -> dict:
        warnings = await self._refresh(strict=False) if refresh else []
        queue = self.queue.queue()
        if not queue:
            self.sessions.set_current(None, None)
            return self._payload(None, warnings)
        lead = queue[0]
        self.sessions.set_current(lead.fingerprint, lead.sheet_row)
        return self._payload(lead.fingerprint, warnings)

    async def skip(self, fingerprint: str, mode: str, reason: str = "") -> dict:
        c = self._cache(fingerprint)
        sess = self.sessions.ensure()
        until = {
            "10m": utcnow() + timedelta(minutes=10),
            "30m": utcnow() + timedelta(minutes=30),
            "today": end_of_local_day_utc(),
            "session": None,
        }[mode]
        with self.db.session() as s:
            SkipRepository(s).add(fingerprint=fingerprint, session_id=sess.id, company_name=c.company_name,
                                  phone=c.phone_raw, sheet_row=c.sheet_row, mode=mode, until=until, reason=reason)
        if mode == "session":
            self.sessions.mark_skipped(fingerprint)
        elif sess.current_fingerprint == fingerprint:
            self.sessions.set_current(None, None)
        return await self.next(refresh=False)

    def restore_skip(self, skip_id: int) -> None:
        with self.db.session() as s:
            row = SkipRepository(s).deactivate(skip_id)
        if row:
            self.sessions.unskip(row.fingerprint)

    # -------------------------------------------------------------- odoo
    def _store_match(self, fingerprint: str, match: MatchResult, lead: OdooLead | None = None) -> None:
        if match.status == "matched":
            chosen = lead or match.lead
            self._update_cache(fingerprint, odoo_lead_id=chosen.id if chosen else None,
                               odoo_data=chosen.to_dict() if chosen else None, match_status="matched",
                               match_candidates=None)
        else:
            self._update_cache(fingerprint, odoo_lead_id=None, odoo_data=None, match_status=match.status,
                               match_candidates=[c.to_dict() for c in match.candidates])

    async def _load_lead(self, lead: OdooLead, open_in_browser: bool) -> tuple[OdooLead, list[str]]:
        warnings: list[str] = []
        try:
            if open_in_browser or lead.id is None:
                return await self.odoo.adapter.open_lead(lead), warnings
            return await self.odoo.adapter.get_lead(lead.id), warnings
        except AgentError as exc:
            if exc.code == "ODOO_LOGIN_REQUIRED":
                raise
            warnings.append(exc.message_ar)
            return lead, warnings

    async def search_odoo(self, fingerprint: str, query: str = "") -> dict:
        c = self._cache(fingerprint)
        company, phone = c.company_name, c.phone_norm
        if query.strip():
            digits = re.sub(r"\D", "", to_ascii_digits(query))
            company, phone = ("", normalize_phone(query)) if len(digits) >= 7 else (query.strip(), "")
        try:
            match = await self.odoo.find_match(company, phone)
        except AgentError as exc:
            if exc.code != "ODOO_LOGIN_REQUIRED":
                self._update_cache(fingerprint, match_status="error")
            raise
        warnings: list[str] = []
        lead = None
        if match.status == "matched" and match.lead:
            lead, warnings = await self._load_lead(match.lead, self.settings.get().auto_open_odoo_lead)
        self._store_match(fingerprint, match, lead)
        payload = self._payload(fingerprint, warnings)
        payload["match"] = {"status": match.status, "strategy": match.strategy}
        return payload

    async def select_candidate(self, fingerprint: str, odoo_id: int | None, ui_index: int | None, ui_query: str) -> dict:
        c = self._cache(fingerprint)
        chosen = next((OdooLead.from_dict(d) for d in (c.match_candidates or [])
                       if (odoo_id is not None and d.get("id") == odoo_id)
                       or (odoo_id is None and d.get("ui_index") == ui_index)), None)
        if chosen is None:
            chosen = OdooLead(id=odoo_id, ui_index=ui_index, ui_query=ui_query)
        lead, warnings = await self._load_lead(chosen, True)
        self._store_match(fingerprint, MatchResult("matched", lead, [], "user_choice"), lead)
        return self._payload(fingerprint, warnings)

    async def open_in_odoo(self, fingerprint: str) -> dict:
        c = self._cache(fingerprint)
        if not c.odoo_lead_id:
            await self.odoo.adapter.open_url(self.settings.get().crm_url)
            return self._payload(fingerprint, ["العميل غير مربوط بـLead؛ تم فتح CRM."])
        lead = await self.odoo.adapter.open_lead(OdooLead(id=c.odoo_lead_id))
        self._update_cache(fingerprint, odoo_data=lead.to_dict())
        return self._payload(fingerprint)

    async def open_crm(self) -> None:
        await self.odoo.adapter.open_url(self.settings.get().crm_url)

    async def call(self, fingerprint: str | None = None, odoo_id: int | None = None, *, target: str = "auto",
                   force: bool = False) -> dict:
        """Start the call; Phone Link takes over from Windows.

        ``target``: auto | phone | mobile | sheet. The chosen number is checked first; a number
        that is clearly wrong is not called unless ``force`` (the user chose "call anyway").
        Fast mode hands the number to Windows directly (no browser round-trip).
        """
        sheet_phone = ""
        if fingerprint:
            c = self._cache(fingerprint)
            if not c.odoo_lead_id or not c.odoo_data:
                raise AgentError("NOT_MATCHED", "اربط العميل بـLead في Odoo أولًا (إعادة البحث).", actions=["retry"])
            lead = OdooLead.from_dict(c.odoo_data)  # already loaded: no Odoo round-trip
            sheet_phone = c.phone_raw
        elif odoo_id:
            lead = await self.odoo.adapter.get_lead(odoo_id)
        else:
            raise AgentError("NOT_MATCHED", "لا يوجد عميل محدد للاتصال.")
        assert lead.id is not None
        report = phone_report(sheet_phone, lead)
        if target == "sheet":
            if not sheet_phone:
                raise AgentError("NO_SHEET_PHONE", "لا يوجد رقم في Google Sheet لهذا العميل.")
            chosen = {**check_phone(sheet_phone), "field": "sheet"}
        elif target in ("phone", "mobile"):
            value = getattr(lead, target) or ""
            chosen = {**check_phone(value), "field": target}
        else:
            chosen = report["target"]
        if chosen is None or chosen.get("kind") == "empty":
            raise AgentError("NO_PHONE_IN_ODOO", "لا يوجد رقم هاتف على العميل في Odoo.",
                             actions=["call_sheet", "open_odoo", "skip"] if report["sheet"]["valid"] else ["open_odoo", "skip"],
                             details={"phone_check": report})
        s = self.settings.get()
        if chosen["severity"] == "error" and s.call_check_phone and not force:
            label = FIELD_LABEL.get(chosen["field"], chosen["field"])
            actions = ["call_anyway", "open_odoo"]
            if chosen["field"] != "sheet" and report["sheet"]["valid"]:
                actions.insert(0, "call_sheet")
            raise AgentError(
                "PHONE_INVALID",
                f"رقم {label} ({chosen['raw']}) غير صحيح: " + "، ".join(chosen["issues"]),
                actions=actions, status_code=409,
                details={"phone_check": report, "number": chosen["raw"], "field": chosen["field"],
                         "issues": chosen["issues"], "sheet_phone": report["sheet"]["raw"] if report["sheet"]["valid"] else ""},
            )
        if chosen["tel"]:
            tel = chosen["tel"]
        else:  # "call anyway" on a number that failed the check: dial the digits exactly as written
            digits = re.sub(r"\D", "", to_ascii_digits(chosen["raw"]))
            tel = digits if digits.startswith("0") else "+" + digits
        if s.call_launch_mode == "fast" or chosen["field"] == "sheet":
            outcome = await self.odoo.adapter.launch_tel(f"tel:{tel}")
        else:
            outcome = await self.odoo.adapter.click_call(lead.id, chosen["field"], chosen["raw"])
        warnings = [p for p in report["problems"] if chosen["field"] != "sheet"] if report["status"] != "ok" else []
        return {"call_started_at": utcnow().isoformat() + "Z", "phone_field": chosen["field"], "phone": chosen["raw"],
                "tel": tel, "method": outcome.method, "warnings": warnings}

    async def refresh_lead(self, fingerprint: str) -> dict:
        warnings = await self._refresh(strict=False)
        c = self._cache(fingerprint)
        if c.odoo_lead_id:
            try:
                lead = await self.odoo.adapter.get_lead(c.odoo_lead_id)
                self._update_cache(fingerprint, odoo_data=lead.to_dict())
            except AgentError as exc:
                if exc.code == "ODOO_LOGIN_REQUIRED":
                    raise
                warnings.append(exc.message_ar)
        return self._payload(fingerprint, warnings)

    # ------------------------------------------------------ status filter
    def _status_options(self) -> list[str]:
        try:
            return self.sheets.dropdown_options("followup_status")
        except Exception:  # noqa: BLE001 - the filter still works from the rows' own values
            log.info("Could not read follow-up status options", exc_info=True)
            return []

    async def status_filter(self) -> dict:
        """Which follow-up statuses the queue looks for, with how many of the owner's rows have each."""
        warnings: list[str] = []
        if not self.queue.loaded:
            warnings = await self._refresh(strict=False)
        s = self.settings.get()
        counts: dict[str, int] = {}
        labels: dict[str, str] = {"": ""}
        for lead in self.queue.owner_leads:
            key = normalize_text(lead.followup_status)
            counts[key] = counts.get(key, 0) + 1
            labels.setdefault(key, lead.followup_status.strip())
        values = [""] + await asyncio.to_thread(self._status_options) + [v for v in s.pending_status_values if v]
        values += [labels[k] for k in counts if k]
        selected = s.pending_values_normalized()
        options, seen = [], set()
        for v in values:
            key = normalize_text(v)
            if key in seen:
                continue
            seen.add(key)
            options.append({"value": v.strip(), "empty": key == "", "count": counts.get(key, 0),
                            "selected": key in selected})
        return {"options": options, "loaded": self.queue.loaded, "warnings": warnings}

    async def set_status_filter(self, values: list[str]) -> dict:
        """Save the statuses to look for; the queue is re-filtered at once (no sheet write)."""
        clean: list[str] = []
        for v in values:
            v = "" if v.strip() == EMPTY_TOKEN else v.strip()
            if v not in clean:
                clean.append(v)
        if not clean:
            raise AgentError("STATUS_FILTER_EMPTY", "اختر حالة متابعة واحدة على الأقل.")
        self.settings.update({"pending_status_values": clean})
        sess = self.sessions.ensure()
        fp = sess.current_fingerprint
        if fp and any(lead.fingerprint == fp for lead in self.queue.queue()):
            payload = self._payload(fp)
        else:
            payload = await self.next(refresh=False)
        payload["filter"] = await self.status_filter()
        return payload

    # --------------------------------------------------------- live sync
    async def _signature(self, lead_id: int) -> tuple[str | None, dict]:
        """Current Odoo signature of a lead, or ``None`` plus a quiet status (polling never raises)."""
        try:
            return await self.odoo.adapter.lead_signature(lead_id), {}
        except AgentError as exc:
            if exc.code == "ODOO_LOGIN_REQUIRED":
                self.odoo.mark_logged_out()
                return None, {"login_required": True}
            return None, {"error": exc.message_ar}
        except Exception:  # noqa: BLE001 - background polling must stay silent
            log.debug("Live sync signature failed for lead %s", lead_id, exc_info=True)
            return None, {}

    async def live(self, fingerprint: str, since: str) -> dict:
        """Live sync for the current queue lead: re-read it when anything changed in Odoo.

        The first poll (empty ``since``) only establishes the baseline signature.
        """
        s = self.settings.get()
        c = self._cache(fingerprint)
        base = {"changed": False, "enabled": s.live_sync_enabled, "interval": s.live_sync_interval_seconds,
                "signature": since}
        if not s.live_sync_enabled or not c.odoo_lead_id:
            return base
        sig, extra = await self._signature(c.odoo_lead_id)
        base.update(extra)
        if sig is None:
            return base
        base["signature"] = sig
        if not since or sig == since:
            return base
        try:
            lead = await self.odoo.adapter.get_lead(c.odoo_lead_id)
        except AgentError:
            log.info("Live sync re-read failed for lead %s", c.odoo_lead_id, exc_info=True)
            base["signature"] = since  # retry on the next poll
            return base
        self._update_cache(fingerprint, odoo_data=lead.to_dict())
        log.info("Live sync: lead %s changed in Odoo; refreshed", c.odoo_lead_id)
        return {**self._payload(fingerprint), **base, "changed": True}

    async def manual_live(self, odoo_id: int, since: str) -> dict:
        """Live sync for a lead opened from manual search (not linked to a sheet row)."""
        s = self.settings.get()
        base = {"changed": False, "enabled": s.live_sync_enabled, "interval": s.live_sync_interval_seconds,
                "signature": since}
        if not s.live_sync_enabled:
            return base
        sig, extra = await self._signature(odoo_id)
        base.update(extra)
        if sig is None:
            return base
        base["signature"] = sig
        if not since or sig == since:
            return base
        try:
            lead = await self.odoo.adapter.get_lead(odoo_id)
        except AgentError:
            base["signature"] = since
            return base
        return {**base, "changed": True, "odoo": lead.to_dict()}

    # ------------------------------------------------------------ manual
    def _linked_fingerprint(self, phone_norm: str) -> str | None:
        """A sheet row of the owner is linked only on an unambiguous phone match."""
        if not phone_norm:
            return None
        rows = [lead for lead in self.queue.owner_leads if any(phones_match(p, phone_norm) for p in lead.phones)]
        return rows[0].fingerprint if len(rows) == 1 else None

    async def manual_search(self, query: str) -> dict:
        query = query.strip()
        if len(query) < 2:
            raise AgentError("QUERY_TOO_SHORT", "اكتب اسم العميل أو رقم الجوال.")
        if not self.queue.loaded:
            await self._refresh(strict=False)
        digits = re.sub(r"\D", "", to_ascii_digits(query))
        if len(digits) >= 7:
            phone_norm = normalize_phone(query)
            found = await self.odoo.adapter.search_by_phone(phone_norm)
            found = [c for c in found if c.id is None or phones_match(c.phone, phone_norm) or phones_match(c.mobile, phone_norm)]
        else:
            found = await self.odoo.adapter.search_by_name(query)
            nq = normalize_company(query)
            found.sort(key=lambda c: 0 if normalize_company(c.company_name) == nq else 1)
        return {"candidates": [c.to_dict() for c in found]}

    async def manual_open(self, odoo_id: int) -> dict:
        lead = await self.odoo.adapter.open_lead(OdooLead(id=odoo_id))
        linked = None
        for number in (lead.phone, lead.mobile):
            linked = self._linked_fingerprint(normalize_phone(number))
            if linked:
                break
        if linked:
            self._update_cache(linked, odoo_lead_id=lead.id, odoo_data=lead.to_dict(), match_status="matched",
                               match_candidates=None)
            c = self._cache(linked)
            self.sessions.set_current(linked, c.sheet_row)
            return {"linked": True, **self._payload(linked, ["تم ربط العميل بصفه في Google Sheet عبر رقم الجوال."])}
        return {"linked": False, "odoo": lead.to_dict(),
                "warnings": ["العميل غير مربوط بصف مؤكد في Google Sheet؛ سيتم تحديث Odoo فقط."]}
