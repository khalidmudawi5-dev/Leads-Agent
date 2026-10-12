"""End-of-day summary (mock Odoo + in-memory sheet)."""
import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from app.utils.timeutils import localnow
from tests.test_outreach import _age
from tests.test_results import prepare, save

H = {"X-KLA": "1"}


def _summary(container):
    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        r = tc.get("/api/reports/summary")
        assert r.status_code == 200, r.text
        return r.json()


def test_summary_counts_interested_followups_and_whatsapp_needs(container, sheet):
    container.settings.update({"duplicate_window_seconds": 0, "no_answer_max_attempts": 2, "daily_call_goal": 10})
    lead = prepare(container)
    fp = lead["fingerprint"]
    save(container, idempotency_key="sum-na-1", fingerprint=fp, result_code="NO_ANSWER")
    save(container, idempotency_key="sum-na-2", fingerprint=fp, result_code="NO_ANSWER")
    d = _summary(container)
    assert d["totals"]["calls"] == 2 and d["goal"] == 10 and d["goal_pct"] == 20
    assert [w["company"] for w in d["need_whatsapp"]] == ["مؤسسة الاختبار الأولى"] and d["need_whatsapp"][0]["attempts"] == 2
    # After a WhatsApp message the customer is no longer listed.
    asyncio.run(container.whatsapp.send(fp, "0561234567", "السلام عليكم"))
    assert _summary(container)["need_whatsapp"] == []
    # Interested + a follow-up tomorrow.
    tomorrow = (localnow().date() + timedelta(days=1)).isoformat()
    save(container, idempotency_key="sum-int-1", fingerprint=fp, result_code="INTERESTED", note="يريد عرض سعر",
         schedule_followup=True, followup_date=tomorrow, followup_time="10:30")
    d = _summary(container)
    assert d["hot"][0]["company"] == "مؤسسة الاختبار الأولى" and d["hot"][0]["note"] == "يريد عرض سعر"
    assert [i["company"] for i in d["followups_tomorrow"]] == ["مؤسسة الاختبار الأولى"]
    assert d["first_at"] and d["last_at"]
    text = d["text"]
    assert "ملخص اليوم" in text and "📞 النتائج المسجلة: 3 من هدف 10 (30%)" in text
    assert "يريد عرض سعر" in text and "متابعات بكرة (1)" in text and "10:30" in text


def test_overdue_followup_is_listed_and_yesterday_not_counted(container):
    lead = prepare(container)
    save(container, idempotency_key="sum-fu-old", fingerprint=lead["fingerprint"], result_code="FOLLOW_UP",
         followup_date=(localnow().date() - timedelta(days=1)).isoformat())
    _age(container, days=2)
    d = _summary(container)
    assert d["totals"]["calls"] == 0 and d["first_at"] == ""
    assert [i["state"] for i in d["followups_open"]] == ["overdue"]
    assert "متابعات مفتوحة لم تُنجز (1)" in d["text"]


def test_dry_run_results_are_not_in_the_summary(container):
    container.settings.update({"dry_run": True})
    lead = prepare(container)
    save(container, idempotency_key="sum-dry-1", fingerprint=lead["fingerprint"], result_code="INTERESTED")
    d = _summary(container)
    assert d["totals"]["calls"] == 0 and d["hot"] == []
