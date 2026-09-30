"""Shared fixtures. Only mocks and fictional data – no production Google Sheet or Odoo."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.adapters.google.mock_client import InMemorySheetsClient  # noqa: E402
from app.adapters.odoo.base import OdooLead  # noqa: E402
from app.adapters.odoo.mock_adapter import MockOdooAdapter  # noqa: E402
from app.config import EnvSettings  # noqa: E402
from app.container import build_container  # noqa: E402

# Header deliberately in a different order than the defaults and with an extra column,
# to prove columns are resolved by header text and not by letter.
HEADER = ["#", "المسؤول الحالي", "اسم المنشأة", "حالة المتابعة", "رقم الجوال", "مصدر العميل",
          "هل تم التسجيل بالنسخة التجريبية", "سبب عدم الاشتراك", "تاريخ انتهاء الاشتراك", "الملاحظات", "معادلة"]


def sample_rows() -> list[list[str]]:
    return [
        HEADER,
        ["1", "خالد", "مؤسسة الاختبار الأولى", "", "0561234567", "", "لا", "", "", "", "=A2*2"],
        ["2", "سارة", "شركة سارة", "", "0561111111", "", "", "", "", "ملاحظة سارة", ""],
        ["3", " خالد ", "شركة الأمل", "لم يتم الرد", "+966 55 222 3333", "تيك توك", "", "", "", "[01/09/2026 10:00 - خالد]\nلم يرد", ""],
        ["4", "خالد", "مصنع مكتمل", "مهتم", "0554444444", "", "", "", "", "", ""],
        ["5", "خالد", "مكتب التقنية", "متابعة", "05 6555 5555", "", "", "", "", "", ""],
    ]


VALIDATIONS = {
    ("Leads", 3): ["مهتم", "غير مهتم", "لم يتم الرد", "بيانات التواصل غير صحيحة", "متابعة", "تم الاشتراك"],
    ("Leads", 5): ["Meta || Leads", "تيك توك", "باور بي اي"],
}


def odoo_leads() -> list[OdooLead]:
    return [
        OdooLead(id=1, name="Lead الاختبار", company_name="مؤسسة الاختبار الأولى", phone="+966 56 123 4567",
                 source="Meta", medium="Leads", salesperson="خالد", stage="جديد"),
        OdooLead(id=2, name="الأمل", company_name="شركة الأمل", mobile="0552223333", source="Twajd"),
        OdooLead(id=3, name="مكتب التقنية", company_name="مكتب التقنية", phone="0565555555"),
        OdooLead(id=4, name="مكتب التقنية 2", company_name="مكتب التقنية فرع", phone="0565555555"),
    ]


@pytest.fixture
def env(tmp_path) -> EnvSettings:
    return EnvSettings(_env_file=None, data_dir=str(tmp_path / "data"), logs_dir=str(tmp_path / "logs"),
                       use_mocks=False, open_browser_on_start=False)


@pytest.fixture
def sheet() -> InMemorySheetsClient:
    return InMemorySheetsClient({"Leads": sample_rows()}, validations=VALIDATIONS)


@pytest.fixture
def odoo() -> MockOdooAdapter:
    return MockOdooAdapter(odoo_leads())


def make_container(env: EnvSettings, sheet: InMemorySheetsClient, odoo: MockOdooAdapter, **settings):
    c = build_container(env, sheets_client_factory=lambda _s: sheet, odoo_adapter=odoo)
    base = {"spreadsheet_id": "TEST-SHEET", "sheet_name": "Leads", "setup_completed": True, "dry_run": False,
            "duplicate_window_seconds": 60}
    base.update(settings)
    c.settings.update(base)
    return c


@pytest.fixture
def container(env, sheet, odoo):
    return make_container(env, sheet, odoo)
