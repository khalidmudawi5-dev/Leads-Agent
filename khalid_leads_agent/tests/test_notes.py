from datetime import datetime

from app.services.google_sheets_service import format_note_entry, merge_notes


def test_note_entry_format():
    when = datetime(2026, 9, 28, 15, 30)
    # Default: one line, no name, no date/time.
    assert format_note_entry("العميل مهتم\n\nموعد المتابعة: 2026-10-01  10:00", "خالد", when, "") == \
        "العميل مهتم - موعد المتابعة: 2026-10-01 10:00"
    # A stamp can still be configured; it stays on the same line.
    assert format_note_entry("العميل مهتم...", "خالد", when, "[{date} - {owner}]") == "[28/09/2026 15:30 - خالد] العميل مهتم..."
    # Old multi-line style when single line is turned off.
    entry = format_note_entry("العميل مهتم...", "خالد", when, "[{date} - {owner}]", single_line=False)
    assert entry == "[28/09/2026 15:30 - خالد]\nالعميل مهتم..."


def test_single_line_append_uses_separator():
    assert merge_notes("لم يرد", "مهتم", append=True) == "لم يرد | مهتم"
    assert merge_notes("لم يرد", "مهتم", append=True, single_line=False) == "لم يرد\n\nمهتم"


def test_append_keeps_previous_text():
    old = "[01/09/2026 10:00 - خالد]\nلم يرد"
    merged = merge_notes(old, "[28/09/2026 15:30 - خالد]\nمهتم", append=True)
    assert merged.startswith(old)
    assert merged.endswith("[28/09/2026 15:30 - خالد]\nمهتم")


def test_append_to_empty_and_disabled():
    assert merge_notes("", "entry", append=True) == "entry"
    assert merge_notes("old", "entry", append=False) == "entry"
