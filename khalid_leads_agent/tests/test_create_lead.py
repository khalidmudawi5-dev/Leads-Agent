"""Adding a customer that is missing from Odoo as a new opportunity (mock Odoo only)."""
import pytest
from fastapi.testclient import TestClient

from app.adapters.odoo.base import OdooLead
from app.main import create_app
from tests.conftest import make_container

H = {"X-KLA": "1"}


def _missing_lead(client, odoo):
    """Make the first queued customer missing from Odoo and return its fingerprint."""
    odoo.leads.pop(1)
    client.post("/api/session/start", json={"resume": True}, headers=H)
    fp = client.get("/api/lead/current").json()["lead"]["fingerprint"]
    s = client.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H).json()
    assert s["match"]["status"] == "not_found" and s["lead"]["match_status"] == "not_found"
    return fp


def _client(env, sheet, odoo, **settings):
    c = make_container(env, sheet, odoo, **settings)
    return TestClient(create_app(c, allowed_hosts=["testserver"])), c


def test_create_opportunity_links_it_and_audits(env, sheet, odoo):
    tc, c = _client(env, sheet, odoo)
    with tc:
        fp = _missing_lead(tc, odoo)
        r = tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                    json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567", "contact_name": "أحمد"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["create"]["status"] == "created" and body["create"]["type"] == "opportunity"
        assert odoo.created == [{"id": body["create"]["id"], "name": "مؤسسة الاختبار الأولى",
                                 "partner_name": "مؤسسة الاختبار الأولى", "phone": "+966 56 123 4567",
                                 "contact_name": "أحمد", "type": "opportunity", "source_name": "",
                                 "medium_name": ""}]
        lead = body["lead"]
        assert lead["match_status"] == "matched" and lead["odoo_lead_id"] == body["create"]["id"]
        assert sheet.write_calls == []  # the sheet is never touched by this action
        # Second click: already linked, no duplicate.
        again = tc.post(f"/api/lead/{fp}/create-odoo", headers=H, json={"company": "x", "phone": "0561234567"})
        assert again.status_code >= 400 and again.json()["error"]["code"] == "ALREADY_LINKED"
        assert len(odoo.created) == 1
    audits = c.db.session
    with audits() as s:
        from app.models import AuditLog
        rows = s.query(AuditLog).filter_by(action="create_lead").all()
        assert len(rows) == 1 and rows[0].success and not rows[0].dry_run


def test_dry_run_creates_nothing(env, sheet, odoo):
    tc, _ = _client(env, sheet, odoo, dry_run=True)
    with tc:
        fp = _missing_lead(tc, odoo)
        body = tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                       json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567"}).json()
        assert body["create"]["status"] == "dry_run" and odoo.created == []
        assert body["lead"]["match_status"] == "not_found"


def test_existing_phone_is_linked_not_duplicated(env, sheet, odoo):
    tc, _ = _client(env, sheet, odoo)
    with tc:
        fp = _missing_lead(tc, odoo)
        # Meanwhile someone added it in Odoo with the same number.
        odoo.leads[50] = OdooLead(id=50, name="جديد", company_name="اسم مختلف", phone="+966561234567")
        body = tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                       json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567", "force": True}).json()
        assert body["create"]["status"] == "exists" and not body["create"]["can_force"]
        assert body["lead"]["odoo_lead_id"] == 50 and odoo.created == []


def test_similar_name_needs_force(env, sheet, odoo):
    tc, _ = _client(env, sheet, odoo)
    with tc:
        fp = _missing_lead(tc, odoo)
        odoo.leads[60] = OdooLead(id=60, name="مؤسسة الاختبار الأولى للتجارة",
                                  company_name="مؤسسة الاختبار الأولى للتجارة", phone="0500000999")
        first = tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                        json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567"}).json()
        assert first["create"]["status"] == "exists" and first["create"]["can_force"]
        assert first["lead"]["match_status"] == "multiple" and odoo.created == []
        forced = tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                         json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567", "force": True}).json()
        assert forced["create"]["status"] == "created" and len(odoo.created) == 1


@pytest.mark.parametrize("payload,code", [
    ({"company": "", "phone": "0561234567"}, "COMPANY_REQUIRED"),
    ({"company": "شركة", "phone": "123"}, "PHONE_INVALID"),
])
def test_validation(env, sheet, odoo, payload, code):
    tc, _ = _client(env, sheet, odoo)
    with tc:
        fp = _missing_lead(tc, odoo)
        r = tc.post(f"/api/lead/{fp}/create-odoo", headers=H, json=payload)
        assert r.status_code >= 400 and r.json()["error"]["code"] == code and odoo.created == []


def test_create_failure_is_reported(env, sheet, odoo):
    tc, _ = _client(env, sheet, odoo)
    with tc:
        fp = _missing_lead(tc, odoo)
        odoo.fail_create = True
        r = tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                    json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567"})
        assert r.json()["error"]["code"] == "ODOO_CREATE_FAILED"
        assert tc.get("/api/lead/current").json()["lead"]["match_status"] == "not_found"


def test_lead_type_setting(env, sheet, odoo):
    tc, _ = _client(env, sheet, odoo, odoo_new_lead_type="lead")
    with tc:
        fp = _missing_lead(tc, odoo)
        body = tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                       json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567"}).json()
        assert body["create"]["type"] == "lead" and odoo.created[0]["type"] == "lead"


def _set_sheet_source(c, fp, value):
    c.workflow._update_cache(fp, sheet_source=value)


def test_sheet_source_goes_to_odoo(env, sheet, odoo):
    tc, c = _client(env, sheet, odoo)
    with tc:
        fp = _missing_lead(tc, odoo)
        _set_sheet_source(c, fp, "Meta || Leads")
        body = tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                       json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567"}).json()
        created = odoo.created[0]
        assert created["source_name"] == "Meta" and created["medium_name"] == "Leads"
        assert body["lead"]["odoo"]["source"] == "Meta" and body["warnings"] == []


def test_source_from_form_uses_saved_mapping(env, sheet, odoo):
    tc, c = _client(env, sheet, odoo)
    with tc:
        fp = _missing_lead(tc, odoo)
        c.mappings.save_source("Meta", "تيك توك")  # less specific
        c.mappings.save_source("Google / CPC", "تيك توك")  # most specific wins
        tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567", "source": "تيك توك"})
        assert odoo.created[0]["source_name"] == "Google" and odoo.created[0]["medium_name"] == "CPC"


def test_unknown_source_warns_but_creates(env, sheet, odoo):
    tc, c = _client(env, sheet, odoo)
    with tc:
        fp = _missing_lead(tc, odoo)
        body = tc.post(f"/api/lead/{fp}/create-odoo", headers=H,
                       json={"company": "مؤسسة الاختبار الأولى", "phone": "0561234567", "source": "باور بي اي"}).json()
        assert body["create"]["status"] == "created" and odoo.created[0]["source_name"] == "باور بي اي"
        assert any("باور بي اي" in w for w in body["warnings"])


def test_open_in_odoo_never_opens_bare_crm_for_missing_customer(env, sheet, odoo):
    tc, _ = _client(env, sheet, odoo)
    with tc:
        odoo.leads.pop(1)
        tc.post("/api/session/start", json={"resume": True}, headers=H)
        fp = tc.get("/api/lead/current").json()["lead"]["fingerprint"]
        # Not searched yet: «فتح في Odoo» searches first, then reports the customer as missing.
        body = tc.post(f"/api/lead/{fp}/open", headers=H).json()
        assert body["open"]["status"] == "not_found" and body["lead"]["match_status"] == "not_found"
        assert odoo.urls == []  # no CRM page was opened
        call = tc.post(f"/api/lead/{fp}/call", headers=H).json()
        assert call["error"]["code"] == "NOT_MATCHED" and call["error"]["details"]["match_status"] == "not_found"


def test_open_in_odoo_searches_then_opens_found_lead(env, sheet, odoo):
    tc, _ = _client(env, sheet, odoo)
    with tc:
        tc.post("/api/session/start", json={"resume": True}, headers=H)
        fp = tc.get("/api/lead/current").json()["lead"]["fingerprint"]
        body = tc.post(f"/api/lead/{fp}/open", headers=H).json()
        assert "open" not in body and body["lead"]["odoo_lead_id"] == 1 and odoo.opened == [1]


def test_similar_names_are_reported_as_weak_match(env, sheet, odoo):
    tc, _ = _client(env, sheet, odoo)
    with tc:
        odoo.leads.pop(1)
        odoo.leads[60] = OdooLead(id=60, name="مؤسسة الاختبار الأولى للتجارة",
                                  company_name="مؤسسة الاختبار الأولى للتجارة", phone="0500000999")
        tc.post("/api/session/start", json={"resume": True}, headers=H)
        fp = tc.get("/api/lead/current").json()["lead"]["fingerprint"]
        lead = tc.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H).json()["lead"]
        assert lead["match_status"] == "multiple" and lead["match_strategy"] == "company_partial"
