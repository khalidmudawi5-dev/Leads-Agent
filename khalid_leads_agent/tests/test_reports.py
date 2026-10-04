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
