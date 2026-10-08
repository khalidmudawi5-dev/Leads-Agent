"""Full workflow over HTTP with the real Playwright adapter + fake Odoo + in-memory sheet."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.google.mock_client import InMemorySheetsClient
from app.container import build_container
from app.main import create_app
from tests.conftest import HEADER, VALIDATIONS
from tests.fake_odoo.server import SESSION, FakeOdooServer
from tests.test_browser_adapter import EXE, pytestmark  # noqa: F401  (same skip condition)

H = {"X-KLA": "1"}


def test_full_workflow_real_browser(env):
    rows = [HEADER, ["1", "خالد", "مؤسسة الاختبار", "", "0561234567", "", "", "", "", "ملاحظة قديمة", "=A2"],
            ["2", "سارة", "عميل سارة", "", "0561111111", "", "", "", "", "", ""],
            ["3", "خالد", "شركة بلا زر", "", "0509876543", "", "", "", "", "", ""]]
    sheet = InMemorySheetsClient({"Leads": rows}, validations=VALIDATIONS)
    with FakeOdooServer() as fake:
        from app.adapters.odoo.browser_adapter import BrowserOdooAdapter

        c = build_container(env, sheets_client_factory=lambda _s: sheet, odoo_adapter=None)
        c.settings.update({"spreadsheet_id": "T", "sheet_name": "Leads", "setup_completed": True, "dry_run": False,
                           "call_launch_mode": "odoo_click",
                           "odoo_base_url": fake.url, "browser_headless": True, "browser_executable_path": EXE,
                           "navigation_timeout_ms": 8000, "action_timeout_ms": 4000})
        adapter = BrowserOdooAdapter(c.settings.get, env.data_path / "browser-profile", env.logs_path / "screenshots",
                                     env.logs_path / "snapshots")
        c.odoo.adapter = adapter
        app = create_app(c, allowed_hosts=["testserver"])
        with TestClient(app) as client:
            # not logged in yet → clear Arabic message
            client.post("/api/session/start", json={"resume": True}, headers=H)
            lead = client.get("/api/lead/current").json()["lead"]
            r = client.post(f"/api/lead/{lead['fingerprint']}/search", json={"query": ""}, headers=H)
            assert r.status_code == 401 and r.json()["error"]["message"] == "تسجيل الدخول إلى Odoo مطلوب"

            async def _login():
                ctx = await adapter._w_context()
                await ctx.add_cookies([{"name": "session_id", "value": SESSION, "url": fake.url}])
            import asyncio
            asyncio.run(adapter._rt.submit(_login()))
            assert client.post("/api/odoo/check-login", headers=H).json()["logged_in"]

            s = client.post(f"/api/lead/{lead['fingerprint']}/search", json={"query": ""}, headers=H).json()
            assert s["match"]["status"] == "matched" and s["lead"]["odoo"]["source"] == "Meta"
            # The source comes from the Studio field labelled "UTM Source", not from Source (source_id).
            assert s["lead"]["odoo"]["utm_source"] == "Meta / Leads"
            assert s["lead"]["source"]["odoo_value"] == "Meta / Leads" and s["lead"]["source"]["mapped"]
            assert s["lead"]["source"]["prefill"] == "Meta || Leads"  # identical sheet dropdown value
            # …and «مصدر العميل» is written to the sheet as soon as the lead is matched.
            assert sheet.sheets["Leads"][1][5] == "Meta || Leads" and s["notices"]

            call = client.post(f"/api/lead/{lead['fingerprint']}/call", headers=H).json()
            assert call["phone_field"] == "phone"

            res = client.post("/api/result", headers=H, json={
                "idempotency_key": "e2e-key-0001", "fingerprint": lead["fingerprint"], "result_code": "FOLLOW_UP",
                "note": "العميل مهتم بنظام رصد التواجد", "followup_date": "2026-10-01", "followup_time": "10:00",
                "source_value": "Meta || Leads", "save_source_mapping": True, "source_odoo_value": "Meta / Leads"}).json()
            assert res["status"] == "done", res
            assert res["odoo_note_status"] == "success" and res["odoo_activity_status"] == "success"
            assert res["sheet_status"] == "success"
            agent_notes = [m for m in fake.state.messages if "نتيجة التواصل" in m["body"]]
            assert len(agent_notes) == 1 and "نتيجة التواصل: متابعة لاحقًا" in agent_notes[0]["body"]
            assert fake.state.activities[0]["date_deadline"] == "2026-10-01"
            row = sheet.sheets["Leads"][1]
            assert row[3] == "متابعة" and row[5] == "Meta || Leads" and row[10] == "=A2"
            # One line, without name or date/time, appended after the old note.
            assert row[9] == "ملاحظة قديمة | العميل مهتم بنظام رصد التواجد - موعد المتابعة: 2026-10-01 10:00"
            assert sheet.sheets["Leads"][2][3] == ""  # other user's row untouched

            nxt = client.post("/api/lead/next", headers=H).json()
            assert nxt["lead"]["company_name"] == "شركة بلا زر"
            assert nxt["stats"]["follow_up"] == 1
