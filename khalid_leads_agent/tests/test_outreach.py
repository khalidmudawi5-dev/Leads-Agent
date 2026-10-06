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


# ------------------------------------------------- follow-up as an action next to any result
def test_followup_action_with_any_sheet_status(container, sheet, odoo):
    lead = prepare(container)
    tomorrow = (localnow().date() + timedelta(days=1)).isoformat()
    res = save(container, idempotency_key="key-fua-001", fingerprint=lead["fingerprint"], result_code="INTERESTED",
               schedule_followup=True, followup_date=tomorrow, followup_time="11:00", followup_note="إرسال العرض")
    assert res["status"] == "done" and res["odoo_activity_status"] == "success"
    assert odoo.activities[0]["date"] == tomorrow
    assert sheet.sheets["Leads"][1][3] == "مهتم"  # the chosen status, not «متابعة»
    item = container.workflow.followup_items()[0]
    assert item["state"] == "upcoming" and item["followup_at"] == f"{tomorrow} 11:00"
    assert FIRST not in _queue_names(container)  # waits for its date


def test_followup_result_without_dropdown_value_keeps_sheet_status(container, sheet, odoo):
    container.mappings.save_statuses([{"code": "FOLLOW_UP", "sheet_value": "قيمة غير موجودة في القائمة"}])
    lead = prepare(container)
    tomorrow = (localnow().date() + timedelta(days=1)).isoformat()
    res = save(container, idempotency_key="key-fua-002", fingerprint=lead["fingerprint"], result_code="FOLLOW_UP",
               followup_date=tomorrow)
    assert res["status"] == "done" and res["odoo_activity_status"] == "success"
    assert sheet.sheets["Leads"][1][3] == ""  # status untouched, no invalid dropdown value written
    assert "متابعة" in sheet.sheets["Leads"][1][9]  # the note still records the follow-up


def test_followup_action_requires_a_date(container):
    lead = prepare(container)
    try:
        save(container, idempotency_key="key-fua-003", fingerprint=lead["fingerprint"], result_code="NO_ANSWER",
             schedule_followup=True)
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "code", "") == "FOLLOWUP_DATE_REQUIRED"
    else:
        raise AssertionError("expected FOLLOWUP_DATE_REQUIRED")


def test_no_answer_with_followup_waits_for_the_followup_date(container):
    container.settings.update({"no_answer_retry_hours": 1})
    lead = prepare(container)
    nxt = (localnow().date() + timedelta(days=3)).isoformat()
    save(container, idempotency_key="key-fua-004", fingerprint=lead["fingerprint"], result_code="NO_ANSWER",
         schedule_followup=True, followup_date=nxt)
    _age(container, hours=5)
    assert FIRST not in _queue_names(container)  # the follow-up date wins over the 1-hour retry


# ------------------------------------------------- WhatsApp attachments (image / PDF)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%test\n"


def _client(container):
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app(container, allowed_hosts=["testserver"]))


def test_attachment_upload_serve_and_validation(container):
    with _client(container) as tc:
        r = tc.post("/api/attachments", files={"file": ("بوستر رصد.png", PNG, "image/png")}, headers={"X-KLA": "1"})
        f = r.json()["file"]
        assert f["kind"] == "image" and f["name"] == "بوستر رصد.png" and f["id"].endswith(".png")
        got = tc.get(f["url"])
        assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
        assert "attachment" in tc.get(f["url"] + "?download=1&name=x").headers["content-disposition"]
        # The real content decides: a renamed text file is refused, and only stored names are served.
        bad = tc.post("/api/attachments", files={"file": ("fake.pdf", b"hello", "application/pdf")}, headers={"X-KLA": "1"})
        assert bad.json()["error"]["code"] == "FILE_TYPE"
        assert tc.get("/api/attachments/..%2Fagent.db").status_code == 404
        pdf = tc.post("/api/attachments", files={"file": ("عرض.pdf", PDF, "application/pdf")}, headers={"X-KLA": "1"}).json()["file"]
        assert pdf["kind"] == "pdf"


def test_template_with_attachment_is_offered_and_logged(container, sheet, odoo):
    lead = prepare(container)
    f = container.whatsapp.attachments.save("poster.png", PNG)
    container.settings.update({"whatsapp_templates": [{"name": "النسخة التجريبية", "text": "أهلًا {company}",
                                                       "file": f["id"], "file_name": "poster.png"}]})
    tpl = container.whatsapp.options(lead["fingerprint"])["templates"][0]
    assert tpl["file"]["id"] == f["id"] and tpl["file"]["kind"] == "image"
    res = asyncio.run(container.whatsapp.send(lead["fingerprint"], "0561234567", "أهلًا", "النسخة التجريبية",
                                              file_id=f["id"], file_name="poster.png"))
    assert res["file"]["name"] == "poster.png" and res["file"]["copied"] is False  # no Windows clipboard here
    assert "مرفق: poster.png" in odoo.notes[0]["body"]
    assert "واتساب: النسخة التجريبية + صورة" in sheet.sheets["Leads"][1][9]


def test_missing_attachment_is_reported(container):
    lead = prepare(container)
    try:
        asyncio.run(container.whatsapp.send(lead["fingerprint"], "0561234567", "أهلًا", file_id="0" * 32 + ".png"))
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "code", "") == "FILE_NOT_FOUND"
    else:
        raise AssertionError("expected FILE_NOT_FOUND")


def test_unused_attachments_are_cleaned_up(container):
    att = container.whatsapp.attachments
    keep = att.save("a.png", PNG)["id"]
    old = att.save("b.pdf", PDF)["id"]
    fresh = att.save("c.pdf", PDF)["id"]
    assert att.cleanup({keep}, min_age_seconds=10**9) == 0  # recent uploads are kept
    import os
    import time
    os.utime(att.path(old), (time.time() - 2 * 86400,) * 2)
    assert att.cleanup({keep}) == 1
    assert att.path(keep) and att.path(fresh) and att.path(old) is None


def test_clipboard_copy_on_windows_passes_the_path_safely(container, monkeypatch):
    import subprocess

    from app.services import attachment_service as mod

    att = container.whatsapp.attachments
    fid = att.save("a'; Remove-Item x; '.png", PNG)["id"]
    seen = {}
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: seen.update(args=args, env=kw["env"]))
    assert att.copy_to_clipboard(fid) is True
    assert seen["args"][0] == "powershell.exe" and "-STA" in seen["args"]
    assert seen["env"]["KLA_CLIP_FILE"].endswith(fid) and fid not in " ".join(seen["args"])
    assert seen["env"]["KLA_CLIP_KIND"] == "image"  # a picture goes on the clipboard as an image, not a file
    pdf = att.save("offer.pdf", PDF)["id"]
    att.copy_to_clipboard(pdf)
    assert seen["env"]["KLA_CLIP_KIND"] == "pdf"
    assert att.copy_to_clipboard("../../agent.db") is False
