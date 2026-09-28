"""In-memory Odoo adapter for tests and development (never touches a real Odoo)."""
from __future__ import annotations

from typing import Any

from app.adapters.odoo.base import ActionOutcome, LoginStatus, OdooAdapter, OdooLead
from app.errors import AutomationError, OdooLoginRequired
from app.utils.phone import normalize_phone, phones_match
from app.utils.text import normalize_company


class MockOdooAdapter(OdooAdapter):
    def __init__(self, leads: list[OdooLead] | None = None, logged_in: bool = True) -> None:
        self.leads: dict[int, OdooLead] = {lead.id: lead for lead in (leads or []) if lead.id is not None}
        self.logged_in = logged_in
        self.notes: list[dict[str, Any]] = []
        self.activities: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.opened: list[int] = []
        self.urls: list[str] = []
        self.fail_activity = False
        self.fail_note = False
        self.fail_call = False

    def _check(self) -> None:
        if not self.logged_in:
            raise OdooLoginRequired()

    async def login_status(self) -> LoginStatus:
        return LoginStatus(self.logged_in, True, user_name="Mock User" if self.logged_in else "")

    async def open_login(self) -> None:
        self.urls.append("login")

    async def open_url(self, url: str) -> None:
        self.urls.append(url)

    async def search_by_phone(self, phone_norm: str) -> list[OdooLead]:
        self._check()
        return [lead for lead in self.leads.values()
                if phones_match(lead.phone, phone_norm) or phones_match(lead.mobile, phone_norm)]

    async def search_by_name(self, text: str) -> list[OdooLead]:
        self._check()
        needle = normalize_company(text)
        return [lead for lead in self.leads.values()
                if needle and (needle in normalize_company(lead.company_name) or needle in normalize_company(lead.name))]

    async def get_lead(self, lead_id: int) -> OdooLead:
        self._check()
        return self.leads[lead_id]

    async def open_lead(self, lead: OdooLead) -> OdooLead:
        self._check()
        assert lead.id is not None
        self.opened.append(lead.id)
        return self.leads[lead.id]

    async def click_call(self, lead_id: int, phone_field: str, phone: str) -> ActionOutcome:
        self._check()
        if self.fail_call:
            raise AutomationError("ODOO_CALL_BUTTON_NOT_FOUND", "تعذر العثور على زر الاتصال في Odoo.")
        self.calls.append({"lead_id": lead_id, "field": phone_field, "phone": normalize_phone(phone)})
        return ActionOutcome(True, "mock")

    async def post_log_note(self, lead_id: int, body: str, ref: str) -> ActionOutcome:
        self._check()
        if any(n["lead_id"] == lead_id and ref in n["body"] for n in self.notes):
            return ActionOutcome(True, "existing", already_done=True)
        if self.fail_note:
            return ActionOutcome(False, "none", "mock failure")
        self.notes.append({"lead_id": lead_id, "body": body})
        return ActionOutcome(True, "mock")

    async def schedule_activity(self, lead_id: int, date_deadline: str, summary: str, note: str) -> ActionOutcome:
        self._check()
        if self.fail_activity:
            return ActionOutcome(False, "none", "Activity creation failed: mock")
        self.activities.append({"lead_id": lead_id, "date": date_deadline, "summary": summary, "note": note})
        return ActionOutcome(True, "mock")

    async def diagnostics(self) -> dict[str, Any]:
        return {"url": "mock://odoo", "browser_open": True, "lead_detected": bool(self.opened),
                "phone_detected": True, "source_detected": True, "call_button_detected": True,
                "log_note_detected": True, "activity_detected": True, "rpc_available": True}

    async def capture_screenshot(self, name: str) -> str:
        return ""

    async def capture_dom(self, name: str) -> str:
        return ""


def demo_odoo_leads() -> list[OdooLead]:
    """Sample data for USE_MOCKS development mode (fictional)."""
    return [
        OdooLead(id=101, name="طلب عرض - مؤسسة الأفق", company_name="مؤسسة الأفق للتجارة", contact_name="أحمد",
                 phone="+966 50 000 0001", salesperson="خالد", stage="جديد", source="Meta", medium="Leads",
                 campaign="Q3", utm_source="Meta", utm_medium="Leads", utm_campaign="Q3"),
        OdooLead(id=102, name="شركة النخبة", company_name="شركة النخبة", phone="0500000002",
                 salesperson="خالد", stage="جديد", source="Twajd", medium="", campaign=""),
        OdooLead(id=103, name="مصنع الريادة", company_name="مصنع الريادة", phone="0500000003", source="Power BI"),
        OdooLead(id=104, name="مصنع الريادة - فرع 2", company_name="مصنع الريادة", phone="0500000003", source="Google"),
    ]
