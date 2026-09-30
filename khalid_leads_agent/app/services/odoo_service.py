"""Deterministic Odoo lead matching on top of an :class:`OdooAdapter`.

Search priority: phone exact → mobile exact → company exact → company partial.
Only a single *strong* match is opened automatically; anything else is shown
to the user to choose. Leads are never created automatically.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.adapters.odoo.base import LoginStatus, OdooAdapter, OdooLead
from app.errors import AgentError, OdooLoginRequired
from app.utils.phone import phones_match
from app.utils.text import company_core, company_similarity, normalize_company

log = logging.getLogger(__name__)
FUZZY_THRESHOLD = 0.6


@dataclass
class MatchResult:
    status: str  # matched | multiple | not_found
    lead: OdooLead | None = None
    candidates: list[OdooLead] = field(default_factory=list)
    strategy: str = ""

    def to_dict(self) -> dict:
        return {"status": self.status, "strategy": self.strategy,
                "lead": self.lead.to_dict() if self.lead else None,
                "candidates": [c.to_dict() for c in self.candidates]}


def _dedupe(leads: list[OdooLead]) -> list[OdooLead]:
    seen: set = set()
    out: list[OdooLead] = []
    for lead in leads:
        key = lead.id if lead.id is not None else f"ui{lead.ui_index}"
        if key not in seen:
            seen.add(key)
            out.append(lead)
    return out


def _same_company(lead: OdooLead, company_norm: str) -> bool:
    return bool(company_norm) and company_norm in (normalize_company(lead.company_name), normalize_company(lead.name))


class OdooService:
    def __init__(self, adapter: OdooAdapter) -> None:
        self.adapter = adapter
        self.last_login: LoginStatus | None = None

    async def check_login(self) -> LoginStatus:
        try:
            self.last_login = await self.adapter.login_status()
        except AgentError:
            self.last_login = LoginStatus(False, False, message="تعذر فتح المتصفح")
            raise
        return self.last_login

    def mark_logged_out(self) -> None:
        self.last_login = LoginStatus(False, True, message="تسجيل الدخول إلى Odoo مطلوب")

    async def find_match(self, company: str, phone_norm: str) -> MatchResult:
        try:
            result = await self._find(company, phone_norm)
        except OdooLoginRequired:
            self.mark_logged_out()
            raise
        if self.last_login is None or not self.last_login.logged_in:
            self.last_login = LoginStatus(True, True)
        return result

    async def _find(self, company: str, phone_norm: str) -> MatchResult:
        company_norm = normalize_company(company)
        if phone_norm:
            found = await self.adapter.search_by_phone(phone_norm)
            ui_only = [c for c in found if c.id is None]
            by_phone = [c for c in found if c.id is not None and phones_match(c.phone, phone_norm)]
            by_mobile = [c for c in found if c.id is not None and phones_match(c.mobile, phone_norm)]
            if len(by_phone) == 1:
                return MatchResult("matched", by_phone[0], by_phone, "phone")
            if not by_phone and len(by_mobile) == 1:
                return MatchResult("matched", by_mobile[0], by_mobile, "mobile")
            strong = _dedupe(by_phone + by_mobile)
            if strong:
                same = [c for c in strong if _same_company(c, company_norm)]
                if len(same) == 1:
                    return MatchResult("matched", same[0], strong, "phone+company")
                return MatchResult("multiple", None, strong, "phone")
            if ui_only:
                return MatchResult("multiple", None, ui_only, "ui_search")
        if company_norm:
            found = await self.adapter.search_by_name(company)
            exact = [c for c in found if _same_company(c, company_norm)]
            if len(exact) == 1 and exact[0].id is not None:
                return MatchResult("matched", exact[0], exact, "company_exact")
            if exact:
                return MatchResult("multiple", None, _dedupe(exact), "company_exact")
            partial = list(found)
            core = company_core(company)
            if core and core != company_norm:
                partial += await self.adapter.search_by_name(core)
            if not partial:
                words = sorted((w for w in core.split(" ") if len(w) >= 3), key=len, reverse=True)
                if words:
                    partial += await self.adapter.search_by_name(words[0])
            scored = [(company_similarity(company, c.company_name or c.name), c) for c in _dedupe(partial)]
            scored = [(score, c) for score, c in scored if c.id is None or score >= FUZZY_THRESHOLD]
            scored.sort(key=lambda t: t[0], reverse=True)
            if scored:
                # Partial/fuzzy matches are never opened automatically.
                return MatchResult("multiple", None, [c for _, c in scored[:10]], "company_partial")
        return MatchResult("not_found", None, [], "")
