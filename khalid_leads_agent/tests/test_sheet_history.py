"""Earlier attempts from the sheet's notes cell."""
from datetime import datetime

from app.config import AppSettings
from app.services.sheet_history import combined_streak, drop_saved, history_view, parse_notes
from tests.test_results import prepare, save

KEYS = AppSettings().no_answer_keywords
NOTES = """01/10/2026 اتصلت ما رد

٠٣/١٠/٢٠٢٦ الجوال مغلق

[05/10/2026 10:15 - سارة]
لم يتم الرد"""


def test_parse_dates_agent_stamps_and_keywords():
    e = parse_notes(NOTES, KEYS)
    assert [x.at for x in e] == [datetime(2026, 10, 1), datetime(2026, 10, 3), datetime(2026, 10, 5, 10, 15)]
    assert [x.no_answer for x in e] == [True, True, True] and [x.by_agent for x in e] == [False, False, True]
    assert history_view(e) == {"entries": 3, "no_answer": 3, "last_at": "05/10/2026"}
    other = parse_notes("2026-09-20 مهتم ويريد عرض سعر\n\nملاحظة بدون تاريخ: لا يرد", KEYS)
    assert other[0].at == datetime(2026, 9, 20) and not other[0].no_answer
    assert other[1].at is None and other[1].no_answer


def test_streak_stops_at_an_answer_and_merges_with_saved_results():
    e = parse_notes("01/10/2026 لم يرد\n\n02/10/2026 تم التواصل، مهتم\n\n03/10/2026 لم يرد", KEYS)
    assert combined_streak(e, []) == 1
    assert combined_streak(e, [(datetime(2026, 10, 4, 9), "NO_ANSWER")]) == 2
    assert combined_streak(e, [(datetime(2026, 10, 4, 9), "INTERESTED")]) == 0


def test_entries_saved_on_this_pc_are_not_counted_twice():
    e = parse_notes(NOTES, KEYS)
    kept = drop_saved(e, [datetime(2026, 10, 5, 10, 16)])
    assert len(kept) == 2 and not any(x.by_agent for x in kept)


def _with_notes(container, sheet, notes):
    sheet.sheets["Leads"][1][9] = notes
    return prepare(container)


def test_lead_card_counts_old_sheet_attempts(container, sheet):
    container.settings.update({"no_answer_max_attempts": 3, "duplicate_window_seconds": 0})
    lead = _with_notes(container, sheet, "01/10/2026 ما رد\n\n02/10/2026 لا يرد")
    o = container.workflow.lead_view(lead["fingerprint"])["outcome"]
    assert o["no_answer_streak"] == 2 and not o["attempts_reached"]
    assert o["sheet_history"] == {"entries": 2, "no_answer": 2, "last_at": "02/10/2026"}
    save(container, idempotency_key="hist-na-001", fingerprint=lead["fingerprint"], result_code="NO_ANSWER")
    o = container.workflow.lead_view(lead["fingerprint"])["outcome"]
    assert o["no_answer_streak"] == 3 and o["attempts_reached"]  # 2 from the sheet + 1 saved now


def test_sheet_history_can_be_turned_off(container, sheet):
    container.settings.update({"sheet_history_enabled": False})
    lead = _with_notes(container, sheet, "01/10/2026 ما رد\n\n02/10/2026 لا يرد")
    assert container.workflow.lead_view(lead["fingerprint"])["outcome"] is None
