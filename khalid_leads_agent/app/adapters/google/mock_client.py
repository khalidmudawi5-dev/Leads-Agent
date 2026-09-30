"""In-memory Sheets client used by tests and development (USE_MOCKS=true).

It mimics the Values API semantics: a write only touches the addressed cell and
records every call so tests can assert that nothing else was modified.
"""
from __future__ import annotations

import copy
import re

from app.adapters.google.base import CellUpdate, SheetsClient

_CELL_RE = re.compile(r"^'?(?P<sheet>(?:[^']|'')+?)'?!(?P<col>[A-Z]+)(?P<row>\d+)$")


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


class InMemorySheetsClient(SheetsClient):
    def __init__(self, sheets: dict[str, list[list[str]]] | None = None, title: str = "Mock Spreadsheet",
                 validations: dict[tuple[str, int], list[str]] | None = None) -> None:
        self.sheets: dict[str, list[list[str]]] = copy.deepcopy(sheets or {})
        self.title = title
        self.validations = validations or {}
        self.write_calls: list[list[CellUpdate]] = []
        self.forbidden_calls: list[str] = []  # would record clear/format calls (never used)
        self.fail_next_write: Exception | None = None

    def spreadsheet_info(self, spreadsheet_id: str) -> dict:
        return {"title": self.title, "sheets": list(self.sheets)}

    def get_values(self, spreadsheet_id: str, a1_range: str) -> list[list[str]]:
        name = a1_range.split("!")[0].strip("'").replace("''", "'")
        rows = self.sheets.get(name)
        if rows is None:
            raise KeyError(f"Unable to parse range: {a1_range}")
        m = re.search(r"![A-Z]+\d*:([A-Z]+)", a1_range)
        width = max((len(r) for r in rows), default=0)
        if m and _col_index(m.group(1)) >= width:  # mimic the real API grid check
            raise ValueError(f"Range ({a1_range}) exceeds grid limits. Max columns: {width}")
        out = [list(map(str, r)) for r in copy.deepcopy(rows)]
        for r in out:  # the API trims trailing empty cells
            while r and r[-1] == "":
                r.pop()
        while out and not out[-1]:
            out.pop()
        return out

    def update_cells(self, spreadsheet_id: str, updates: list[CellUpdate]) -> None:
        if self.fail_next_write:
            exc, self.fail_next_write = self.fail_next_write, None
            raise exc
        self.write_calls.append(list(updates))
        for u in updates:
            m = _CELL_RE.match(u.range)
            if not m:
                raise ValueError(f"not a single cell range: {u.range}")
            sheet = m.group("sheet").replace("''", "'")
            row_i, col_i = int(m.group("row")) - 1, _col_index(m.group("col"))
            rows = self.sheets[sheet]
            while len(rows) <= row_i:
                rows.append([])
            while len(rows[row_i]) <= col_i:
                rows[row_i].append("")
            rows[row_i][col_i] = u.value

    def dropdown_options(self, spreadsheet_id: str, sheet_name: str, col_index: int, header_row: int) -> list[str]:
        return list(self.validations.get((sheet_name, col_index), []))
