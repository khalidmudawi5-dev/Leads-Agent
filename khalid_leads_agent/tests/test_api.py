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
