"""Deterministic Odoo matching (mock adapter)."""
import asyncio

from app.adapters.odoo.base import OdooLead
from app.adapters.odoo.mock_adapter import MockOdooAdapter
from app.services.odoo_service import OdooService


def run(coro):
    return asyncio.run(coro)


def svc(*leads):
    return OdooService(MockOdooAdapter(list(leads)))


def test_single_phone_match_is_strong():
    s = svc(OdooLead(id=1, company_name="أ", phone="+966 56 123 4567"), OdooLead(id=2, company_name="ب", phone="0550000000"))
    r = run(s.find_match("اسم مختلف", "966561234567"))
    assert r.status == "matched" and r.lead.id == 1 and r.strategy == "phone"


def test_mobile_match_used_when_no_phone_match():
    s = svc(OdooLead(id=1, company_name="أ", mobile="0561234567"))
    r = run(s.find_match("", "966561234567"))
    assert r.status == "matched" and r.strategy == "mobile"


def test_multiple_phone_matches_require_choice_unless_company_disambiguates():
    a = OdooLead(id=1, company_name="مكتب التقنية", phone="0565555555")
    b = OdooLead(id=2, company_name="مكتب التقنية فرع", phone="0565555555")
    r = run(svc(a, b).find_match("مكتب التقنية", "966565555555"))
    assert r.status == "matched" and r.lead.id == 1 and r.strategy == "phone+company"
    r = run(svc(a, b).find_match("شركة أخرى", "966565555555"))
    assert r.status == "multiple" and {c.id for c in r.candidates} == {1, 2}


def test_company_exact_then_partial():
    s = svc(OdooLead(id=5, company_name="مؤسسة الأفق للتجارة"), OdooLead(id=6, company_name="الأفق الذهبي"))
    r = run(s.find_match("مؤسسة الافق للتجارة", "966500000000"))  # different phone, same company (أ/ا unified)
    assert r.status == "matched" and r.lead.id == 5 and r.strategy == "company_exact"
    r = run(s.find_match("الأفق", ""))
    assert r.status == "multiple" and r.strategy == "company_partial"  # fuzzy never auto-opens


def test_not_found_never_creates():
    adapter = MockOdooAdapter([OdooLead(id=1, company_name="أ", phone="0550000000")])
    r = run(OdooService(adapter).find_match("غير موجود", "966561234567"))
    assert r.status == "not_found" and len(adapter.leads) == 1
