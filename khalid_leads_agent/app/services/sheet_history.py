"""Earlier contact attempts read from the sheet's «الملاحظات» cell (deterministic, no AI).

The cell holds entries separated by blank lines: the agent writes ``[dd/mm/yyyy HH:MM - name]`` then the
text; older entries are free text, often starting with a date. Each entry is counted as one earlier
attempt, and as «no answer» when its text contains one of the configured keywords (e.g. «لم يتم الرد»).

Entries this PC's agent already saved as results are skipped (same minute ±2) so nothing counts twice;
entries from a colleague's agent or written by hand are counted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.utils.phone import to_ascii_digits
from app.utils.text import normalize_arabic_letters, normalize_text

_AGENT_STAMP = re.compile(r"^\[(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?\s*-\s*([^\]]*)\]\s*(.*)$", re.S)
_DMY = re.compile(r"^\W{0,3}(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?:\s+(\d{1,2}):(\d{2}))?")
_YMD = re.compile(r"^\W{0,3}(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?")


@dataclass
class SheetEntry:
    at: datetime | None
    text: str
    by_agent: bool
    no_answer: bool


def _norm(value: str) -> str:
    return normalize_arabic_letters(normalize_text(value))


def _date(y: str, m: str, d: str, hh: str | None, mm: str | None) -> datetime | None:
    try:
        return datetime(int(y), int(m), int(d), int(hh or 0), int(mm or 0))
    except ValueError:
        return None


def parse_notes(notes: str, keywords: list[str]) -> list[SheetEntry]:
    keys = [k for k in (_norm(k) for k in keywords) if k]
    entries: list[SheetEntry] = []
    for block in re.split(r"\n\s*\n", notes or ""):
        block = block.strip()
        if not block:
            continue
        head = to_ascii_digits(block)
        at, by_agent, text = None, False, block
        m = _AGENT_STAMP.match(head)
        if m:
            d, mo, y, hh, mi, _owner, rest = m.groups()
            at, by_agent, text = _date(y, mo, d, hh, mi), True, rest.strip()
        elif (m := _DMY.match(head)):
            at = _date(m.group(3), m.group(2), m.group(1), m.group(4), m.group(5))
        elif (m := _YMD.match(head)):
            at = _date(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
        norm = _norm(text)
        entries.append(SheetEntry(at, text, by_agent, any(k in norm for k in keys)))
    return entries


def drop_saved(entries: list[SheetEntry], saved_local: list[datetime]) -> list[SheetEntry]:
    """Remove the agent entries that match a result already saved on this PC (same minute ±2)."""
    window = timedelta(minutes=2)
    return [e for e in entries
            if not (e.by_agent and e.at and any(abs(e.at - t) <= window for t in saved_local))]


def combined_streak(entries: list[SheetEntry], results: list[tuple[datetime, str]]) -> int:
    """«No answer» in a row at the end of the sheet entries + this PC's saved results, by time.

    Undated sheet entries keep their place in the cell (they inherit the previous entry's time).
    """
    timeline: list[tuple[datetime, int, bool]] = []
    last = datetime.min
    for i, e in enumerate(entries):
        last = e.at or last
        timeline.append((last, i, e.no_answer))
    for j, (at, code) in enumerate(results):
        timeline.append((at, len(entries) + j, code == "NO_ANSWER"))
    timeline.sort(key=lambda x: (x[0], x[1]))
    streak = 0
    for _, _, no_answer in reversed(timeline):
        if not no_answer:
            break
        streak += 1
    return streak


def history_view(entries: list[SheetEntry]) -> dict:
    dated = [e.at for e in entries if e.at]
    return {"entries": len(entries), "no_answer": sum(e.no_answer for e in entries),
            "last_at": max(dated).strftime("%d/%m/%Y") if dated else ""}
