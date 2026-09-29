"""Safe row update + owner validation (CRITICAL requirements)."""
import pytest

from app.errors import AgentError, OwnerChanged, RowNotFound
from app.services.google_sheets_service import LeadRef
from tests.conftest import sample_rows


def ref_for(container, company):
    snap = container.sheets.load()
    lead = next(lead for lead in snap.leads if lead.company_name == company)
    return lead, LeadRef(lead.fingerprint, lead.sheet_row, lead.company_name, lead.phone_norm)


def test_columns_resolved_by_header_text_not_letter(container):
    snap = container.sheets.load()
    assert snap.columns["owner"] == 1 and snap.columns["company_name"] == 2 and snap.columns["phone"] == 4
    owners = {lead.company_name for lead in container.sheets.owner_leads(snap)}
    assert "شركة سارة" not in owners and "شركة الأمل" in owners  # " خالد " with spaces is still خالد


def test_only_changed_cells_are_written(container, sheet):
    before = [list(r) for r in sheet.sheets["Leads"]]
    lead, ref = ref_for(container, "مؤسسة الاختبار الأولى")
    plan = container.sheets.plan_update(ref, {"followup_status": "مهتم", "source": "Meta || Leads"}, "[x - خالد]\nمهتم")
    assert container.sheets.apply(plan, dry_run=False, action_id="a1") == "success"
    assert len(sheet.write_calls) == 1
    cells = sorted(u.range for u in sheet.write_calls[0])
    assert cells == ["'Leads'!D2", "'Leads'!F2", "'Leads'!J2"]
    after = sheet.sheets["Leads"]
    for r, row in enumerate(before):
        for c, value in enumerate(row):
            if (r, c) not in {(1, 3), (1, 5), (1, 9)}:
                assert after[r][c] == value, f"cell {r},{c} changed"
    assert after[1][10] == "=A2*2"  # formula untouched


def test_row_moved_is_found_by_company_and_phone(container, sheet):
    lead, ref = ref_for(container, "مكتب التقنية")
    rows = sheet.sheets["Leads"]
    rows.insert(1, ["0", "سارة", "صف جديد أضيف فوق", "", "0500000000", "", "", "", "", "", ""])
    plan = container.sheets.plan_update(ref, {"followup_status": "مهتم"}, "")
    assert plan.lead.sheet_row == ref.sheet_row + 1
    container.sheets.apply(plan, dry_run=False)
    assert rows[plan.lead.sheet_row - 1][3] == "مهتم"
    # the row that now sits at the old row number belongs to another lead and is untouched
    assert rows[ref.sheet_row - 1][2] == "مصنع مكتمل" and rows[ref.sheet_row - 1][3] == "مهتم"
    assert len(sheet.write_calls[0]) == 1


def test_owner_changed_blocks_update(container, sheet):
    lead, ref = ref_for(container, "مؤسسة الاختبار الأولى")
    sheet.sheets["Leads"][1][1] = "سارة"  # reassigned by the team
    with pytest.raises(OwnerChanged) as exc:
        container.sheets.plan_update(ref, {"followup_status": "مهتم"}, "")
    assert "تم تحويل العميل إلى موظف آخر" in exc.value.message_ar
    assert sheet.write_calls == []


def test_owner_changed_blocks_update_even_after_row_moves(container, sheet):
    lead, ref = ref_for(container, "مكتب التقنية")
    rows = sheet.sheets["Leads"]
    moved = rows.pop(5)
    moved[1] = "محمد"
    rows.insert(2, moved)
    with pytest.raises(OwnerChanged):
        container.sheets.plan_update(ref, {"followup_status": "مهتم"}, "")


def test_row_deleted_or_ambiguous_blocks(container, sheet):
    lead, ref = ref_for(container, "مكتب التقنية")
    rows = sheet.sheets["Leads"]
    original = list(rows[5])
    rows[5] = ["5", "خالد", "مكتب مختلف", "", "0509999999", "", "", "", "", "", ""]
    rows.append(list(original))
    rows.append(list(original))  # the same lead now exists twice for Khalid
    with pytest.raises(RowNotFound) as exc:
        container.sheets.plan_update(ref, {"followup_status": "مهتم"}, "")  # moved (hint wrong) + 2 matches
    assert "أكثر من صف" in exc.value.message_ar
    rows.pop()
    rows.pop()
    with pytest.raises(RowNotFound):
        container.sheets.plan_update(ref, {"followup_status": "مهتم"}, "")
    assert sheet.write_calls == []


def test_dry_run_never_writes_but_logs(container, sheet):
    lead, ref = ref_for(container, "مؤسسة الاختبار الأولى")
    plan = container.sheets.plan_update(ref, {"followup_status": "مهتم"}, "")
    assert container.sheets.apply(plan, dry_run=True, action_id="dry1") == "dry_run"
    assert sheet.write_calls == []
    from app.repositories.log_repo import LogRepository
    with container.db.session() as s:
        logs = LogRepository(s).syncs_for("dry1")
        audits = LogRepository(s).audits()
    assert logs[0].status == "dry_run" and logs[0].old_value == "" and logs[0].new_value == "مهتم"
    assert audits[0].system == "GOOGLE_SHEETS" and audits[0].dry_run


def test_value_outside_dropdown_is_refused(container, sheet):
    lead, ref = ref_for(container, "مؤسسة الاختبار الأولى")
    with pytest.raises(AgentError) as exc:
        container.sheets.plan_update(ref, {"followup_status": "قيمة غير موجودة"}, "")
    assert exc.value.code == "VALUE_NOT_IN_DROPDOWN"
    assert sheet.write_calls == []


def test_unchanged_values_are_not_rewritten(container, sheet):
    lead, ref = ref_for(container, "شركة الأمل")
    plan = container.sheets.plan_update(ref, {"followup_status": "لم يتم الرد", "source": "تيك توك"}, "")
    assert plan.changes == []
    assert container.sheets.apply(plan, dry_run=False) == "nochange"
    assert sheet.write_calls == []


def test_notes_append_preserves_old_text_in_sheet(container, sheet):
    lead, ref = ref_for(container, "شركة الأمل")
    plan = container.sheets.plan_update(ref, {}, "[28/09/2026 15:30 - خالد]\nالعميل مهتم")
    container.sheets.apply(plan, dry_run=False)
    cell = sheet.sheets["Leads"][3][9]
    assert cell.startswith("[01/09/2026 10:00 - خالد]\nلم يرد")
    assert cell.endswith("[28/09/2026 15:30 - خالد]\nالعميل مهتم")
    # the same entry is not appended twice (retry after partial failure)
    plan2 = container.sheets.plan_update(ref, {}, "[28/09/2026 15:30 - خالد]\nالعميل مهتم")
    assert plan2.changes == []


def test_write_failure_is_logged_and_raised(container, sheet):
    lead, ref = ref_for(container, "مؤسسة الاختبار الأولى")
    plan = container.sheets.plan_update(ref, {"followup_status": "مهتم"}, "")
    sheet.fail_next_write = RuntimeError("network down")
    with pytest.raises(AgentError) as exc:
        container.sheets.apply(plan, dry_run=False, action_id="f1")
    assert exc.value.code == "SHEET_UPDATE_FAILED"
    from app.repositories.log_repo import LogRepository
    with container.db.session() as s:
        assert LogRepository(s).syncs_for("f1")[0].status == "failed"


def test_missing_required_column_is_reported(container, sheet):
    sheet.sheets["Leads"][0][1] = "الموظف"
    with pytest.raises(AgentError) as exc:
        container.sheets.load()
    assert "المسؤول الحالي" in exc.value.message_ar
    container.settings.update({"column_mapping": {"owner": "الموظف"}})
    assert len(container.sheets.owner_leads(container.sheets.load())) == 4


def test_sample_rows_fixture_is_fictional():
    assert all("05" in r[4] or "+966" in r[4] for r in sample_rows()[1:])


def test_tab_name_with_extra_spaces_or_bidi_marks_is_resolved(env, odoo):
    """The browser drops trailing/double spaces from <option> text; Google needs the exact title."""
    from app.adapters.google.mock_client import InMemorySheetsClient
    from tests.conftest import VALIDATIONS, make_container, sample_rows

    real = "‏رصد تواجد-عملاء  محتملين 2026 "
    sheet = InMemorySheetsClient({"Other": [["x"]], real: sample_rows()}, validations=VALIDATIONS)
    c = make_container(env, sheet, odoo, sheet_name="رصد تواجد-عملاء محتملين 2026")
    snap = c.sheets.load()
    assert len(c.sheets.owner_leads(snap)) == 4
    lead = next(lead for lead in snap.leads if lead.company_name == "مؤسسة الاختبار الأولى")
    plan = c.sheets.plan_update(LeadRef(lead.fingerprint, lead.sheet_row, lead.company_name, lead.phone_norm),
                                {"followup_status": "مهتم"}, "")
    c.sheets.apply(plan, dry_run=False)
    assert sheet.sheets[real][1][3] == "مهتم" and sheet.sheets["Other"] == [["x"]]
    assert c.sheets.test_connection()["owner_rows"] == 4


def test_unknown_tab_lists_existing_tabs(container):
    container.settings.update({"sheet_name": "غير موجود"})
    container.sheets.reset_client()
    with pytest.raises(AgentError) as exc:
        container.sheets.load()
    assert exc.value.code == "SHEET_TAB_NOT_FOUND" and "Leads" in exc.value.message_ar


def test_rows_inserted_above_header_between_read_and_write(container, sheet):
    """A teammate inserts rows above the header: the header is found again and the right cell is written."""
    lead, ref = ref_for(container, "مكتب التقنية")
    rows = sheet.sheets["Leads"]
    rows.insert(0, ["ملاحظة للفريق: لا تعدلوا العناوين"])
    rows.insert(0, [""])
    plan = container.sheets.plan_update(ref, {"followup_status": "مهتم"}, "")
    assert container.sheets.header_row_used == 3 and plan.lead.sheet_row == ref.sheet_row + 2
    container.sheets.apply(plan, dry_run=False)
    assert rows[plan.lead.sheet_row - 1][2] == "مكتب التقنية" and rows[plan.lead.sheet_row - 1][3] == "مهتم"
    assert [u.range for u in sheet.write_calls[0]] == [f"'Leads'!D{ref.sheet_row + 2}"]


def test_header_with_invisible_marks_and_letter_variants(container, sheet):
    header = sheet.sheets["Leads"][0]
    header[2] = "‏اسم المنشاه "   # RTL mark + ا/أ and ه/ة variants + trailing space
    header[1] = "المسؤول  الحالي‎"
    snap = container.sheets.load()
    assert snap.columns["company_name"] == 2 and snap.columns["owner"] == 1


def test_missing_column_error_lists_found_headers(container, sheet):
    sheet.sheets["Leads"][0][2] = "العميل"
    with pytest.raises(AgentError) as exc:
        container.sheets.load()
    msg = exc.value.message_ar
    assert "اسم المنشأة" in msg and "«العميل»" in msg and "«رقم الجوال»" in msg
