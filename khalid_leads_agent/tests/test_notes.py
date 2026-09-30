from datetime import datetime

from app.services.google_sheets_service import format_note_entry, merge_notes


def test_note_entry_format():
    entry = format_note_entry("العميل مهتم...", "خالد", datetime(2026, 9, 28, 15, 30), "[{date} - {owner}]")
    assert entry == "[28/09/2026 15:30 - خالد]\nالعميل مهتم..."


def test_append_keeps_previous_text():
    old = "[01/09/2026 10:00 - خالد]\nلم يرد"
    merged = merge_notes(old, "[28/09/2026 15:30 - خالد]\nمهتم", append=True)
    assert merged.startswith(old)
    assert merged.endswith("[28/09/2026 15:30 - خالد]\nمهتم")


def test_append_to_empty_and_disabled():
    assert merge_notes("", "entry", append=True) == "entry"
    assert merge_notes("old", "entry", append=False) == "entry"
