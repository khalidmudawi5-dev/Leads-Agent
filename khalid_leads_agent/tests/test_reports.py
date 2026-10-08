"""Reports: counts, rates, per source, per day, Excel export (opened with openpyxl when available)."""
import asyncio
import io

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.utils.timeutils import localnow
from tests.test_results import prepare, save


def _seed(container):
    container.settings.update({"duplicate_window_seconds": 0})
    a = prepare(container)
    b = prepare(container, "شركة الأمل")
    save(container, idempotency_key="report-001", fingerprint=a["fingerprint"], result_code="NO_ANSWER")
    save(container, idempotency_key="report-002", fingerprint=a["fingerprint"], result_code="INTERESTED",
         source_value="Meta || Leads", note="مهتم")
    save(container, idempotency_key="report-003", fingerprint=b["fingerprint"], result_code="SUBSCRIBED",
         subscription_expiry="2027-01-01")
    asyncio.run(container.whatsapp.send(a["fingerprint"], "0561234567", "مرحبا", "متابعة"))
    container.settings.update({"dry_run": True})
    save(container, idempotency_key="report-004", fingerprint=b["fingerprint"], result_code="NOT_INTERESTED")  # not counted
    container.settings.update({"dry_run": False})


def test_report_numbers(container):
    _seed(container)
    rep = container.reports.public(container.reports.build("today"))
    t = rep["totals"]
    assert t["calls"] == 3 and t["answered"] == 2 and t["answer_rate"] == 66.7
    assert t["interested"] == 1 and t["subscribed"] == 1 and t["interest_rate"] == 100.0
    assert t["whatsapp"] == 1 and t["customers"] == 2
    src = {s["source"]: s for s in rep["by_source"]}
    assert src["Meta || Leads"]["interested"] == 1 and src["تيك توك"]["subscribed"] == 1  # sheet source fallback
    assert rep["by_day"] == [{"date": localnow().date().isoformat(), "calls": 3}]
    week = container.reports.build("week")
    assert len(week["by_day"]) == (localnow().date().weekday() + 1) % 7 + 1


def test_custom_period_validation(container):
    with pytest.raises(Exception):
        container.reports.build("custom", "bad", "")
    rep = container.reports.build("custom", "2026-01-10", "2026-01-01")  # swapped
    assert rep["start"] == "2026-01-01" and len(rep["by_day"]) == 10


def test_excel_export_opens(container):
    openpyxl = pytest.importorskip("openpyxl")
    _seed(container)
    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        r = tc.get("/api/reports/export?period=today")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        assert tc.get("/reports").status_code == 200
        assert tc.get("/api/reports?period=month").json()["totals"]["calls"] == 3
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["الملخص", "حسب اليوم", "حسب المصدر", "التفاصيل", "واتساب"]
    ws = wb["الملخص"]
    assert ws["A1"].value == "المؤشر" and ws["A1"].font.bold and ws.sheet_view.rightToLeft
    assert ws["B3"].value == 3  # numbers stay numbers
    details = list(wb["التفاصيل"].values)
    assert len(details) == 4 and details[2][1] == "مؤسسة الاختبار الأولى" and details[2][5] == "مهتم"
    assert list(wb["واتساب"].values)[1][4] == "مرحبا"


# ---------------------------------------------------------------- customers by status
H = {"X-KLA": "1"}


def test_customer_report_reads_odoo_and_writes_nothing(container, sheet, odoo):
    odoo.leads[2].email, odoo.leads[2].contact_name, odoo.leads[2].utm_source = "amal@example.com", "سعد", "Twajd"
    rep = asyncio.run(container.customer_report.build(["لم يتم الرد", "مهتم"]))
    by_company = {r["company"]: r for r in rep["rows"]}
    amal = by_company["شركة الأمل"]  # unlinked in the sheet → found in Odoo by its mobile
    assert amal["email"] == "amal@example.com" and amal["contact"] == "سعد" and amal["status"] == "لم يتم الرد"
    assert amal["phone"] and amal["utm_source"] == "Twajd" and amal["odoo_url"].endswith("/2")
    assert amal["last_note"] == "لم يرد"
    assert by_company["مصنع مكتمل"]["in_odoo"] is False and by_company["مصنع مكتمل"]["email"] == ""
    assert rep["total"] == 2 and rep["counts"] == {"لم يتم الرد": 1, "مهتم": 1} and rep["with_email"] == 1
    assert sheet.write_calls == [] and odoo.notes == []  # read-only
    empty = asyncio.run(container.customer_report.build(["(فارغ)"], search_unlinked=False))
    assert [r["company"] for r in empty["rows"]] == ["مؤسسة الاختبار الأولى"]


def test_customer_report_without_odoo_login(container, odoo):
    odoo.logged_in = False
    rep = asyncio.run(container.customer_report.build(["لم يتم الرد"]))
    assert rep["total"] == 1 and not rep["odoo_read"] and rep["rows"][0]["email"] == ""
    assert any("Odoo" in w for w in rep["warnings"])


def test_customer_report_exports(container, odoo):
    openpyxl = pytest.importorskip("openpyxl")
    odoo.leads[2].email = "amal@example.com"
    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        opts = tc.get("/api/reports/customers/options").json()["options"]
        assert any(o["value"] == "لم يتم الرد" and o["count"] == 1 for o in opts)
        r = tc.post("/api/reports/customers", json={"statuses": ["لم يتم الرد"]}, headers=H).json()
        assert r["rows"][0]["email"] == "amal@example.com"
        x = tc.get("/api/reports/customers/export", params={"fmt": "xlsx", "statuses": ["لم يتم الرد"]})
        assert x.status_code == 200 and ".xlsx" in x.headers["content-disposition"]
        p = tc.get("/api/reports/customers/export", params={"fmt": "pdf", "statuses": ["لم يتم الرد"]})
        assert p.status_code == 200 and p.headers["content-type"] == "application/pdf" and p.content.startswith(b"%PDF")
        assert "amal@example.com" in odoo.pdf_html and 'dir="rtl"' in odoo.pdf_html
        h = tc.get("/api/reports/customers/export", params={"fmt": "print", "statuses": ["لم يتم الرد"]})
        assert "window.print" in h.text and "شركة الأمل" in h.text
        bad = tc.post("/api/reports/customers", json={"statuses": []}, headers=H)
        assert bad.status_code >= 400
    rows = list(openpyxl.load_workbook(io.BytesIO(x.content))["العملاء"].values)
    assert rows[0][0] == "المنشأة" and rows[1][0] == "شركة الأمل" and rows[1][3] == "amal@example.com"
