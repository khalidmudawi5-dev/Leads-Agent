"""WhatsApp messages, today's follow-ups, no-answer retries, duplicates (mock Odoo + in-memory sheet)."""
import asyncio
from datetime import timedelta

from app.models import CallResult
from app.utils.timeutils import localnow, utcnow
from tests.test_results import prepare, save

FIRST = "مؤسسة الاختبار الأولى"


def _age(container, days=0, hours=0):
    """Pretend every saved result was made earlier."""
    with container.db.session() as s:
        for row in s.query(CallResult).all():
            row.created_at = utcnow() - timedelta(days=days, hours=hours)


def _queue_names(container):
    return [lead.company_name for lead in container.queue.queue()]


# ---------------------------------------------------------------- WhatsApp
def test_whatsapp_options_fill_templates_and_numbers(container):
    lead = prepare(container)
    opts = container.whatsapp.options(lead["fingerprint"])
    assert opts["numbers"][0]["tel"] == "+966561234567"
    assert FIRST in opts["templates"][0]["text"] and "خالد" in opts["templates"][0]["text"]
    assert "{" not in opts["templates"][0]["text"]


def test_whatsapp_send_logs_to_odoo_and_sheet(container, sheet, odoo):
    lead = prepare(container)
    res = asyncio.run(container.whatsapp.send(lead["fingerprint"], "0561234567", "السلام عليكم\nمعك خالد", "متابعة"))
    assert res["url"].startswith("https://wa.me/966561234567?text=")
    assert "%D8%A7%D9%84%D8%B3%D9%84%D8%A7%D9%85" in res["url"]  # Arabic text is URL-encoded
    assert res["odoo_status"] == "success" and res["sheet_status"] == "success"
    assert "واتساب" in odoo.notes[0]["body"] and "معك خالد" in odoo.notes[0]["body"]
    assert "واتساب: متابعة" in sheet.sheets["Leads"][1][9]
    assert sheet.sheets["Leads"][1][3] == ""  # the follow-up status is not changed
    assert container.workflow.stats()["whatsapp_today"] == 1


def test_whatsapp_without_logging_and_dry_run(container, sheet, odoo):
    lead = prepare(container)
    res = asyncio.run(container.whatsapp.send(lead["fingerprint"], "0561234567", "مرحبا", log_it=False))
    assert res["odoo_status"] == "skipped" and odoo.notes == [] and sheet.write_calls == []
    container.settings.update({"dry_run": True})
    res = asyncio.run(container.whatsapp.send(lead["fingerprint"], "0561234567", "مرحبا"))
    assert res["dry_run"] and res["odoo_status"] == "dry_run" and odoo.notes == [] and sheet.write_calls == []


def test_whatsapp_rejects_bad_number(container):
    lead = prepare(container)
    try:
        asyncio.run(container.whatsapp.send(lead["fingerprint"], "123", "مرحبا"))
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "code", "") == "PHONE_INVALID"
    else:
        raise AssertionError("expected PHONE_INVALID")


# ---------------------------------------------------------------- follow-ups
def test_future_follow_up_waits_then_comes_back_first(container):
    lead = prepare(container)
    tomorrow = (localnow().date() + timedelta(days=1)).isoformat()
    save(container, idempotency_key="key-fu-001", fingerprint=lead["fingerprint"], result_code="FOLLOW_UP",
         followup_date=tomorrow, followup_time="10:00")
    assert FIRST not in _queue_names(container)
    items = container.workflow.followup_items()
    assert items[0]["state"] == "upcoming" and container.workflow.stats()["followups_due"] == 0
    # A day later (same session): due today, back in the queue and first.
    with container.db.session() as s:
        row = s.query(CallResult).one()
        row.followup_at = f"{localnow().date().isoformat()} 10:00"
        row.created_at = utcnow() - timedelta(days=1)
    assert _queue_names(container)[0] == FIRST
    st = container.workflow.stats()
    assert st["followups_due"] == 1 and st["followups_overdue"] == 0
    assert container.workflow.lead_view(lead["fingerprint"])["outcome"]["followup_state"] == "due"


def test_overdue_follow_up_is_listed_first(container):
    lead = prepare(container)
    save(container, idempotency_key="key-fu-002", fingerprint=lead["fingerprint"], result_code="FOLLOW_UP",
         followup_date=(localnow().date() - timedelta(days=2)).isoformat())
    _age(container, days=3)
    items = container.workflow.followup_items()
    assert items[0]["state"] == "overdue" and container.workflow.stats()["followups_overdue"] == 1
    assert _queue_names(container)[0] == FIRST


# ---------------------------------------------------------------- no answer
def test_no_answer_comes_back_after_retry_hours_and_counts_attempts(container):
    container.settings.update({"no_answer_retry_hours": 4, "no_answer_max_attempts": 2, "duplicate_window_seconds": 0})
    lead = prepare(container)
    fp = lead["fingerprint"]
    save(container, idempotency_key="key-na-001", fingerprint=fp, result_code="NO_ANSWER")
    assert FIRST not in _queue_names(container)  # waits 4 hours
    _age(container, hours=5)
    assert FIRST in _queue_names(container)  # back, even though done earlier in this session
    view = container.workflow.lead_view(fp)["outcome"]
    assert view["no_answer_streak"] == 1 and not view["attempts_reached"]
    save(container, idempotency_key="key-na-002", fingerprint=fp, result_code="NO_ANSWER")
    view = container.workflow.lead_view(fp)["outcome"]
    assert view["no_answer_streak"] == 2 and view["attempts_reached"]
    save(container, idempotency_key="key-na-003", fingerprint=fp, result_code="INTERESTED")
    assert container.workflow.lead_view(fp)["outcome"]["no_answer_streak"] == 0


def test_no_answer_retry_off_keeps_old_behaviour(container):
    container.settings.update({"no_answer_retry_hours": 0})
    lead = prepare(container)
    save(container, idempotency_key="key-na-010", fingerprint=lead["fingerprint"], result_code="NO_ANSWER")
    _age(container, hours=30)
    assert FIRST not in _queue_names(container)  # done for this session


# ---------------------------------------------------------------- duplicates
def test_duplicate_numbers_across_owners(container, sheet):
    sheet.sheets["Leads"].append(["6", "سارة", "نفس العميل عند سارة", "", "+966 56 123 4567", "", "", "", "", "", ""])
    lead = prepare(container)
    dups = container.workflow.lead_view(lead["fingerprint"])["duplicates"]
    assert dups == [{"row": 7, "company": "نفس العميل عند سارة", "owner": "سارة", "status": ""}]
    groups = container.workflow.duplicate_groups()
    assert [g["company"] for g in groups] == [FIRST] and container.workflow.stats()["duplicates"] == 1


def test_settings_round_trip_for_new_options(container):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        body = {"whatsapp_templates": [{"name": "ترحيب", "text": "أهلًا {company}"}], "whatsapp_log": False,
                "no_answer_retry_hours": 6, "daily_call_goal": 25, "sheet_poll_minutes": 3}
        assert tc.put("/api/settings", json=body, headers={"X-KLA": "1"}).status_code == 200
        s = tc.get("/api/settings").json()["settings"]
        assert s["whatsapp_templates"] == [{"name": "ترحيب", "text": "أهلًا {company}"}]
        assert s["daily_call_goal"] == 25 and s["no_answer_retry_hours"] == 6 and not s["whatsapp_log"]


def test_background_check_announces_new_customers(container, sheet):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        assert tc.get("/api/queue/check").json() == {"new": 0, "checked": False}  # nothing loaded yet
        tc.post("/api/session/start", json={"resume": True}, headers={"X-KLA": "1"})
        fp = tc.get("/api/lead/current").json()["lead"]["fingerprint"]
        assert tc.get("/api/queue/check").json()["new"] == 0
        sheet.sheets["Leads"].append(["6", "خالد", "عميل وصل الآن", "", "0567777777", "", "", "", "", "", ""])
        r = tc.get("/api/queue/check").json()
        assert r["new"] == 1 and r["names"] == ["عميل وصل الآن"] and r["current"] == fp
        assert r["stats"]["owner_total"] == 5


def test_whatsapp_moves_to_next_customer(container, sheet, odoo):
    from fastapi.testclient import TestClient

    from app.main import create_app
    lead = prepare(container)
    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        res = tc.post(f"/api/lead/{lead['fingerprint']}/whatsapp", headers={"X-KLA": "1"},
                      json={"tel": "0561234567", "text": "تذكير", "template": "تذكير"}).json()
        assert res["url"].startswith("https://wa.me/")
        assert res["next"]["lead"]["fingerprint"] != lead["fingerprint"]  # moved on
        skipped = tc.get("/api/skipped").json()
        assert any("واتساب" in (s["reason"] or "") and s["active"] for s in skipped["items"])
        nxt = res["next"]["lead"]["fingerprint"]
        stay = tc.post(f"/api/lead/{nxt}/whatsapp", headers={"X-KLA": "1"},
                       json={"tel": "0552223333", "text": "مرحبا", "next": False}).json()
        assert "next" not in stay
    assert sheet.sheets["Leads"][1][9] == "واتساب: تذكير"  # one line, no name/time
