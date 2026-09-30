"""Playwright implementation of :class:`OdooAdapter`.

* Uses a persistent Chromium/Chrome profile (``data/browser-profile``) so the
  user logs in to Odoo manually once; no password is stored anywhere.
* Reuses one visible tab.
* Structured reads/writes use Odoo's generic web-client endpoint
  (``/web/dataset/call_kw``) **through the logged-in browser session**; field
  availability is discovered with ``fields_get`` so nothing is version specific.
  Every read also has a DOM fallback (see :mod:`odoo_selectors`).
* Calls are started by clicking Odoo's own phone/Call link; the OS ``tel:``
  handler (Windows → Phone Link) does the rest.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.adapters.odoo import odoo_selectors as S
from app.adapters.odoo.base import (
    ActionOutcome,
    LoginStatus,
    OdooAdapter,
    OdooLead,
    OdooRpcError,
    OdooRpcUnavailable,
)
from app.adapters.odoo.browser_runtime import BrowserRuntime
from app.config import AppSettings
from app.errors import AgentError, AutomationError, OdooLoginRequired
from app.utils.phone import national_significant, search_variants, to_tel
from app.utils.text import html_to_text

log = logging.getLogger(__name__)

WANTED_FIELDS = [
    "name", "partner_name", "partner_id", "contact_name", "phone", "mobile", "email_from", "user_id",
    "stage_id", "source_id", "medium_id", "campaign_id", "type", "active", "write_date",
]
MESSAGE_FIELDS = [
    "body", "date", "author_id", "email_from", "message_type", "subtype_id", "tracking_value_ids",
    "is_internal", "write_date",
]
TRACKING_FIELDS = [
    "field_id", "field", "field_desc", "old_value_char", "new_value_char", "old_value_datetime",
    "new_value_datetime", "old_value_float", "new_value_float", "old_value_integer", "new_value_integer",
]
ACTIVITY_FIELDS = ["date_deadline", "summary", "activity_type_id", "user_id", "note", "state"]
_NOTE_SUBTYPES = {"note", "notes", "ملاحظة", "ملاحظات"}
_SERVICE_HINTS = ("service", "خدمة", "الخدمة")

_DOM_CHATTER_JS = """
(sel) => {
  const pick = (root, list) => { for (const s of list) { const e = root.querySelector(s); if (e) return e; } return null; };
  const items = [];
  for (const s of sel.item) { const found = document.querySelectorAll(s); if (found.length) { items.push(...found); break; } }
  return items.slice(0, sel.limit).map((m) => {
    const date = pick(m, sel.date);
    const body = pick(m, sel.body);
    const tracking = pick(m, sel.tracking);
    const author = pick(m, sel.author);
    return {
      author: author ? author.textContent.trim() : '',
      date: date ? (date.getAttribute('title') || date.textContent || '').trim() : '',
      body: body ? body.innerText.trim() : '',
      tracking_text: tracking ? tracking.innerText.trim() : '',
    };
  });
}
"""

_LABEL_LOOKUP_JS = """
(label) => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const wanted = norm(label);
  const labels = Array.from(document.querySelectorAll('.o_form_view label, .o_form_view .o_form_label'));
  for (const l of labels) {
    if (norm(l.textContent) !== wanted) continue;
    let target = null;
    const f = l.getAttribute('for');
    if (f) target = document.getElementById(f);
    if (!target) {
      const cell = l.closest('.o_cell, .o_wrap_label, td, .o_wrap_field');
      const next = cell && cell.nextElementSibling;
      if (next) target = next.querySelector('input, textarea, select') || next;
    }
    if (!target) continue;
    const tag = target.tagName.toLowerCase();
    const v = (tag === 'input' || tag === 'textarea' || tag === 'select') ? target.value : target.textContent;
    if (norm(v)) return v.trim();
  }
  return '';
}
"""


def _m2o(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1] or "")
    return "" if value in (False, None) else str(value)


def _val(value: Any) -> str:
    return "" if value in (False, None) else str(value)


def _tracking_value(row: dict, side: str) -> str:
    """First non-empty ``old_value_*`` / ``new_value_*`` of a mail.tracking.value row."""
    for kind in ("char", "datetime", "float", "integer"):
        v = row.get(f"{side}_value_{kind}")
        if v not in (False, None, ""):
            return str(v)
    return ""


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


class BrowserOdooAdapter(OdooAdapter):
    def __init__(
        self,
        settings_provider: Callable[[], AppSettings],
        profile_dir: Path,
        screenshots_dir: Path,
        snapshots_dir: Path,
    ) -> None:
        self._settings_provider = settings_provider
        self._default_profile = profile_dir
        self._shots = screenshots_dir
        self._snaps = snapshots_dir
        self._rt = BrowserRuntime()
        self._pw = None
        self._context = None
        self._page = None
        self._closed = True
        self._fields_cache: dict[str, dict[str, dict]] = {}
        self._uid: int | None = None
        self._open_lead_id: int | None = None

    # ------------------------------------------------------------ plumbing
    @property
    def s(self) -> AppSettings:
        return self._settings_provider()

    @property
    def base(self) -> str:
        return self.s.odoo_base_url

    @property
    def browser_started(self) -> bool:
        return self._context is not None and not self._closed

    async def _exec(self, fn: Callable, *args):
        """Run a worker coroutine; relaunch once if the user closed the browser window."""

        async def _job():
            try:
                return await fn(*args)
            except AgentError:
                raise
            except Exception as exc:  # noqa: BLE001
                if "closed" in str(exc).lower() and "target" in str(exc).lower():
                    log.warning("Browser was closed; relaunching")
                    self._context, self._page, self._closed = None, None, True
                    return await fn(*args)
                raise

        return await self._rt.submit(_job())

    async def _w_context(self):
        if self._context is None or self._closed:
            await self._w_launch()
        return self._context

    async def _w_launch(self) -> None:
        from playwright.async_api import async_playwright

        s = self.s
        profile = Path(s.browser_profile_path) if s.browser_profile_path else self._default_profile
        profile.mkdir(parents=True, exist_ok=True)
        if self._pw is None:
            self._pw = await async_playwright().start()
        kwargs: dict[str, Any] = {"user_data_dir": str(profile), "headless": s.browser_headless}
        if s.browser_headless:
            kwargs["viewport"] = {"width": 1400, "height": 900}
        else:
            kwargs["no_viewport"] = True
            kwargs["args"] = ["--start-maximized"]
        if s.browser_executable_path:
            kwargs["executable_path"] = s.browser_executable_path
        elif s.browser_channel in ("chrome", "msedge"):
            kwargs["channel"] = s.browser_channel
        try:
            ctx = await self._pw.chromium.launch_persistent_context(**kwargs)
        except Exception as first:  # noqa: BLE001
            if "channel" in kwargs:
                log.warning("Launch with channel %s failed, retrying bundled Chromium", kwargs["channel"], exc_info=True)
                kwargs.pop("channel")
                try:
                    ctx = await self._pw.chromium.launch_persistent_context(**kwargs)
                except Exception as exc:  # noqa: BLE001
                    raise self._launch_error(exc) from exc
            else:
                raise self._launch_error(first) from first
        ctx.set_default_timeout(s.action_timeout_ms)
        ctx.set_default_navigation_timeout(s.navigation_timeout_ms)
        ctx.on("close", lambda *_: self._mark_closed())
        self._context, self._page, self._closed = ctx, None, False
        self._fields_cache.clear()

    @staticmethod
    def _launch_error(exc: Exception) -> AgentError:
        log.exception("Browser launch failed", exc_info=exc)
        return AgentError(
            "BROWSER_LAUNCH_FAILED",
            "تعذر تشغيل متصفح Odoo. تأكد من تشغيل 01_install.bat ومن إغلاق أي نافذة متصفح سابقة للـAgent ثم أعد المحاولة.",
            actions=["retry"],
            status_code=503,
        )

    def _mark_closed(self) -> None:
        self._closed, self._context, self._page = True, None, None

    async def _w_page(self):
        ctx = await self._w_context()
        if self._page is not None and not self._page.is_closed():
            return self._page
        pages = [p for p in ctx.pages if not p.is_closed()]
        self._page = pages[0] if pages else await ctx.new_page()
        return self._page

    # ------------------------------------------------------------------ RPC
    async def _w_rpc(self, route: str, params: dict) -> Any:
        ctx = await self._w_context()
        payload = {"jsonrpc": "2.0", "method": "call", "id": 1, "params": params}
        try:
            resp = await ctx.request.post(
                self.base + route, data=json.dumps(payload), headers={"Content-Type": "application/json"},
                timeout=self.s.navigation_timeout_ms,
            )
        except Exception as exc:  # noqa: BLE001
            raise OdooRpcUnavailable(str(exc)) from exc
        if resp.status in (404, 405):
            raise OdooRpcUnavailable(f"HTTP {resp.status}")
        try:
            body = await resp.json()
        except Exception as exc:  # noqa: BLE001 - HTML login page or proxy page
            if "/web/login" in resp.url:
                raise OdooLoginRequired() from exc
            raise OdooRpcUnavailable("non-JSON response") from exc
        err = body.get("error") if isinstance(body, dict) else None
        if err:
            data = err.get("data") or {}
            name = str(data.get("name", ""))
            if "SessionExpired" in name or err.get("code") == 100:
                raise OdooLoginRequired()
            raise OdooRpcError(str(data.get("message") or err.get("message") or name))
        return body.get("result") if isinstance(body, dict) else None

    async def _w_call_kw(self, model: str, method: str, args: list | None = None, kwargs: dict | None = None) -> Any:
        return await self._w_rpc(
            f"/web/dataset/call_kw/{model}/{method}",
            {"model": model, "method": method, "args": args or [], "kwargs": kwargs or {}},
        )

    async def _w_fields(self, model: str = "crm.lead") -> dict[str, dict]:
        key = f"{self.base}|{model}"
        if key not in self._fields_cache:
            self._fields_cache[key] = await self._w_call_kw(
                model, "fields_get", [], {"attributes": ["string", "type", "relation", "selection"]}
            ) or {}
        return self._fields_cache[key]

    async def _w_existing(self, model: str, wanted: list[str], required: list[str]) -> list[str]:
        """Subset of ``wanted`` that exists on ``model`` in this Odoo version (``required`` if unknown)."""
        try:
            fields = await self._w_fields(model)
        except OdooRpcError:
            return required
        return [f for f in wanted if f in fields] or required

    def _service_field(self, fields: dict[str, dict]) -> str | None:
        for name, meta in fields.items():
            label = str(meta.get("string", "")).lower()
            if meta.get("type") not in ("char", "selection", "many2one"):
                continue
            if any(h in name.lower() for h in ("service",)) or any(h in label for h in _SERVICE_HINTS):
                return name
        return None

    async def _w_read_fields(self) -> list[str]:
        fields = await self._w_fields()
        wanted = [f for f in WANTED_FIELDS if f in fields]
        svc = self._service_field(fields)
        if svc and svc not in wanted:
            wanted.append(svc)
        return wanted

    def _record_to_lead(self, rec: dict, fields: dict[str, dict]) -> OdooLead:
        svc = self._service_field(fields)
        service_val = ""
        if svc:
            raw = rec.get(svc)
            meta = fields.get(svc, {})
            if meta.get("type") == "selection":
                service_val = dict(meta.get("selection") or []).get(raw, _val(raw))
            elif meta.get("type") == "many2one":
                service_val = _m2o(raw)
            else:
                service_val = _val(raw)
        source, medium, campaign = _m2o(rec.get("source_id")), _m2o(rec.get("medium_id")), _m2o(rec.get("campaign_id"))
        lead_id = int(rec["id"])
        return OdooLead(
            id=lead_id,
            name=_val(rec.get("name")),
            company_name=_val(rec.get("partner_name")) or _m2o(rec.get("partner_id")),
            contact_name=_val(rec.get("contact_name")),
            phone=_val(rec.get("phone")),
            mobile=_val(rec.get("mobile")),
            email=_val(rec.get("email_from")),
            salesperson=_m2o(rec.get("user_id")),
            stage=_m2o(rec.get("stage_id")),
            source=source, medium=medium, campaign=campaign,
            utm_source=source, utm_medium=medium, utm_campaign=campaign,
            service_type=service_val,
            lead_type=_val(rec.get("type")),
            active=bool(rec.get("active", True)),
            write_date=_val(rec.get("write_date")),
            url=self.s.lead_url(lead_id),
        )

    async def _w_search(self, domain: list) -> list[OdooLead]:
        fields = await self._w_fields()
        records = await self._w_call_kw(
            "crm.lead", "search_read", [],
            {"domain": domain, "fields": await self._w_read_fields(), "limit": 25, "order": "id desc"},
        ) or []
        return [self._record_to_lead(r, fields) for r in records]

    @staticmethod
    def _or_domain(terms: list[list]) -> list:
        if not terms:
            return [["id", "=", 0]]
        return ["|"] * (len(terms) - 1) + terms

    # ----------------------------------------------------------- UI helpers
    async def _first_visible(self, page, selectors: list[str], field: str | None = None):
        for tmpl in selectors:
            sel = tmpl.format(field=field) if field else tmpl
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return loc, sel
            except Exception:  # noqa: BLE001 - invalid selector for this engine version
                continue
        return None, ""

    async def _wait_first(self, page, selectors: list[str], timeout: int):
        try:
            await page.locator(", ".join(selectors)).first.wait_for(state="visible", timeout=timeout)
        except Exception:  # noqa: BLE001
            return None, ""
        return await self._first_visible(page, selectors)

    async def _w_is_login_page(self, page) -> bool:
        if "/web/login" in page.url:
            return True
        loc, _ = await self._first_visible(page, S.LOGIN_FORM)
        return loc is not None

    async def _w_wait_form(self, page) -> str:
        """Wait for a form view or a login form. Returns 'form', 'login' or ''."""
        try:
            await page.locator(", ".join(S.FORM_VIEW + S.LOGIN_FORM)).first.wait_for(
                state="visible", timeout=self.s.navigation_timeout_ms
            )
        except Exception:  # noqa: BLE001
            return ""
        if await self._w_is_login_page(page):
            return "login"
        try:  # record data renders slightly after the view shell
            await page.locator("div[name='name'], div[name='phone'], div[name='partner_name']").first.wait_for(
                state="attached", timeout=3000
            )
        except Exception:  # noqa: BLE001
            pass
        return "form"

    async def _w_read_dom_field(self, page, logical: str) -> str:
        for fname in S.FIELD_NAMES.get(logical, []):
            for tmpl in S.FIELD_VALUE_SELECTORS:
                sel = tmpl.format(field=fname)
                try:
                    loc = page.locator(sel).first
                    if await loc.count() == 0:
                        continue
                    tag = await loc.evaluate("e => e.tagName.toLowerCase()")
                    value = await loc.input_value() if tag in ("input", "textarea", "select") else await loc.inner_text()
                except Exception:  # noqa: BLE001
                    continue
                value = (value or "").strip()
                if value:
                    return value
        for label in S.FIELD_LABELS.get(logical, []):
            try:
                value = await page.evaluate(_LABEL_LOOKUP_JS, label)
            except Exception:  # noqa: BLE001
                value = ""
            if value:
                return value.strip()
        return ""

    async def _w_extract_dom(self, page) -> dict[str, str]:
        data: dict[str, str] = {}
        for logical in ("lead_name", "company_name", "contact_name", "phone", "mobile", "email", "salesperson",
                        "source", "medium", "campaign", "service_type"):
            data[logical] = await self._w_read_dom_field(page, logical)
        stage, _ = await self._first_visible(page, S.STAGE_SELECTORS)
        data["stage"] = (await stage.inner_text()).strip() if stage else ""
        try:
            msgs = page.locator(", ".join(S.CHATTER_MESSAGE[:1]))
            data["notes"] = json.dumps([t.strip()[:500] for t in (await msgs.all_inner_texts())[:3]], ensure_ascii=False)
        except Exception:  # noqa: BLE001
            data["notes"] = "[]"
        return data

    def _page_shows_lead(self, page, lead_id: int) -> bool:
        return re.search(rf"(?:/|id=){lead_id}(?:\D|$)", page.url or "") is not None

    async def _w_screenshot(self, name: str) -> str:
        try:
            page = await self._w_page()
            self._shots.mkdir(parents=True, exist_ok=True)
            path = self._shots / f"{name}-{_stamp()}.png"
            await page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:  # noqa: BLE001
            log.warning("Screenshot failed", exc_info=True)
            return ""

    # ------------------------------------------------------------- session
    async def _w_login_status(self) -> LoginStatus:
        try:
            info = await self._w_rpc("/web/session/get_session_info", {})
        except OdooLoginRequired:
            return LoginStatus(False, True, message="تسجيل الدخول إلى Odoo مطلوب")
        except (OdooRpcUnavailable, OdooRpcError):
            page = await self._w_page()
            if not page.url.startswith(self.base):
                await page.goto(self.base + "/web")
            logged = not await self._w_is_login_page(page)
            return LoginStatus(logged, True, url=page.url,
                               message="" if logged else "تسجيل الدخول إلى Odoo مطلوب")
        uid = (info or {}).get("uid")
        if not uid:
            return LoginStatus(False, True, message="تسجيل الدخول إلى Odoo مطلوب")
        self._uid = int(uid)
        name = (info or {}).get("name") or (info or {}).get("username") or ""
        page_url = self._page.url if self._page is not None and not self._page.is_closed() else ""
        return LoginStatus(True, True, user_name=str(name), url=page_url)

    async def login_status(self) -> LoginStatus:
        return await self._exec(self._w_login_status)

    async def _w_open_url(self, url: str) -> None:
        page = await self._w_page()
        await page.goto(url)
        await page.bring_to_front()

    async def open_login(self) -> None:
        await self._exec(self._w_open_url, self.base + "/web/login")

    async def open_url(self, url: str) -> None:
        await self._exec(self._w_open_url, url)

    # -------------------------------------------------------------- search
    async def _w_search_phone(self, phone_norm: str) -> list[OdooLead]:
        try:
            fields = await self._w_fields()
        except OdooRpcUnavailable:
            return await self._w_ui_search("0" + national_significant(phone_norm))
        nsn = national_significant(phone_norm)
        terms: list[list] = []
        if "phone_mobile_search" in fields:
            terms.append(["phone_mobile_search", "ilike", nsn])
        for fname in ("phone", "mobile", "phone_sanitized"):
            if fname in fields:
                for v in search_variants(phone_norm):
                    if v == phone_norm and len(search_variants(phone_norm)) > 1:
                        continue  # covered by the 9-digit variant
                    terms.append([fname, "ilike", v])
        return await self._w_search(self._or_domain(terms))

    async def search_by_phone(self, phone_norm: str) -> list[OdooLead]:
        return await self._exec(self._w_search_phone, phone_norm)

    async def _w_search_name(self, text: str) -> list[OdooLead]:
        try:
            fields = await self._w_fields()
        except OdooRpcUnavailable:
            return await self._w_ui_search(text)
        terms = [[f, "ilike", text] for f in ("partner_name", "name", "contact_name", "partner_id") if f in fields]
        return await self._w_search(self._or_domain(terms))

    async def search_by_name(self, text: str) -> list[OdooLead]:
        return await self._exec(self._w_search_name, text)

    async def _w_ui_search(self, query: str) -> list[OdooLead]:
        """Fallback: type into the CRM search box and read visible rows/cards."""
        page = await self._w_page()
        await page.goto(self.s.crm_url)
        if await self._w_is_login_page(page):
            raise OdooLoginRequired()
        box, _ = await self._wait_first(page, S.SEARCH_INPUT, self.s.navigation_timeout_ms)
        if box is None:
            shot = await self._w_screenshot("odoo-search-box-not-found")
            raise AutomationError("ODOO_SEARCH_BOX_NOT_FOUND", "تعذر العثور على مربع البحث في Odoo.", shot)
        await box.fill(query)
        await box.press("Enter")
        await page.wait_for_timeout(1500)
        for sel in S.LIST_ROWS:
            rows = page.locator(sel)
            n = await rows.count()
            if n:
                texts = await rows.all_inner_texts()
                return [OdooLead(id=None, name=" | ".join(t.split()[:12]), ui_index=i, ui_query=query)
                        for i, t in enumerate(texts[:25])]
        return []

    async def _w_open_ui_candidate(self, lead: OdooLead) -> int:
        await self._w_ui_search(lead.ui_query)
        page = await self._w_page()
        for sel in S.LIST_ROWS:
            rows = page.locator(sel)
            if await rows.count() > (lead.ui_index or 0):
                await rows.nth(lead.ui_index or 0).click()
                await self._w_wait_form(page)
                m = re.search(r"(?:/|id=)(\d+)(?:\D|$)", page.url)
                if m:
                    return int(m.group(1))
        raise AutomationError("ODOO_LEAD_OPEN_FAILED", "تعذر فتح صفحة العميل في Odoo.", await self._w_screenshot("odoo-open-lead-failed"))

    # ---------------------------------------------------------------- read
    async def _w_get_lead(self, lead_id: int) -> OdooLead:
        fields = await self._w_fields()
        recs = await self._w_call_kw("crm.lead", "read", [[lead_id]], {"fields": await self._w_read_fields()})
        if not recs:
            raise AgentError("ODOO_LEAD_NOT_FOUND", "العميل غير موجود في Odoo أو لا تملك صلاحية عليه.")
        lead = self._record_to_lead(recs[0], fields)
        try:
            lead.chatter = await self._w_chatter(lead_id)
        except OdooRpcError:
            log.info("Could not read chatter for lead %s", lead_id, exc_info=True)
        lead.latest_notes = [m["body"][:500] for m in lead.chatter if m["kind"] in ("note", "message") and m["body"]][:3]
        try:
            lead.activities = await self._w_activities(lead_id)
        except OdooRpcError:
            log.info("Could not read activities for lead %s", lead_id, exc_info=True)
        return lead

    # ------------------------------------------------------------- chatter
    async def _w_tracking(self, ids: list[int]) -> dict[int, dict[str, str]]:
        """Field changes (stage, salesperson...). Often admin-only: failures are ignored."""
        if not ids:
            return {}
        try:
            wanted = await self._w_existing("mail.tracking.value", TRACKING_FIELDS, ["field_desc"])
            rows = await self._w_call_kw("mail.tracking.value", "read", [ids], {"fields": wanted}) or []
        except (OdooRpcError, OdooRpcUnavailable):
            log.debug("Tracking values not readable", exc_info=True)
            return {}
        out: dict[int, dict[str, str]] = {}
        for r in rows:
            label = _val(r.get("field_desc")) or _m2o(r.get("field_id")) or _val(r.get("field"))
            label = re.sub(r"\s*\([\w.]+\)\s*$", "", label)

            out[int(r["id"])] = {"field": label, "old": _tracking_value(r, "old"), "new": _tracking_value(r, "new")}
        return out

    async def _w_chatter(self, lead_id: int) -> list[dict[str, Any]]:
        wanted = await self._w_existing("mail.message", MESSAGE_FIELDS, ["body", "date"])
        msgs = await self._w_call_kw(
            "mail.message", "search_read", [],
            {"domain": [["model", "=", "crm.lead"], ["res_id", "=", lead_id]], "fields": wanted,
             "limit": self.s.chatter_history_limit, "order": "id desc"},
        ) or []
        tracking = await self._w_tracking([t for m in msgs for t in (m.get("tracking_value_ids") or [])])
        out: list[dict[str, Any]] = []
        for m in msgs:
            changes = [tracking[t] for t in (m.get("tracking_value_ids") or []) if t in tracking]
            subtype = _m2o(m.get("subtype_id"))
            mtype = _val(m.get("message_type"))
            if mtype == "comment":
                internal = m.get("is_internal") is True or subtype.strip().lower() in _NOTE_SUBTYPES
                kind = "note" if internal else "message"
            elif mtype in ("email", "email_outgoing"):
                kind = "email"
            elif changes or m.get("tracking_value_ids"):
                kind = "tracking"
            else:
                kind = "system"
            out.append({
                "id": m.get("id"), "date": _val(m.get("date")), "author": _m2o(m.get("author_id")) or _val(m.get("email_from")),
                "kind": kind, "subtype": subtype, "body": html_to_text(m.get("body"))[:4000], "tracking": changes,
            })
        return out

    async def _w_activities(self, lead_id: int) -> list[dict[str, Any]]:
        wanted = await self._w_existing("mail.activity", ACTIVITY_FIELDS, ["date_deadline", "summary"])
        rows = await self._w_call_kw(
            "mail.activity", "search_read", [],
            {"domain": [["res_model", "=", "crm.lead"], ["res_id", "=", lead_id]], "fields": wanted,
             "limit": 20, "order": "date_deadline asc"},
        ) or []
        return [{"id": r.get("id"), "date_deadline": _val(r.get("date_deadline")), "summary": _val(r.get("summary")),
                 "type": _m2o(r.get("activity_type_id")), "user": _m2o(r.get("user_id")),
                 "note": html_to_text(_val(r.get("note")))[:1000], "state": _val(r.get("state"))} for r in rows]

    async def _w_dom_chatter(self, page) -> list[dict[str, Any]]:
        try:
            rows = await page.evaluate(_DOM_CHATTER_JS, {
                "item": S.CHATTER_ITEM, "author": S.CHATTER_AUTHOR, "date": S.CHATTER_DATE, "body": S.CHATTER_BODY,
                "tracking": S.CHATTER_TRACKING, "limit": self.s.chatter_history_limit,
            })
        except Exception:  # noqa: BLE001
            log.debug("DOM chatter read failed", exc_info=True)
            return []
        out = []
        for i, r in enumerate(rows or []):
            tracking = [{"field": "", "old": "", "new": r["tracking_text"]}] if r.get("tracking_text") else []
            kind = "note" if r.get("body") else ("tracking" if tracking else "system")
            out.append({"id": -(i + 1), "date": r.get("date", ""), "author": r.get("author", ""), "kind": kind,
                        "subtype": "", "body": (r.get("body") or "")[:4000], "tracking": tracking})
        return out

    async def _w_signature(self, lead_id: int) -> str | None:
        if not self.browser_started:
            return None  # never launch a browser just to poll
        try:
            recs = await self._w_call_kw("crm.lead", "read", [[lead_id]], {"fields": ["write_date"]}) or []
            domain = [["model", "=", "crm.lead"], ["res_id", "=", lead_id]]
            count = await self._w_call_kw("mail.message", "search_count", [domain])
            last = await self._w_call_kw("mail.message", "search_read", [],
                                         {"domain": domain, "fields": ["write_date"], "limit": 1,
                                          "order": "write_date desc, id desc"}) or []
            acts = await self._w_call_kw("mail.activity", "search_read", [],
                                         {"domain": [["res_model", "=", "crm.lead"], ["res_id", "=", lead_id]],
                                          "fields": ["write_date"], "order": "id asc"}) or []
        except (OdooRpcUnavailable, OdooRpcError):
            return None
        lead_wd = _val(recs[0].get("write_date")) if recs else "missing"
        msg = f"{last[0].get('id')}@{_val(last[0].get('write_date'))}" if last else "-"
        act = ",".join(f"{a.get('id')}@{_val(a.get('write_date'))}" for a in acts)
        return f"{lead_wd}|{count}|{msg}|{act}"

    async def lead_signature(self, lead_id: int) -> str | None:
        return await self._exec(self._w_signature, lead_id)

    async def get_lead(self, lead_id: int) -> OdooLead:
        return await self._exec(self._w_get_lead, lead_id)

    async def _w_navigate_lead(self, lead_id: int) -> None:
        page = await self._w_page()
        urls = [self.s.lead_url(lead_id), f"{self.base}/web#id={lead_id}&model=crm.lead&view_type=form"]
        last = ""
        for attempt in range(self.s.retry_attempts):
            for url in urls:
                await page.goto(url)
                last = await self._w_wait_form(page)
                if last == "login":
                    raise OdooLoginRequired()
                if last == "form":
                    self._open_lead_id = lead_id
                    await page.bring_to_front()
                    return
            log.warning("Lead %s form not detected (attempt %s)", lead_id, attempt + 1)
        shot = await self._w_screenshot("odoo-open-lead-failed")
        raise AutomationError("ODOO_LEAD_OPEN_FAILED", "تعذر فتح صفحة العميل في Odoo.", shot)

    async def _w_open_lead(self, lead: OdooLead) -> OdooLead:
        lead_id = lead.id
        if lead_id is None:
            lead_id = await self._w_open_ui_candidate(lead)
        else:
            await self._w_navigate_lead(lead_id)
        page = await self._w_page()
        dom = await self._w_extract_dom(page)
        try:
            result = await self._w_get_lead(lead_id)
        except (OdooRpcUnavailable, OdooRpcError):
            result = OdooLead(id=lead_id)
        # DOM fills anything the structured read did not return.
        mapping = {"lead_name": "name", "company_name": "company_name", "contact_name": "contact_name",
                   "phone": "phone", "mobile": "mobile", "email": "email", "salesperson": "salesperson",
                   "source": "source", "medium": "medium", "campaign": "campaign", "service_type": "service_type",
                   "stage": "stage"}
        for dom_key, attr in mapping.items():
            if not getattr(result, attr) and dom.get(dom_key):
                setattr(result, attr, dom[dom_key])
        if not result.utm_source:
            result.utm_source, result.utm_medium, result.utm_campaign = result.source, result.medium, result.campaign
        if not result.latest_notes:
            result.latest_notes = json.loads(dom.get("notes") or "[]")
        if not result.chatter:
            result.chatter = await self._w_dom_chatter(page)
        result.url = page.url
        return result

    async def open_lead(self, lead: OdooLead) -> OdooLead:
        return await self._exec(self._w_open_lead, lead)

    # ---------------------------------------------------------------- call
    async def _w_ensure_lead_page(self, lead_id: int):
        page = await self._w_page()
        form, _ = await self._first_visible(page, S.FORM_VIEW)
        if not (self._open_lead_id == lead_id and self._page_shows_lead(page, lead_id) and form is not None):
            await self._w_navigate_lead(lead_id)
        return await self._w_page()

    async def _w_click_call(self, lead_id: int, phone_field: str, phone: str) -> ActionOutcome:
        page = await self._w_ensure_lead_page(lead_id)
        loc, sel = await self._first_visible(page, S.CALL_BUTTON_SELECTORS, field=phone_field)
        if loc is None:
            other = "mobile" if phone_field == "phone" else "phone"
            loc, sel = await self._first_visible(page, S.CALL_BUTTON_SELECTORS, field=other)
        if loc is None:
            generic = page.locator(", ".join(S.CALL_BUTTON_GENERIC))
            if await generic.count() == 1:
                loc, sel = generic.first, "generic"
        if loc is not None and self.s.call_launch_mode == "windows_handler":
            # Same number Odoo would dial (read from its own link), handed to the Windows tel: handler.
            href = (await loc.get_attribute("href") or "").strip()
            target = href if href.lower().startswith("tel:") else f"tel:{to_tel(phone)}"
            self._launch_tel(target)
            log.info("Launched %s via Windows handler for lead %s", target, lead_id)
            return ActionOutcome(True, "windows_tel", sel)
        if loc is not None:
            await page.bring_to_front()
            await loc.click()
            log.info("Clicked Odoo call control (%s) for lead %s", sel, lead_id)
            return ActionOutcome(True, "ui", sel)
        if self.s.call_fallback_windows_handler and to_tel(phone):
            self._launch_tel(f"tel:{to_tel(phone)}")
            return ActionOutcome(True, "windows_tel", "Odoo call link not found; used Windows tel: handler")
        shot = await self._w_screenshot("odoo-call-button-not-found")
        raise AutomationError("ODOO_CALL_BUTTON_NOT_FOUND", "تعذر العثور على زر الاتصال في Odoo.", shot)

    async def click_call(self, lead_id: int, phone_field: str, phone: str) -> ActionOutcome:
        return await self._exec(self._w_click_call, lead_id, phone_field, phone)

    async def launch_tel(self, tel_uri: str) -> ActionOutcome:
        # No browser round-trip: this is what makes the fast call mode instant.
        self._launch_tel(tel_uri)
        log.info("Launched %s via Windows handler (fast mode)", tel_uri)
        return ActionOutcome(True, "fast_tel", tel_uri)

    @staticmethod
    def _launch_tel(uri: str) -> None:
        """Hand a tel: URI to the OS (Windows → Phone Link). Never dials/ends calls itself."""
        if sys.platform != "win32":
            raise AgentError("WINDOWS_ONLY", "تشغيل الاتصال عبر Windows متاح على Windows فقط.")
        os.startfile(uri)  # type: ignore[attr-defined]

    # ------------------------------------------------------------ log note
    @staticmethod
    def _snippets(ref: str) -> list[str]:
        """A ref is one code ("KLA-…") or several note lines separated by newlines (all must match)."""
        return [x.strip() for x in (ref or "").split("\n") if x.strip()]

    async def _w_note_exists(self, lead_id: int, ref: str) -> bool:
        snippets = self._snippets(ref)
        if not snippets:
            return False
        try:
            count = await self._w_call_kw(
                "mail.message", "search_count",
                [[["model", "=", "crm.lead"], ["res_id", "=", lead_id]] + [["body", "ilike", x] for x in snippets]],
            )
            return bool(count)
        except (OdooRpcUnavailable, OdooRpcError):
            page = await self._w_page()
            if self._page_shows_lead(page, lead_id):
                msgs = page.locator(", ".join(S.CHATTER_MESSAGE))
                for x in snippets:
                    msgs = msgs.filter(has_text=x)
                return await msgs.count() > 0
            return False

    async def _w_ui_log_note(self, lead_id: int, body: str, ref: str) -> None:
        page = await self._w_ensure_lead_page(lead_id)
        btn, _ = await self._first_visible(page, S.LOG_NOTE_BUTTON)
        if btn is None:
            raise AutomationError("ODOO_LOG_NOTE_BUTTON_NOT_FOUND", "تعذر العثور على زر Log note في Odoo.")
        await btn.click()
        box, box_sel = await self._wait_first(page, S.COMPOSER_INPUT, self.s.action_timeout_ms)
        if box is None:
            raise AutomationError("ODOO_COMPOSER_NOT_FOUND", "تعذر فتح مربع كتابة الملاحظة في Odoo.")
        if "contenteditable" in box_sel:
            await box.click()
            await page.keyboard.insert_text(body)
        else:
            await box.fill(body)
        send, _ = await self._wait_first(page, S.COMPOSER_SEND, self.s.action_timeout_ms)
        if send is None:
            raise AutomationError("ODOO_LOG_BUTTON_NOT_FOUND", "تعذر العثور على زر Log في Odoo.")
        label = (await send.inner_text()).strip().lower()
        if label in ("send", "إرسال", "ارسال"):
            raise AutomationError("ODOO_COMPOSER_WRONG_MODE", "مربع الكتابة في وضع إرسال رسالة وليس Log note؛ تم الإلغاء.")
        await send.click()
        posted = page.locator(", ".join(S.CHATTER_MESSAGE))
        for x in self._snippets(ref)[:2]:
            posted = posted.filter(has_text=x)
        await posted.first.wait_for(state="visible", timeout=self.s.action_timeout_ms)

    async def _w_rpc_log_note(self, lead_id: int, body: str) -> None:
        await self._w_call_kw(
            "crm.lead", "message_post", [[lead_id]],
            {"body": body, "message_type": "comment", "subtype_xmlid": "mail.mt_note"},
        )

    async def _w_post_log_note(self, lead_id: int, body: str, ref: str) -> ActionOutcome:
        if await self._w_note_exists(lead_id, ref):
            return ActionOutcome(True, "existing", "Log note already exists", already_done=True)
        order = ["ui", "rpc"] if self.s.odoo_write_method == "ui_first" else ["rpc", "ui"]
        errors: list[str] = []
        for method in order:
            try:
                if method == "ui":
                    await self._w_ui_log_note(lead_id, body, ref)
                else:
                    await self._w_rpc_log_note(lead_id, body)
                return ActionOutcome(True, method)
            except OdooLoginRequired:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("Log note via %s failed for lead %s", method, lead_id, exc_info=True)
                errors.append(f"{method}: {getattr(exc, 'message_ar', str(exc))}")
            # Never post twice: the failed attempt may still have saved the note.
            if await self._w_note_exists(lead_id, ref):
                return ActionOutcome(True, method, "verified after error")
        shot = await self._w_screenshot("odoo-log-note-failed")
        return ActionOutcome(False, "none", " | ".join(errors), shot)

    async def post_log_note(self, lead_id: int, body: str, ref: str) -> ActionOutcome:
        return await self._exec(self._w_post_log_note, lead_id, body, ref)

    # ------------------------------------------------------------ activity
    async def _w_schedule_activity(self, lead_id: int, date_deadline: str, summary: str, note: str) -> ActionOutcome:
        try:
            if self._uid is None:
                await self._w_login_status()
            kwargs: dict[str, Any] = {
                "act_type_xmlid": self.s.odoo_activity_type_xmlid, "date_deadline": date_deadline,
                "summary": summary, "note": note,
            }
            if self._uid:
                kwargs["user_id"] = self._uid
            await self._w_call_kw("crm.lead", "activity_schedule", [[lead_id]], kwargs)
            return ActionOutcome(True, "rpc")
        except OdooLoginRequired:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("Activity creation failed for lead %s", lead_id, exc_info=True)
            return ActionOutcome(False, "none", f"Activity creation failed: {exc}")

    async def schedule_activity(self, lead_id: int, date_deadline: str, summary: str, note: str) -> ActionOutcome:
        return await self._exec(self._w_schedule_activity, lead_id, date_deadline, summary, note)

    # -------------------------------------------------------------- create
    async def _w_create_lead(self, values: dict[str, Any]) -> OdooLead:
        try:
            fields = await self._w_fields()
            vals = {k: v for k, v in values.items() if k in fields and v not in ("", None)}
            if "user_id" in fields and "user_id" not in vals:
                if self._uid is None:
                    await self._w_login_status()
                if self._uid:
                    vals["user_id"] = self._uid
            new_id = await self._w_call_kw("crm.lead", "create", [vals])
        except OdooLoginRequired:
            raise
        except (OdooRpcError, OdooRpcUnavailable) as exc:
            log.warning("Creating a lead failed", exc_info=True)
            raise AgentError("ODOO_CREATE_FAILED", f"تعذر إضافة العميل إلى Odoo: {exc}", actions=["retry"]) from exc
        if isinstance(new_id, list):
            new_id = new_id[0] if new_id else None
        if not new_id:
            raise AgentError("ODOO_CREATE_FAILED", "لم يرجع Odoo رقم العميل الجديد.", actions=["retry"])
        return await self._w_get_lead(int(new_id))

    async def create_lead(self, values: dict[str, Any]) -> OdooLead:
        return await self._exec(self._w_create_lead, values)

    # --------------------------------------------------------- diagnostics
    async def _w_diagnostics(self) -> dict[str, Any]:
        page = await self._w_page()
        result: dict[str, Any] = {"url": page.url, "browser_open": True}
        form, form_sel = await self._first_visible(page, S.FORM_VIEW)
        result["lead_detected"] = bool(form) and ("crm" in page.url or "crm.lead" in page.url)
        result["login_page"] = await self._w_is_login_page(page)
        checks = {
            "phone": ("phone", None), "mobile": ("mobile", None), "source": ("source", None),
        }
        for key, (logical, _) in checks.items():
            result[f"{key}_value"] = await self._w_read_dom_field(page, logical) if form else ""
        result["phone_detected"] = bool(result["phone_value"] or result["mobile_value"])
        result["source_detected"] = bool(result["source_value"])
        call, call_sel = await self._first_visible(page, S.CALL_BUTTON_SELECTORS, field="phone")
        if call is None:
            call, call_sel = await self._first_visible(page, S.CALL_BUTTON_SELECTORS, field="mobile")
        result["call_button_detected"], result["call_selector"] = call is not None, call_sel
        note, note_sel = await self._first_visible(page, S.LOG_NOTE_BUTTON)
        result["log_note_detected"], result["log_note_selector"] = note is not None, note_sel
        act, act_sel = await self._first_visible(page, S.ACTIVITY_BUTTON)
        result["activity_detected"], result["activity_selector"] = act is not None, act_sel
        result["form_selector"] = form_sel
        try:
            await self._w_fields()
            result["rpc_available"] = True
        except Exception:  # noqa: BLE001
            result["rpc_available"] = False
        return result

    async def diagnostics(self) -> dict[str, Any]:
        return await self._exec(self._w_diagnostics)

    async def capture_screenshot(self, name: str) -> str:
        return await self._exec(self._w_screenshot, name)

    async def _w_dom(self, name: str) -> str:
        page = await self._w_page()
        self._snaps.mkdir(parents=True, exist_ok=True)
        path = self._snaps / f"{name}-{_stamp()}.html"
        path.write_text(await page.content(), encoding="utf-8")
        return str(path)

    async def capture_dom(self, name: str) -> str:
        return await self._exec(self._w_dom, name)

    async def _w_close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
            if self._pw is not None:
                await self._pw.stop()
        finally:
            self._context, self._pw, self._closed = None, None, True

    async def close(self) -> None:
        if self._rt._thread is None:
            return
        try:
            await self._rt.submit(self._w_close())
        finally:
            self._rt.stop()
