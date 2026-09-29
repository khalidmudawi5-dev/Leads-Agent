"""HTTP layer: startup, HTML routes, static files, CSRF, errors in Arabic without stack traces."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_container

H = {"X-KLA": "1"}


@pytest.fixture
def client(env, sheet, odoo):
    c = make_container(env, sheet, odoo, dry_run=True)
    app = create_app(c, allowed_hosts=["testserver"])
    with TestClient(app) as tc:
        yield tc


def test_pages_and_static(client):
    for path in ["/", "/history", "/skipped", "/errors", "/settings", "/diagnostics", "/setup"]:
        r = client.get(path)
        assert r.status_code == 200 and 'dir="rtl"' in r.text, path
    for path in ["/static/css/app.css", "/static/js/app.js", "/static/js/dashboard.js", "/static/js/settings.js",
                 "/static/js/setup.js", "/static/js/history.js", "/static/fonts/tajawal.css",
                 "/static/fonts/tajawal-arabic-400.woff2", "/static/fonts/tajawal-arabic-700.woff2"]:
        assert client.get(path).status_code == 200, path


def test_setup_redirect_when_incomplete(env, sheet, odoo):
    c = make_container(env, sheet, odoo, setup_completed=False)
    with TestClient(create_app(c, allowed_hosts=["testserver"])) as tc:
        r = tc.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/setup"


def test_csrf_header_required(client):
    assert client.post("/api/lead/next").status_code == 403
    assert client.post("/api/lead/next", headers={**H, "Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/lead/next", headers=H).status_code == 200


def test_untrusted_host_rejected(env, sheet, odoo):
    c = make_container(env, sheet, odoo)
    with TestClient(create_app(c)) as tc:  # default: only 127.0.0.1 / localhost
        assert tc.get("/api/status").status_code == 400


def test_full_dry_run_flow_over_http(client, sheet, odoo):
    client.post("/api/session/start", json={"resume": True}, headers=H)
    cur = client.get("/api/lead/current").json()
    fp = cur["lead"]["fingerprint"]
    assert cur["stats"]["owner_total"] == 4 and cur["stats"]["pending"] == 3
    s = client.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H).json()
    assert s["match"]["status"] == "matched"
    call = client.post(f"/api/lead/{fp}/call", headers=H).json()
    assert call["phone_field"] == "phone" and odoo.calls
    res = client.post("/api/result", json={"idempotency_key": "http-key-01", "fingerprint": fp,
                                           "result_code": "NO_ANSWER"}, headers=H).json()
    assert res["dry_run"] and sheet.write_calls == [] and odoo.notes == []
    hist = client.get("/api/history?period=today").json()
    assert hist["items"][0]["google"] == "dry_run"
    audit = client.get("/api/audit").json()["items"]
    assert {a["system"] for a in audit} == {"GOOGLE_SHEETS", "ODOO"}


def test_errors_are_arabic_without_stack_trace(client, odoo):
    odoo.logged_in = False
    client.post("/api/session/start", json={"resume": True}, headers=H)
    fp = client.get("/api/lead/current").json()["lead"]["fingerprint"]
    r = client.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H)
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["message"] == "تسجيل الدخول إلى Odoo مطلوب" and "open_login" in err["actions"]
    assert "Traceback" not in r.text
    assert client.get("/api/errors").json()["items"][0]["code"] == "ODOO_LOGIN_REQUIRED"


def test_call_button_missing_error(client, odoo):
    odoo.fail_call = True
    client.put("/api/settings", json={"call_launch_mode": "odoo_click"}, headers=H)
    client.post("/api/session/start", json={"resume": True}, headers=H)
    fp = client.get("/api/lead/current").json()["lead"]["fingerprint"]
    client.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H)
    r = client.post(f"/api/lead/{fp}/call", headers=H).json()["error"]
    assert r["message"] == "تعذر العثور على زر الاتصال في Odoo." and r["actions"] == ["retry", "open_odoo", "skip"]


def test_settings_and_mappings_api(client):
    s = client.get("/api/settings").json()
    assert s["settings"]["dry_run"] is True and "company_name" in s["column_labels"]
    r = client.put("/api/settings", json={"next_lead_delay_seconds": 5, "pending_status_values": ["", "متابعة"]}, headers=H)
    assert r.json()["settings"]["next_lead_delay_seconds"] == 5
    assert client.put("/api/settings", json={"next_lead_delay_seconds": 999}, headers=H).status_code == 400
    r = client.post("/api/settings/source-mapping", json={"odoo_value": "Twajd", "sheet_value": "تيك توك"}, headers=H).json()
    assert r["items"][0]["sheet_value"] == "تيك توك"
    opts = client.get("/api/sheet/options/followup_status").json()["options"]
    assert "لم يتم الرد" in opts
    hdr = client.get("/api/sheet/headers").json()
    assert hdr["missing"] == [] and hdr["columns"]["owner"] == "المسؤول الحالي"
    t = client.post("/api/google/test", headers=H).json()
    assert t["owner_rows"] == 4 and t["tabs"] == ["Leads"]


def test_unexpected_error_hidden(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(client.app.state.container.workflow, "stats", boom)
    r = TestClient(client.app, raise_server_exceptions=False).get("/api/stats")
    assert r.status_code == 500 and "secret" not in r.text and "logs/agent.log" in r.json()["error"]["message"]


def test_live_sync_refreshes_lead_when_odoo_changes(client, odoo):
    client.post("/api/session/start", json={"resume": True}, headers=H)
    fp = client.get("/api/lead/current").json()["lead"]["fingerprint"]
    client.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H)
    lead_id = client.get("/api/lead/current").json()["lead"]["odoo_lead_id"]

    first = client.get(f"/api/lead/{fp}/live").json()  # baseline only
    assert first["changed"] is False and first["signature"] and first["enabled"]
    same = client.get(f"/api/lead/{fp}/live", params={"since": first["signature"]}).json()
    assert same["changed"] is False and "lead" not in same

    odoo.leads[lead_id].stage = "مؤهل"  # the user edits the lead directly in Odoo…
    odoo.touch(lead_id)
    upd = client.get(f"/api/lead/{fp}/live", params={"since": first["signature"]}).json()
    assert upd["changed"] is True and upd["signature"] != first["signature"]
    assert upd["lead"]["odoo"]["stage"] == "مؤهل"
    assert client.get("/api/lead/current").json()["lead"]["odoo"]["stage"] == "مؤهل"  # cached too

    manual = client.get(f"/api/manual/{lead_id}/live", params={"since": "old"}).json()
    assert manual["changed"] and manual["odoo"]["id"] == lead_id

    odoo.logged_in = False  # polling never raises / never logs errors
    quiet = client.get(f"/api/lead/{fp}/live", params={"since": upd["signature"]})
    assert quiet.status_code == 200 and quiet.json()["login_required"] is True
    assert client.get("/api/errors").json()["items"] == []


def test_live_sync_can_be_disabled(client, odoo):
    client.put("/api/settings", json={"live_sync_enabled": False}, headers=H)
    client.post("/api/session/start", json={"resume": True}, headers=H)
    fp = client.get("/api/lead/current").json()["lead"]["fingerprint"]
    client.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H)
    r = client.get(f"/api/lead/{fp}/live", params={"since": "x"}).json()
    assert r == {"changed": False, "enabled": False, "interval": 5, "signature": "x"}


def test_status_filter_choose_what_the_queue_looks_for(client, sheet):
    client.post("/api/session/start", json={"resume": True}, headers=H)
    f = client.get("/api/queue/filter").json()
    opts = {o["value"]: o for o in f["options"]}
    # empty cell first, then the sheet dropdown values, with the owner's row counts
    assert f["options"][0]["empty"] and opts[""]["count"] == 1 and opts[""]["selected"]
    assert opts["لم يتم الرد"]["count"] == 1 and opts["لم يتم الرد"]["selected"]
    assert opts["مهتم"]["count"] == 1 and not opts["مهتم"]["selected"]
    assert "غير مهتم" in opts and opts["غير مهتم"]["count"] == 0
    assert client.get("/api/lead/current").json()["stats"]["pending"] == 3

    # Look only for "مهتم": queue switches to that lead immediately; sheet untouched
    r = client.put("/api/queue/filter", json={"values": ["مهتم"]}, headers=H).json()
    assert r["lead"]["company_name"] == "مصنع مكتمل" and r["stats"]["pending"] == 1
    assert [o["value"] for o in r["filter"]["options"] if o["selected"]] == ["مهتم"]
    assert sheet.write_calls == []

    # Interested + no answer + empty cell
    r = client.put("/api/queue/filter", json={"values": ["مهتم", "لم يتم الرد", "(فارغ)"]}, headers=H).json()
    assert r["stats"]["pending"] == 3
    assert client.get("/api/settings").json()["settings"]["pending_status_values"] == ["مهتم", "لم يتم الرد", ""]

    bad = client.put("/api/queue/filter", json={"values": []}, headers=H)
    assert bad.status_code == 400 and bad.json()["error"]["message"] == "اختر حالة متابعة واحدة على الأقل."
    assert client.get("/api/errors").json()["items"] == []



def _matched_lead(client):
    client.post("/api/session/start", json={"resume": True}, headers=H)
    fp = client.get("/api/lead/current").json()["lead"]["fingerprint"]
    return client.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H).json()["lead"]


def test_fast_call_is_default_and_skips_the_browser(client, odoo):
    assert client.get("/api/settings").json()["settings"]["call_launch_mode"] == "fast"
    lead = _matched_lead(client)
    assert lead["phone_check"]["status"] == "ok" and lead["phone_check"]["target"]["field"] == "phone"
    opened_before = list(odoo.opened)
    r = client.post(f"/api/lead/{lead['fingerprint']}/call", headers=H).json()
    assert r["method"] == "fast_tel" and r["tel"] == "+966561234567" and r["warnings"] == []
    assert odoo.calls[-1]["tel"] == "tel:+966561234567" and odoo.opened == opened_before  # no page navigation


def test_wrong_odoo_number_is_reported_and_blocked(client, odoo):
    odoo.leads[1].phone = "056123456"  # one digit missing in Odoo (sheet has 0561234567)
    client.post("/api/session/start", json={"resume": True}, headers=H)
    fp = client.get("/api/lead/current").json()["lead"]["fingerprint"]
    client.post(f"/api/lead/{fp}/search", json={"query": "0561234567"}, headers=H)
    client.post(f"/api/lead/{fp}/select", json={"odoo_id": 1}, headers=H)
    lead = client.get("/api/lead/current").json()["lead"]
    pc = lead["phone_check"]
    assert pc["status"] == "error" and any("ناقص 1 رقم" in p for p in pc["problems"])
    assert any("يختلف عن رقم Google Sheet" in p for p in pc["problems"])

    r = client.post(f"/api/lead/{fp}/call", headers=H)
    err = r.json()["error"]
    assert r.status_code == 409 and err["code"] == "PHONE_INVALID" and "ناقص 1 رقم" in err["message"]
    assert err["actions"] == ["call_sheet", "call_anyway", "open_odoo"] and err["details"]["sheet_phone"] == "0561234567"
    assert odoo.calls == []  # nothing dialed
    assert client.get("/api/errors").json()["items"] == []  # a data warning, not a system error

    r = client.post(f"/api/lead/{fp}/call", json={"target": "sheet"}, headers=H).json()
    assert r["phone_field"] == "sheet" and odoo.calls[-1]["tel"] == "tel:+966561234567"
    r = client.post(f"/api/lead/{fp}/call", json={"force": True}, headers=H).json()
    assert r["phone_field"] == "phone" and odoo.calls[-1]["tel"] == "tel:056123456"


def test_card_lists_and_goto_lead(client):
    client.post("/api/session/start", json={"resume": True}, headers=H)
    first = client.get("/api/lead/current").json()["lead"]
    pend = client.get("/api/queue/list", params={"kind": "pending"}).json()["items"]
    everyone = client.get("/api/queue/list", params={"kind": "all"}).json()["items"]
    assert len(pend) == 3 and len(everyone) == 4 and pend[0]["current"]
    assert pend[0]["phone"] == "+966 56 123 4567"  # uniform display
    target = pend[-1]
    r = client.post(f"/api/lead/{target['fingerprint']}/goto", headers=H).json()
    assert r["lead"]["fingerprint"] == target["fingerprint"] != first["fingerprint"]
    assert client.get("/api/lead/current").json()["lead"]["fingerprint"] == target["fingerprint"]
    assert client.get("/api/queue/list", params={"kind": "bad"}).status_code == 400


def test_history_shows_odoo_phone_when_sheet_has_none(client, sheet, odoo):
    sheet.sheets["Leads"][5][4] = ""  # «مكتب التقنية»: no number in the sheet
    client.put("/api/queue/filter", json={"values": ["متابعة"]}, headers=H)
    client.post("/api/session/start", json={"resume": True}, headers=H)
    lead = client.get("/api/lead/current").json()["lead"]
    assert lead["company_name"] == "مكتب التقنية" and lead["phone"] == ""
    client.post(f"/api/lead/{lead['fingerprint']}/search", json={"query": "مكتب التقنية"}, headers=H)
    client.post(f"/api/lead/{lead['fingerprint']}/select", json={"odoo_id": 3}, headers=H)
    client.post("/api/result", json={"idempotency_key": "hist-phone-1", "fingerprint": lead["fingerprint"],
                                     "result_code": "NO_ANSWER"}, headers=H)
    item = client.get("/api/history?period=today").json()["items"][0]
    assert item["phone"] == "+966 56 555 5555"
