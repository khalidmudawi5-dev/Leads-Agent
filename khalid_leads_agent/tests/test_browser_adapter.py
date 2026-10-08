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
    def mine():
        return [m for m in fake_odoo.state.messages if "KLA-TEST0001" in m["body"]]
    assert len(mine()) == 1 and mine()[0]["subtype"] == "mail.mt_note"  # Log note, never "Send message"
    again = run(adapter, adapter.post_log_note(7, body, "KLA-TEST0001"))
    assert again.success and again.already_done and len(mine()) == 1

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
    assert not adapter.browser_started
    # A visible action relaunches the window (the saved session keeps the user signed in).
    lead = run(adapter, adapter.open_lead(OdooLead(id=7)))
    assert adapter.browser_started and lead.company_name == "مؤسسة الاختبار"


def test_windows_handler_mode_reads_odoo_call_link(adapter, fake_odoo, monkeypatch):
    login(adapter, fake_odoo)
    launched = []
    monkeypatch.setattr(type(adapter), "_launch_tel", staticmethod(lambda uri: launched.append(uri)))
    adapter.test_settings.call_launch_mode = "windows_handler"
    out = run(adapter, adapter.click_call(7, "phone", "0561234567"))
    assert out.success and out.method == "windows_tel"
    assert launched == ["tel:+966 56 123 4567"] and fake_odoo.state.calls_clicked == []


def test_chatter_history_and_activities(adapter, fake_odoo):
    login(adapter, fake_odoo)
    lead = run(adapter, adapter.get_lead(7))
    kinds = [(m["kind"], m["author"]) for m in lead.chatter]
    assert kinds == [("note", "سارة"), ("tracking", "سارة"), ("system", "OdooBot")]  # newest first
    assert lead.chatter[0]["body"] == "العميل طلب عرض سعر\nويريد التواصل مساءً"
    assert lead.chatter[1]["tracking"] == [{"field": "Stage", "old": "جديد", "new": "مؤهل"}]
    assert lead.latest_notes == ["العميل طلب عرض سعر\nويريد التواصل مساءً"]
    assert lead.write_date == "2026-09-28 10:00:00"

    run(adapter, adapter.schedule_activity(7, "2026-10-01", "اتصال متابعة", "بعد العرض"))
    lead = run(adapter, adapter.get_lead(7))
    assert [(a["date_deadline"], a["summary"]) for a in lead.activities] == [("2026-10-01", "اتصال متابعة")]


def test_live_signature_changes_on_any_odoo_edit(adapter, fake_odoo):
    assert run(adapter, adapter.lead_signature(7)) is None  # browser not started: never launched for polling
    login(adapter, fake_odoo)
    sig = run(adapter, adapter.lead_signature(7))
    assert sig and run(adapter, adapter.lead_signature(7)) == sig  # stable when nothing changed

    fake_odoo.state.edit_lead(7, stage_id=[2, "مؤهل"])  # field edit in Odoo
    sig2 = run(adapter, adapter.lead_signature(7))
    assert sig2 != sig
    fake_odoo.state.add_message(7, "ملاحظة كتبها خالد من Odoo")  # new chatter note
    sig3 = run(adapter, adapter.lead_signature(7))
    assert sig3 != sig2
    run(adapter, adapter.schedule_activity(7, "2026-10-02", "x", ""))  # new activity
    assert run(adapter, adapter.lead_signature(7)) != sig3
    lead = run(adapter, adapter.get_lead(7))
    assert lead.stage == "مؤهل" and lead.chatter[0]["body"] == "ملاحظة كتبها خالد من Odoo"


def test_dom_chatter_fallback(adapter, fake_odoo):
    login(adapter, fake_odoo)
    run(adapter, adapter.open_lead(OdooLead(id=7)))

    async def dom():
        return await adapter._w_dom_chatter(await adapter._w_page())
    rows = run(adapter, adapter._rt.submit(dom()))
    assert rows[0]["author"] == "سارة" and "عرض سعر" in rows[0]["body"] and rows[0]["date"] == "2026-09-22 14:10:00"


def test_create_lead_via_rpc(adapter, fake_odoo):
    login(adapter, fake_odoo)
    lead = run(adapter, adapter.create_lead({"name": "مؤسسة جديدة", "partner_name": "مؤسسة جديدة",
                                             "phone": "+966 55 000 1111", "contact_name": "", "type": "opportunity"}))
    assert lead.id and lead.company_name == "مؤسسة جديدة" and lead.phone == "+966 55 000 1111"
    assert lead.lead_type == "opportunity" and lead.salesperson == "Khalid Test"
    # Empty values are not sent; the logged-in user becomes the salesperson.
    assert fake_odoo.state.created == [{"name": "مؤسسة جديدة", "partner_name": "مؤسسة جديدة",
                                        "phone": "+966 55 000 1111", "type": "opportunity", "user_id": 2}]
    assert [f.id for f in run(adapter, adapter.search_by_phone("966550001111"))] == [lead.id]
    # Source/medium: linked only when a UTM record with that name exists (case-insensitive).
    other = run(adapter, adapter.create_lead({"name": "ب", "partner_name": "ب", "phone": "0550002222",
                                              "source_name": "meta", "medium_name": "Leads"}))
    assert other.source == "Meta" and other.medium == "Leads"
    assert other.utm_source == "meta"  # the "UTM Source" text field is written too
    unknown = run(adapter, adapter.create_lead({"name": "ج", "partner_name": "ج", "phone": "0550003333",
                                                "source_name": "تيك توك", "medium_name": ""}))
    assert unknown.source == "" and "source_id" not in fake_odoo.state.created[-1]
    assert unknown.utm_source == "تيك توك"


def test_utm_source_field_detection():
    from app.adapters.odoo.browser_adapter import find_utm_field
    std = {"source_id": {"string": "Source", "type": "many2one"}, "medium_id": {"string": "Medium", "type": "many2one"}}
    assert find_utm_field(std, "source") == "source_id"  # no separate field: Odoo's standard UTM source
    labelled = {**std, "x_studio_char_field_1a2b": {"string": "UTM  Source", "type": "char"}}
    assert find_utm_field(labelled, "source") == "x_studio_char_field_1a2b"
    named = {**std, "x_utm_source_id": {"string": "مصدر الحملة", "type": "many2one"}}
    assert find_utm_field(named, "source") == "x_utm_source_id"
    assert find_utm_field(named, "medium") == "medium_id"
    assert find_utm_field(labelled, "source", override="source_id") == "source_id"
    assert find_utm_field(labelled, "source", override="missing") == "x_studio_char_field_1a2b"
    not_usable = {**std, "x_utm_source_html": {"string": "UTM Source", "type": "html"}}
    assert find_utm_field(not_usable, "source") == "source_id"


def test_lead_reads_utm_source_field(adapter, fake_odoo):
    login(adapter, fake_odoo)
    lead = run(adapter, adapter.get_lead(7))
    assert lead.source == "Meta" and lead.utm_source == "Meta / Leads"
    assert lead.utm_medium == "Leads"  # no separate "UTM Medium": standard medium_id


def test_ui_search_fallback_removes_filters_ignores_samples_and_returns(adapter, fake_odoo):
    """The CRM-screen search (used when RPC is unavailable) must not leave the user on the pipeline."""
    login(adapter, fake_odoo)
    run(adapter, adapter.open_lead(OdooLead(id=7)))

    async def search(q):
        rows = await adapter._w_ui_search(q)
        return rows, (await adapter._w_page()).url

    rows, url = run(adapter, adapter._rt.submit(search("مؤسسة الاختبار")))
    assert [r.name for r in rows] == ["مؤسسة | الاختبار"]  # «My Pipeline» removed first; not the sample cards
    assert url.endswith("/odoo/crm.lead/7")  # back on the lead, not the pipeline
    rows, url = run(adapter, adapter._rt.submit(search("غير موجود")))
    assert rows == [] and url.endswith("/odoo/crm.lead/7")



@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display (run under xvfb-run)")
def test_background_reads_keep_window_minimized(fake_odoo, tmp_path):
    """Refresh/search launches the browser minimized (no blank window pops up); opening a lead shows it.

    The OS window state is simulated (a bare X server has no window manager to minimize with).
    """
    from app.adapters.odoo.browser_adapter import BrowserOdooAdapter

    settings = AppSettings(odoo_base_url=fake_odoo.url, browser_headless=False, browser_executable_path=EXE,
                           navigation_timeout_ms=8000, action_timeout_ms=4000, retry_attempts=1)
    ad = BrowserOdooAdapter(lambda: settings, tmp_path / "profile", tmp_path / "shots", tmp_path / "snaps")
    window = {"state": "normal"}

    async def fake_state(page, state=None):
        if state:
            window["state"] = state
        return window["state"]

    ad._w_window_state = fake_state
    try:
        login(ad, fake_odoo)  # launches the browser
        assert window["state"] == "minimized"
        assert [f.id for f in run(ad, ad.search_by_phone("966561234567"))] == [7]
        run(ad, ad.get_lead(7))
        assert window["state"] == "minimized"  # background reads never show the window
        run(ad, ad.open_lead(OdooLead(id=7)))
        assert window["state"] == "maximized"  # «فتح في Odoo» brings it up
    finally:
        asyncio.run(ad.close())


def test_background_reads_use_saved_session_without_a_browser(adapter, fake_odoo, tmp_path):
    """After one signed-in read, searches/reads work with the browser closed: no window is opened."""
    login(adapter, fake_odoo)
    assert run(adapter, adapter.login_status()).logged_in
    session_file = tmp_path / "odoo-session.json"
    assert session_file.exists()

    async def close_window():  # the user closes the agent's Odoo window
        await adapter._context.close()
    run(adapter, adapter._rt.submit(close_window()))
    assert not adapter.browser_started and adapter.quiet_ready

    assert [f.id for f in run(adapter, adapter.search_by_phone("966561234567"))] == [7]
    assert run(adapter, adapter.get_lead(7)).company_name == "مؤسسة الاختبار"
    assert run(adapter, adapter.lead_signature(7))  # live sync works too
    assert not adapter.browser_started  # still no browser window

    # Expired session: polling stays quiet, a real read falls back to the browser (sign-in needed).
    fake_odoo.state.session_expired = True
    with pytest.raises(OdooLoginRequired):
        run(adapter, adapter.lead_signature(7))
    assert not session_file.exists() and not adapter.browser_started
    assert run(adapter, adapter.lead_signature(7)) is None  # nothing saved any more: never launches


def test_render_pdf_with_headless_browser(adapter, tmp_path):
    report = {"statuses": ["مهتم"], "rows": [{"company": "مؤسسة الاختبار", "contact": "سعد", "phone": "+966 56 123 4567",
              "email": "test@example.com", "status": "مهتم", "utm_source": "Meta", "stage": "جديد",
              "last_note": "العميل مهتم"}], "counts": {"مهتم": 1}, "total": 1, "warnings": [], "odoo_read": True,
              "in_odoo": 1, "with_email": 1, "generated_at": "08/10/2026 10:00", "owner": "خالد"}
    from jinja2 import Environment, FileSystemLoader

    from app.services.customer_report_service import _TEMPLATES
    html = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True).get_template(
        "report_customers_print.html").render(r=report, auto_print=False)
    pdf = run(adapter, adapter.render_pdf(html))
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    (tmp_path / "r.pdf").write_bytes(pdf)
    assert adapter._context is None  # the Odoo browser window was never opened
