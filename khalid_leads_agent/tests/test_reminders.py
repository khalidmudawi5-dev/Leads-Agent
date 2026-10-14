"""Quick notes, the day-summary time and the report → queue shortcut."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.errors import AgentError
from app.main import create_app
from tests.test_results import save

H = {"X-KLA": "1"}


def _followup(container, fp, when, key, time=""):
    return save(container, idempotency_key=key, fingerprint=fp, result_code="FOLLOW_UP", note="يحتاج عرض سعر",
                followup_date=when.strftime("%Y-%m-%d"), followup_time=time, followup_note="اتصل بالمدير")


def test_quick_notes_and_summary_time_settings(container):
    s = container.settings.update({"quick_notes": ["  طلب عرض سعر ", "", "مشغول"], "day_summary_time": "9:5"})
    assert s.quick_notes == ["طلب عرض سعر", "مشغول"] and s.day_summary_time == "09:05"
    with pytest.raises(Exception):
        container.settings.update({"day_summary_time": "25:00"})


def test_report_list_becomes_the_queue(container):
    asyncio.run(container.workflow.current())
    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        r = tc.put("/api/queue/filter", json={"values": ["لم يتم الرد", "(فارغ)"]}, headers=H).json()
        assert r["lead"]["company_name"] == "مؤسسة الاختبار الأولى"  # starts from the first customer of the new list
        assert {o["value"] for o in r["filter"]["options"] if o["selected"]} == {"", "لم يتم الرد"}
        assert "Qualified" in [s["name"] for s in tc.get("/api/odoo/stages").json()["stages"]]
    with pytest.raises(AgentError):
        asyncio.run(container.workflow.set_status_filter([]))
