"""In-memory Odoo adapter for tests and development (never touches a real Odoo)."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.adapters.odoo.base import ActionOutcome, LoginStatus, OdooAdapter, OdooLead
from app.errors import AgentError, AutomationError, OdooLoginRequired
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
        self.versions: dict[int, int] = {}
        self.created: list[dict[str, Any]] = []
        self.fail_create = False

    def touch(self, lead_id: int) -> None:
        """Simulate an edit made directly in Odoo (changes the live-sync signature)."""
        self.versions[lead_id] = self.versions.get(lead_id, 0) + 1

    def _with_history(self, lead: OdooLead) -> OdooLead:
        """Copy of ``lead`` whose chatter/activities include what this mock has written."""
        assert lead.id is not None
        notes = [{"id": 1000 + i, "date": "", "author": "Mock User", "kind": "note", "subtype": "Note",
                  "body": n["body"], "tracking": []} for i, n in enumerate(self.notes) if n["lead_id"] == lead.id]
        acts = [{"id": 1000 + i, "date_deadline": a["date"], "summary": a["summary"], "type": "To-Do",
                 "user": "Mock User", "note": a["note"], "state": "planned"}
                for i, a in enumerate(self.activities) if a["lead_id"] == lead.id]
        return replace(lead, chatter=notes[::-1] + list(lead.chatter), activities=list(lead.activities) + acts)

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
        return self._with_history(self.leads[lead_id])

    async def open_lead(self, lead: OdooLead) -> OdooLead:
        self._check()
        assert lead.id is not None
        self.opened.append(lead.id)
        return self._with_history(self.leads[lead.id])

    async def click_call(self, lead_id: int, phone_field: str, phone: str) -> ActionOutcome:
        self._check()
        if self.fail_call:
            raise AutomationError("ODOO_CALL_BUTTON_NOT_FOUND", "تعذر العثور على زر الاتصال في Odoo.")
        self.calls.append({"lead_id": lead_id, "field": phone_field, "phone": normalize_phone(phone)})
        return ActionOutcome(True, "mock")

    async def launch_tel(self, tel_uri: str) -> ActionOutcome:
        if self.fail_call:
            raise AutomationError("CALL_LAUNCH_FAILED", "تعذر تشغيل الاتصال عبر Windows.")
        self.calls.append({"lead_id": None, "field": "tel", "phone": normalize_phone(tel_uri), "tel": tel_uri})
        return ActionOutcome(True, "fast_tel", tel_uri)

    async def post_log_note(self, lead_id: int, body: str, ref: str) -> ActionOutcome:
        self._check()
        snippets = [x for x in ref.split("\n") if x.strip()]
        if snippets and any(n["lead_id"] == lead_id and all(x in n["body"] for x in snippets) for n in self.notes):
            return ActionOutcome(True, "existing", already_done=True)
        if self.fail_note:
            return ActionOutcome(False, "none", "mock failure")
        self.notes.append({"lead_id": lead_id, "body": body})
        self.touch(lead_id)
        return ActionOutcome(True, "mock")

    async def schedule_activity(self, lead_id: int, date_deadline: str, summary: str, note: str) -> ActionOutcome:
        self._check()
        if self.fail_activity:
            return ActionOutcome(False, "none", "Activity creation failed: mock")
        self.activities.append({"lead_id": lead_id, "date": date_deadline, "summary": summary, "note": note})
        self.touch(lead_id)
        return ActionOutcome(True, "mock")

    async def create_lead(self, values: dict[str, Any]) -> OdooLead:
        self._check()
        if self.fail_create:
            raise AgentError("ODOO_CREATE_FAILED", "تعذر إضافة العميل إلى Odoo: mock failure", actions=["retry"])
        new_id = max(self.leads, default=0) + 1
        self.created.append({"id": new_id, **values})
        lead = OdooLead(id=new_id, name=values.get("name", ""), company_name=values.get("partner_name", ""),
                        contact_name=values.get("contact_name", ""), phone=values.get("phone", ""),
                        salesperson="Mock User", stage="جديد", lead_type=values.get("type", ""))
        self.leads[new_id] = lead
        return self._with_history(lead)

    async def lead_signature(self, lead_id: int) -> str | None:
        self._check()
        if lead_id not in self.leads:
            return None
        return f"v{self.versions.get(lead_id, 0)}"

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
                 campaign="Q3", utm_source="Meta", utm_medium="Leads", utm_campaign="Q3",
                 chatter=[
                     {"id": 3, "date": "2026-09-27 09:15:00", "author": "خالد", "kind": "note", "subtype": "Note",
                      "body": "تواصلت مع العميل وطلب الاتصال بعد أسبوع لأن المدير مسافر.", "tracking": []},
                     {"id": 2, "date": "2026-09-25 13:02:00", "author": "OdooBot", "kind": "tracking", "subtype": "",
                      "body": "", "tracking": [{"field": "Stage", "old": "New", "new": "Qualified"}]},
                     {"id": 1, "date": "2026-09-24 08:40:00", "author": "Meta Lead Ads", "kind": "email",
                      "subtype": "", "body": "طلب عرض سعر لنظام رصد التواجد لعدد 45 موظف.", "tracking": []},
                 ],
                 activities=[{"id": 1, "date_deadline": "2026-10-01", "summary": "اتصال متابعة", "type": "Call",
                              "user": "خالد", "note": "", "state": "planned"}]),
        OdooLead(id=102, name="شركة النخبة", company_name="شركة النخبة", phone="0500000002",
                 salesperson="خالد", stage="جديد", source="Twajd", medium="", campaign=""),
        OdooLead(id=103, name="مصنع الريادة", company_name="مصنع الريادة", phone="0500000003", source="Power BI"),
        OdooLead(id=104, name="مصنع الريادة - فرع 2", company_name="مصنع الريادة", phone="0500000003", source="Google"),
    ]
