"""Follow-up reminders, end-of-day summary, quick notes and the report → queue shortcut."""
import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.errors import AgentError
from app.main import create_app
from app.utils.timeutils import localnow
from tests.test_results import prepare, save

H = {"X-KLA": "1"}


def _followup(container, fp, when, key, time=""):
    return save(container, idempotency_key=key, fingerprint=fp, result_code="FOLLOW_UP", note="يحتاج عرض سعر",
                followup_date=when.strftime("%Y-%m-%d"), followup_time=time, followup_note="اتصل بالمدير")


def test_reminder_when_time_comes(container):
    container.settings.update({"followup_remind_minutes": 5})
    lead = prepare(container)
    soon = localnow() + timedelta(minutes=3)
    if soon.date() != localnow().date():
        pytest.skip("too close to midnight")
    _followup(container, lead["fingerprint"], soon, "key-rem-001", soon.strftime("%H:%M"))
    r = container.workflow.reminders()
    assert r["enabled"] and len(r["items"]) == 1  # 3 minutes ahead is inside the 5-minute lead time
    item = r["items"][0]
    assert item["company"] == "مؤسسة الاختبار الأولى" and item["note"] == "اتصل بالمدير" and item["key"].startswith(lead["fingerprint"])
    container.settings.update({"followup_remind_minutes": 0})
    assert container.workflow.reminders()["items"] == []  # not yet
    container.settings.update({"followup_reminders": False})
    assert container.workflow.reminders()["items"] == []


def test_reminder_date_only_uses_default_time_and_overdue(container):
    lead = prepare(container)
    now = localnow()
    container.settings.update({"followup_default_time": "00:00"})
    _followup(container, lead["fingerprint"], now, "key-rem-002")
    assert len(container.workflow.reminders()["items"]) == 1
    container.settings.update({"followup_default_time": "23:59", "followup_remind_minutes": 0})
    if now.strftime("%H:%M") < "23:59":
        assert container.workflow.reminders()["items"] == []
    tomorrow = save(container, idempotency_key="key-rem-003", fingerprint=lead["fingerprint"], result_code="FOLLOW_UP",
                    followup_date=(now + timedelta(days=1)).strftime("%Y-%m-%d"))
    assert tomorrow["status"] == "done" and container.workflow.reminders()["items"] == []  # upcoming: no reminder
    with pytest.raises(Exception):
        container.settings.update({"followup_default_time": "25:00"})


def test_day_summary(container):
    lead = prepare(container)
    save(container, idempotency_key="key-day-001", fingerprint=lead["fingerprint"], result_code="INTERESTED",
         note="مهتم بنظام رصد التواجد")
    other = prepare(container, "شركة الأمل")
    _followup(container, other["fingerprint"], localnow() + timedelta(days=1), "key-day-002", "10:30")
    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        d = tc.get("/api/reports/day-summary").json()
    assert d["totals"]["calls"] == 2 and d["totals"]["interested"] == 1
    assert d["interested"][0]["company"] == "مؤسسة الاختبار الأولى" and "رصد التواجد" in d["interested"][0]["note"]
    assert [f["company"] for f in d["tomorrow"]] == ["شركة الأمل"]
    assert "متابعات الغد (1):" in d["text"] and "- 10:30 شركة الأمل — اتصل بالمدير" in d["text"]


def test_quick_notes_and_stage_mapping_settings(container):
    s = container.settings.update({"quick_notes": ["  طلب عرض سعر ", "", "مشغول"],
                                   "odoo_stage_mapping": {"INTERESTED": " Qualified ", "NO_ANSWER": ""}})
    assert s.quick_notes == ["طلب عرض سعر", "مشغول"] and s.odoo_stage_mapping == {"INTERESTED": "Qualified"}
    assert container.settings.get().day_summary_time == "17:00"


def test_report_list_becomes_the_queue(container):
    asyncio.run(container.workflow.current())
    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        r = tc.put("/api/queue/filter", json={"values": ["لم يتم الرد", "(فارغ)"]}, headers=H).json()
        assert r["lead"]["company_name"] == "مؤسسة الاختبار الأولى"  # starts from the first customer of the new list
        assert {o["value"] for o in r["filter"]["options"] if o["selected"]} == {"", "لم يتم الرد"}
        stages = tc.get("/api/odoo/stages").json()["stages"]
        assert "Qualified" in stages
        assert tc.get("/api/reminders").json()["enabled"] is True
    with pytest.raises(AgentError):
        asyncio.run(container.workflow.set_status_filter([]))
