"""Result saving: Odoo note + activity + sheet update, dry run, duplicates, manual mode, retry."""
import asyncio

import pytest

from app.errors import AgentError
from app.schemas.api import ResultIn
from tests.conftest import make_container


def prepare(container, company="مؤسسة الاختبار الأولى"):
    wf = container.workflow
    asyncio.run(wf.current())
    lead = next(lead for lead in container.queue.owner_leads if lead.company_name == company)
    payload = asyncio.run(wf.search_odoo(lead.fingerprint))
    return payload["lead"]


def save(container, **kw):
    return asyncio.run(container.results.save(ResultIn(**kw)))


def test_real_save_updates_odoo_and_sheet_then_next(container, sheet, odoo):
    lead = prepare(container)
    assert lead["match_status"] == "matched" and lead["odoo_lead_id"] == 1
    res = save(container, idempotency_key="key-000001", fingerprint=lead["fingerprint"], result_code="INTERESTED",
               note="العميل مهتم بنظام رصد التواجد ويرغب في عرض سعر.", source_value="Meta || Leads")
    assert res["status"] == "done" and not res["dry_run"]
    assert res["message"] == "تم حفظ النتيجة في Odoo وGoogle Sheet"
    assert len(odoo.notes) == 1
    body = odoo.notes[0]["body"]
    assert body.startswith("نتيجة التواصل: مهتم\nالملاحظات: العميل مهتم")
    assert "التاريخ:" in body and "متابعة آلية" not in body and "المصدر" not in body and "KLA-" not in body
    row = sheet.sheets["Leads"][1]
    assert row[3] == "مهتم" and row[5] == "Meta || Leads" and "العميل مهتم" in row[9]
    nxt = asyncio.run(container.workflow.next())
    assert nxt["lead"]["company_name"] == "شركة الأمل"


def test_dry_run_writes_nothing_and_returns_preview(env, sheet, odoo):
    c = make_container(env, sheet, odoo, dry_run=True)
    lead = prepare(c)
    res = save(c, idempotency_key="key-dry-01", fingerprint=lead["fingerprint"], result_code="FOLLOW_UP",
               note="اتصل لاحقًا", followup_date="2026-10-01", followup_time="10:00", source_value="Meta || Leads")
    assert res["dry_run"] and res["odoo_note_status"] == "dry_run" and res["sheet_status"] == "dry_run"
    assert odoo.notes == [] and odoo.activities == [] and sheet.write_calls == []
    cols = {c["column"]: c["new"] for c in res["preview"]["sheet"]}
    assert cols["حالة المتابعة"] == "متابعة" and cols["مصدر العميل"] == "Meta || Leads"
    assert "نتيجة التواصل" in res["preview"]["odoo_note"] and res["preview"]["activity"]["date_deadline"] == "2026-10-01"


def test_dry_run_is_default_on_first_run(env, sheet, odoo):
    from app.container import build_container

    c = build_container(env, sheets_client_factory=lambda _s: sheet, odoo_adapter=odoo)
    assert c.settings.get().dry_run is True


def test_same_idempotency_key_executes_once(container, sheet, odoo):
    lead = prepare(container)
    kw = dict(idempotency_key="key-dup-001", fingerprint=lead["fingerprint"], result_code="NO_ANSWER")
    first = save(container, **kw)
    second = save(container, **kw)
    assert second["duplicate"] and second["result_id"] == first["result_id"]
    assert len(odoo.notes) == 1 and len(sheet.write_calls) == 1


def test_same_lead_same_result_within_window_is_not_repeated(container, sheet, odoo):
    lead = prepare(container)
    save(container, idempotency_key="key-win-001", fingerprint=lead["fingerprint"], result_code="NO_ANSWER")
    res = save(container, idempotency_key="key-win-002", fingerprint=lead["fingerprint"], result_code="NO_ANSWER")
    assert res["duplicate"] and len(odoo.notes) == 1 and len(sheet.write_calls) == 1


def test_parallel_double_click_is_serialized(container, sheet, odoo):
    lead = prepare(container)

    async def both():
        body = dict(idempotency_key="key-par-001", fingerprint=lead["fingerprint"], result_code="INTERESTED")
        return await asyncio.gather(container.results.save(ResultIn(**body)), container.results.save(ResultIn(**body)))

    a, b = asyncio.run(both())
    assert a["result_id"] == b["result_id"] and (a["duplicate"] or b["duplicate"])
    assert len(odoo.notes) == 1 and len(sheet.write_calls) == 1


def test_follow_up_activity_failure_does_not_fail_save(container, sheet, odoo):
    odoo.fail_activity = True
    lead = prepare(container)
    res = save(container, idempotency_key="key-act-001", fingerprint=lead["fingerprint"], result_code="FOLLOW_UP",
               followup_date="2026-10-05", followup_time="11:30", followup_note="إرسال عرض")
    assert res["odoo_activity_status"] == "failed" and res["odoo_note_status"] == "success"
    assert res["sheet_status"] == "success" and res["status"] == "done"
    assert any("Activity creation failed" in w for w in res["warnings"])
    assert sheet.sheets["Leads"][1][3] == "متابعة"


def test_follow_up_activity_created(container, odoo):
    lead = prepare(container)
    save(container, idempotency_key="key-act-002", fingerprint=lead["fingerprint"], result_code="FOLLOW_UP",
         followup_date="2026-10-05", followup_time="11:30")
    assert odoo.activities[0]["date"] == "2026-10-05"


def test_follow_up_requires_date(container):
    lead = prepare(container)
    with pytest.raises(AgentError):
        save(container, idempotency_key="key-act-003", fingerprint=lead["fingerprint"], result_code="FOLLOW_UP")


def test_owner_changed_blocks_sheet_but_keeps_odoo_note(container, sheet, odoo):
    lead = prepare(container)
    sheet.sheets["Leads"][1][1] = "سارة"
    res = save(container, idempotency_key="key-own-001", fingerprint=lead["fingerprint"], result_code="INTERESTED")
    assert res["sheet_status"] == "blocked" and res["status"] == "partial"
    assert any("تم تحويل العميل إلى موظف آخر" in e for e in res["errors"])
    assert sheet.write_calls == [] and len(odoo.notes) == 1


def test_retry_only_failed_steps(container, sheet, odoo):
    lead = prepare(container)
    odoo.fail_note = True
    res = save(container, idempotency_key="key-rty-001", fingerprint=lead["fingerprint"], result_code="INTERESTED",
               note="مهتم")
    assert res["odoo_note_status"] == "failed" and res["sheet_status"] == "success"
    odoo.fail_note = False
    again = asyncio.run(container.results.retry(res["result_id"]))
    assert again["odoo_note_status"] == "success" and again["status"] == "done"
    assert len(odoo.notes) == 1 and len(sheet.write_calls) == 1  # sheet not written twice


def test_retry_after_sheet_failure_does_not_duplicate_notes(container, sheet, odoo):
    lead = prepare(container)
    sheet.fail_next_write = RuntimeError("boom")
    res = save(container, idempotency_key="key-rty-002", fingerprint=lead["fingerprint"], result_code="INTERESTED",
               note="مهتم جدًا")
    assert res["sheet_status"] == "failed"
    again = asyncio.run(container.results.retry(res["result_id"]))
    assert again["sheet_status"] == "success"
    assert sheet.sheets["Leads"][1][9].count("مهتم جدًا") == 1
    assert len(odoo.notes) == 1


def test_manual_mode_never_updates_sheet(container, sheet, odoo):
    asyncio.run(container.workflow.current())
    res = save(container, idempotency_key="key-man-001", fingerprint=None, odoo_lead_id=2, result_code="INTERESTED",
               manual_company="شركة خارج القائمة", manual_phone="0500000000", update_sheet=True)
    assert res["sheet_status"] == "skipped" and len(odoo.notes) == 1 and sheet.write_calls == []
    assert any("وضع البحث اليدوي" in w for w in res["warnings"])


def test_manual_open_links_only_on_unambiguous_phone(container, odoo):
    asyncio.run(container.workflow.current())
    linked = asyncio.run(container.workflow.manual_open(2))  # mobile 0552223333 == شركة الأمل row
    assert linked["linked"] and linked["lead"]["company_name"] == "شركة الأمل"
    from app.adapters.odoo.base import OdooLead
    odoo.leads[9] = OdooLead(id=9, company_name="مؤسسة الاختبار الأولى", phone="0599999999")
    not_linked = asyncio.run(container.workflow.manual_open(9))  # same company name, different phone
    assert not not_linked["linked"]


def test_source_auto_matched_to_identical_sheet_value(container, sheet):
    lead = prepare(container)  # Odoo "Meta / Leads"; sheet dropdown has "Meta || Leads"
    assert lead["source"]["mapped"] and lead["source"]["auto"] and lead["source"]["prefill"] == "Meta || Leads"
    res = save(container, idempotency_key="key-src-000", fingerprint=lead["fingerprint"], result_code="INTERESTED",
               source_value=lead["source"]["prefill"])
    assert res["sheet_status"] == "success"
    assert {c["key"]: c["new"] for c in res["preview"]["sheet"]}["source"] == "Meta || Leads"


def test_auto_source_written_on_match_from_utm_source(container, sheet, odoo):
    container.settings.update({"auto_write_source": True})
    odoo.leads[1].source = "Something else"  # Source is ignored: UTM Source decides
    lead = prepare(container)
    cells = [u for call in sheet.write_calls for u in call]
    assert [(u.range, u.value) for u in cells] == [("'Leads'!F2", "Meta || Leads")]  # one cell only
    assert lead["sheet_source"] == "Meta || Leads"
    again = asyncio.run(container.workflow.search_odoo(lead["fingerprint"]))  # already up to date
    assert len(sheet.write_calls) == 1 and not again["notices"]
    from app.repositories.log_repo import LogRepository
    with container.db.session() as s:
        assert any(a.system == "GOOGLE_SHEETS" for a in LogRepository(s).audits())


def test_auto_source_respects_dry_run_and_mapping(container, sheet, odoo):
    container.settings.update({"auto_write_source": True, "dry_run": True})
    prepare(container)
    assert sheet.write_calls == []  # Dry Run writes nothing
    container.settings.update({"dry_run": False})
    odoo.leads[1].utm_source = "Snapchat"  # not mapped, no identical sheet value → never guessed
    payload = asyncio.run(container.workflow.search_odoo(prepare(container)["fingerprint"]))
    assert sheet.write_calls == [] and not payload["notices"]


def test_auto_source_blocked_when_owner_changed(container, sheet, odoo):
    container.settings.update({"auto_write_source": True})
    wf = container.workflow
    asyncio.run(wf.current())
    lead = next(x for x in container.queue.owner_leads if x.company_name == "مؤسسة الاختبار الأولى")
    sheet.sheets["Leads"][1][1] = "سارة"  # row reassigned after the queue was loaded
    payload = asyncio.run(wf.search_odoo(lead.fingerprint))
    assert sheet.write_calls == [] and not payload["notices"]
    assert any("مصدر العميل" in w for w in payload["warnings"])


def test_source_mapping_saved_from_result(container, odoo):
    odoo.leads[1].utm_source = "Snapchat"  # no identical sheet value
    lead = prepare(container)
    assert lead["source"]["odoo_value"] == "Snapchat" and not lead["source"]["mapped"]
    save(container, idempotency_key="key-src-001", fingerprint=lead["fingerprint"], result_code="INTERESTED",
         source_value="Meta || Leads", save_source_mapping=True, source_odoo_value="Snapchat")
    view = container.workflow.lead_view(lead["fingerprint"])
    assert view["source"]["mapped"] and not view["source"]["auto"] and view["source"]["prefill"] == "Meta || Leads"


def test_status_not_in_dropdown_is_blocked(container, sheet):
    container.mappings.save_statuses([{"code": "SUBSCRIBED", "label": "تم الاشتراك", "sheet_value": "مشترك"}])
    lead = prepare(container)
    res = save(container, idempotency_key="key-val-001", fingerprint=lead["fingerprint"], result_code="SUBSCRIBED",
               subscription_expiry="2027-09-28")
    assert res["sheet_status"] == "failed" and sheet.write_calls == []


def test_preview_only_writes_nothing_even_when_dry_run_off(container, sheet, odoo):
    lead = prepare(container)
    res = save(container, idempotency_key="key-prv-001", fingerprint=lead["fingerprint"], result_code="NO_ANSWER",
               preview_only=True)
    assert res["status"] == "preview" and res["preview"]["sheet"]
    assert sheet.write_calls == [] and odoo.notes == []
    from app.repositories.log_repo import LogRepository
    with container.db.session() as s:
        assert LogRepository(s).audits() == []


def test_trial_registered_written_to_sheet_and_odoo_note(container, sheet, odoo):
    lead = prepare(container)
    assert lead["trial_registered"] == "لا"  # current sheet value is shown in the panel
    res = save(container, idempotency_key="key-trial-01", fingerprint=lead["fingerprint"], result_code="INTERESTED",
               trial_registered="نعم")
    assert res["sheet_status"] == "success"
    assert {c["key"]: c["new"] for c in res["preview"]["sheet"]}["trial_registered"] == "نعم"
    assert sheet.sheets["Leads"][1][6] == "نعم"  # column «هل تم التسجيل بالنسخة التجريبية»
    assert "التسجيل بالنسخة التجريبية: نعم" in odoo.notes[-1]["body"]


def test_trial_registered_empty_means_no_change(container, sheet):
    lead = prepare(container)
    res = save(container, idempotency_key="key-trial-02", fingerprint=lead["fingerprint"], result_code="NO_ANSWER")
    assert "trial_registered" not in {c["key"] for c in res["preview"]["sheet"]}
    assert sheet.sheets["Leads"][1][6] == "لا"



def test_clean_note_is_not_posted_twice_on_retry(container, odoo):
    lead = prepare(container)
    odoo.fail_note = True  # Odoo step fails first → partial
    res = save(container, idempotency_key="key-clean-01", fingerprint=lead["fingerprint"], result_code="NO_ANSWER")
    assert res["odoo_note_status"] == "failed"
    odoo.fail_note = False
    body = res["preview"]["odoo_note"]
    assert "الملاحظات" not in body  # empty value line dropped
    odoo.notes.append({"lead_id": 1, "body": body})  # it was actually posted before the error
    again = asyncio.run(container.results.retry(res["result_id"]))
    assert again["odoo_note_status"] == "existing" or len(odoo.notes) == 1


def test_legacy_note_template_migrated(env, sheet, odoo):
    from app.config import DEFAULT_NOTE_TEMPLATE, LEGACY_NOTE_TEMPLATE
    from app.models import SettingEntry
    c = make_container(env, sheet, odoo, odoo_note_template=LEGACY_NOTE_TEMPLATE)
    with c.db.session() as s:  # simulate a database from before 1.7
        s.query(SettingEntry).filter_by(key="note_template_v17").delete()
    c.settings.seed()
    c.settings.invalidate()
    assert c.settings.get().odoo_note_template == DEFAULT_NOTE_TEMPLATE


def test_any_sheet_dropdown_status_can_be_recorded(container, sheet, odoo):
    lead = prepare(container)
    res = save(container, idempotency_key="key-sheet-st1", fingerprint=lead["fingerprint"],
               result_code="S:بيانات التواصل غير صحيحة", note="الرقم مقفل")
    assert res["status"] == "done" and res["sheet_status"] == "success"
    assert sheet.sheets["Leads"][1][3] == "بيانات التواصل غير صحيحة"
    assert "نتيجة التواصل: بيانات التواصل غير صحيحة" in odoo.notes[-1]["body"]
    from app.services.settings_service import result_label
    assert result_label("S:السعر مرتفع") == "السعر مرتفع" and result_label("INTERESTED") == "مهتم"


def test_sheet_status_outside_dropdown_is_refused(container, sheet):
    lead = prepare(container)
    res = save(container, idempotency_key="key-sheet-st2", fingerprint=lead["fingerprint"], result_code="S:قيمة غير موجودة")
    assert res["sheet_status"] == "failed" and sheet.write_calls == []
