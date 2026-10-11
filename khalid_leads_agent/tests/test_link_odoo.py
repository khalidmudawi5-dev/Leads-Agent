"""«ربط بعميل في Odoo»: link the customer in front of the user to a lead found by another name/number."""
from fastapi.testclient import TestClient

from app.adapters.odoo.base import OdooLead
from app.main import create_app
from tests.conftest import make_container

H = {"X-KLA": "1"}


def _setup(env, sheet, odoo, **settings):
    """The first customer is in Odoo under another name and without its number."""
    odoo.leads.pop(1)
    odoo.leads[9] = OdooLead(id=9, name="أبو محمد", company_name="مؤسسة باسم مختلف", phone="0112223333")
    c = make_container(env, sheet, odoo, **settings)
    tc = TestClient(create_app(c, allowed_hosts=["testserver"]))
    return tc, c


def _missing(tc):
    tc.post("/api/session/start", json={"resume": True}, headers=H)
    fp = tc.get("/api/lead/current").json()["lead"]["fingerprint"]
    assert tc.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H).json()["match"]["status"] == "not_found"
    return fp


def test_link_found_customer_and_add_the_sheet_number(env, sheet, odoo):
    tc, c = _setup(env, sheet, odoo)
    with tc:
        fp = _missing(tc)
        found = tc.post("/api/manual/search", json={"query": "باسم مختلف"}, headers=H).json()["candidates"]
        assert [x["id"] for x in found] == [9]
        body = tc.post(f"/api/lead/{fp}/link", json={"odoo_id": 9}, headers=H).json()
        lead = body["lead"]
        assert lead["match_status"] == "matched" and lead["odoo_lead_id"] == 9 and lead["match_strategy"] == "user_link"
        assert odoo.phone_writes == [{"id": 9, "mobile": "+966 56 123 4567"}]  # empty Mobile filled, Phone kept
        assert odoo.leads[9].phone == "0112223333"
        assert any("سيتطابق تلقائيًا" in n for n in body["notices"])
        assert sheet.write_calls == []
        # Next time the customer is matched on its own, by phone.
        again = tc.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H).json()
        assert again["match"]["status"] == "matched" and again["lead"]["odoo_lead_id"] == 9
    from app.models import AuditLog
    with c.db.session() as s:
        assert s.query(AuditLog).filter_by(action="link_add_phone", success=True).count() == 1


def test_link_without_adding_the_number(env, sheet, odoo):
    tc, _ = _setup(env, sheet, odoo)
    with tc:
        fp = _missing(tc)
        body = tc.post(f"/api/lead/{fp}/link", json={"odoo_id": 9, "add_phone": False}, headers=H).json()
        assert body["lead"]["odoo_lead_id"] == 9 and odoo.phone_writes == []


def test_link_in_dry_run_writes_nothing(env, sheet, odoo):
    tc, _ = _setup(env, sheet, odoo, dry_run=True)
    with tc:
        fp = _missing(tc)
        body = tc.post(f"/api/lead/{fp}/link", json={"odoo_id": 9}, headers=H).json()
        assert body["lead"]["odoo_lead_id"] == 9 and odoo.phone_writes == []
        assert any("Dry Run" in n for n in body["notices"])


def test_link_never_overwrites_existing_numbers(env, sheet, odoo):
    odoo.leads[9] = OdooLead(id=9, name="x", company_name="مؤسسة باسم مختلف", phone="0112223333", mobile="0559998888")
    tc, _ = _setup(env, sheet, odoo)
    odoo.leads[9].mobile = "0559998888"
    with tc:
        fp = _missing(tc)
        body = tc.post(f"/api/lead/{fp}/link", json={"odoo_id": 9}, headers=H).json()
        assert body["lead"]["odoo_lead_id"] == 9 and odoo.phone_writes == []
        assert any("رقمان آخران" in w for w in body["warnings"])
        assert odoo.leads[9].mobile == "0559998888"


def test_relink_a_wrongly_matched_customer(env, sheet, odoo):
    c = make_container(env, sheet, odoo)
    with TestClient(create_app(c, allowed_hosts=["testserver"])) as tc:
        tc.post("/api/session/start", json={"resume": True}, headers=H)
        fp = tc.get("/api/lead/current").json()["lead"]["fingerprint"]
        assert tc.post(f"/api/lead/{fp}/search", json={"query": ""}, headers=H).json()["lead"]["odoo_lead_id"] == 1
        body = tc.post(f"/api/lead/{fp}/link", json={"odoo_id": 3}, headers=H).json()
        assert body["lead"]["odoo_lead_id"] == 3 and body["lead"]["match_strategy"] == "user_link"
