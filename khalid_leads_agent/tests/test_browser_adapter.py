"""End-to-end tests of the real Playwright BrowserOdooAdapter against a local *fake* Odoo.

Skipped automatically when no Chromium is available. Set KLA_TEST_CHROMIUM to a Chromium
executable to force a specific browser.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.adapters.odoo.base import OdooLead
from app.config import AppSettings
from app.errors import AutomationError, OdooLoginRequired
from tests.fake_odoo.server import SESSION, FakeOdooServer

pytest.importorskip("playwright")


def _chromium_path() -> str:
    candidates = [os.environ.get("KLA_TEST_CHROMIUM", "")]
    base = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    if base.exists():
        candidates += [str(p) for p in sorted(base.glob("chromium-*/chrome-linux/chrome"), reverse=True)]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return ""


EXE = _chromium_path()


def _can_launch() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, executable_path=EXE or None)
            b.close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _can_launch(), reason="Chromium not available for Playwright")


@pytest.fixture
def fake_odoo():
    with FakeOdooServer() as srv:
        yield srv


@pytest.fixture
def adapter(fake_odoo, tmp_path):
    from app.adapters.odoo.browser_adapter import BrowserOdooAdapter

    settings = AppSettings(odoo_base_url=fake_odoo.url, browser_headless=True, browser_executable_path=EXE,
                           navigation_timeout_ms=8000, action_timeout_ms=4000, retry_attempts=1)
    ad = BrowserOdooAdapter(lambda: settings, tmp_path / "profile", tmp_path / "shots", tmp_path / "snaps")
    ad.test_settings = settings  # type: ignore[attr-defined]
    yield ad
    asyncio.run(ad.close())


def run(ad, coro):
    """All adapter calls share one event loop per test (like the web server)."""
    loop = getattr(ad, "_test_loop", None)
    if loop is None:
        loop = asyncio.new_event_loop()
        ad._test_loop = loop
    return loop.run_until_complete(coro)


def login(ad, fake):
    async def _do():  # runs inside the browser thread (Playwright objects are bound to its loop)
        ctx = await ad._w_context()
        await ctx.add_cookies([{"name": "session_id", "value": SESSION, "url": fake.url}])
    run(ad, ad._rt.submit(_do()))


def test_login_detection_and_manual_login(adapter, fake_odoo):
    st = run(adapter, adapter.login_status())
    assert not st.logged_in and st.message == "تسجيل الدخول إلى Odoo مطلوب"
    run(adapter, adapter.open_login())
    with pytest.raises(OdooLoginRequired):
        run(adapter, adapter.open_lead(OdooLead(id=7)))
    login(adapter, fake_odoo)
    st = run(adapter, adapter.login_status())
    assert st.logged_in and st.user_name == "Khalid Test"


def test_search_open_extract_call_note_activity(adapter, fake_odoo):
    login(adapter, fake_odoo)
    # search by phone in any Saudi format stored in Odoo
    found = run(adapter, adapter.search_by_phone("966561234567"))
    assert [f.id for f in found] == [7]
    assert run(adapter, adapter.search_by_name("مؤسسة الاختبار"))[0].id == 7

    lead = run(adapter, adapter.open_lead(OdooLead(id=7)))
    assert lead.company_name == "مؤسسة الاختبار" and lead.source == "Meta" and lead.medium == "Leads"
    assert lead.campaign == "حملة سبتمبر" and lead.service_type == "رصد التواجد" and lead.salesperson == "خالد"
    assert "/odoo/crm.lead/7" in lead.url

    # DOM extraction alone (RPC not used) reads labels/field names
    async def dom():
        page = await adapter._w_page()
        return await adapter._w_extract_dom(page)
    d = run(adapter, adapter._rt.submit(dom()))
    assert d["phone"] == "+966 56 123 4567" and d["source"] == "Meta" and d["stage"] == "جديد"
    assert d["service_type"] == "رصد التواجد"

    out = run(adapter, adapter.click_call(7, "phone", "+966 56 123 4567"))
    assert out.success and "o_phone_form_link" in out.message
    for _ in range(40):
        if fake_odoo.state.calls_clicked:
            break
        run(adapter, asyncio.sleep(0.05))
    assert fake_odoo.state.calls_clicked == ["tel:+966 56 123 4567"]

    body = "متابعة آلية بواسطة Khalid Leads Agent\nنتيجة التواصل: مهتم\nالمرجع: KLA-TEST0001"
    res = run(adapter, adapter.post_log_note(7, body, "KLA-TEST0001"))
    assert res.success and res.method == "ui"
    msgs = fake_odoo.state.messages
    assert len(msgs) == 1 and msgs[0]["subtype"] == "mail.mt_note"  # Log note, never "Send message"
    again = run(adapter, adapter.post_log_note(7, body, "KLA-TEST0001"))
    assert again.success and again.already_done and len(fake_odoo.state.messages) == 1

    act = run(adapter, adapter.schedule_activity(7, "2026-10-01", "متابعة", "اتصال"))
    assert act.success and fake_odoo.state.activities[0]["date_deadline"] == "2026-10-01"

    diag = run(adapter, adapter.diagnostics())
    assert diag["lead_detected"] and diag["call_button_detected"] and diag["log_note_detected"]
    assert diag["activity_detected"] and diag["source_detected"] and diag["rpc_available"]
    assert Path(run(adapter, adapter.capture_dom("t"))).exists()


def test_rpc_first_log_note(adapter, fake_odoo):
    login(adapter, fake_odoo)
    adapter.test_settings.odoo_write_method = "rpc_first"
    res = run(adapter, adapter.post_log_note(7, "note KLA-RPC00001", "KLA-RPC00001"))
    assert res.success and res.method == "rpc" and fake_odoo.state.rpc_log_notes == 1


def test_call_button_missing_takes_screenshot(adapter, fake_odoo, tmp_path):
    login(adapter, fake_odoo)
    with pytest.raises(AutomationError) as exc:
        run(adapter, adapter.click_call(8, "phone", ""))
    assert exc.value.message_ar == "تعذر العثور على زر الاتصال في Odoo."
    shot = exc.value.details["screenshot"]
    assert "odoo-call-button-not-found-" in shot and Path(shot).exists()


def test_browser_closed_by_user_is_relaunched(adapter, fake_odoo):
    login(adapter, fake_odoo)
    run(adapter, adapter.open_lead(OdooLead(id=7)))

    async def close_ctx():
        await adapter._context.close()
    run(adapter, adapter._rt.submit(close_ctx()))
    # Session cookie lived only in memory for this test, so a relaunch shows the login page again.
    st = run(adapter, adapter.login_status())
    assert st.browser_open and not st.logged_in


def test_windows_handler_mode_reads_odoo_call_link(adapter, fake_odoo, monkeypatch):
    login(adapter, fake_odoo)
    launched = []
    monkeypatch.setattr(type(adapter), "_launch_tel", staticmethod(lambda uri: launched.append(uri)))
    adapter.test_settings.call_launch_mode = "windows_handler"
    out = run(adapter, adapter.click_call(7, "phone", "0561234567"))
    assert out.success and out.method == "windows_tel"
    assert launched == ["tel:+966 56 123 4567"] and fake_odoo.state.calls_clicked == []
