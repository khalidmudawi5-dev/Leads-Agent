"""A1 notation helpers for Google Sheets."""
from __future__ import annotations


def col_letter(index: int) -> str:
    """0-based column index → letters (0 → A, 25 → Z, 26 → AA)."""
    if index < 0:
        raise ValueError("column index must be >= 0")
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def quote_sheet(name: str) -> str:
    """Quote a tab name for A1 ranges ('It''s' escaping)."""
    return "'" + name.replace("'", "''") + "'"


def cell_ref(sheet: str, row: int, col_index: int) -> str:
    """Absolute single-cell range, e.g. 'Leads'!C12."""
    return f"{quote_sheet(sheet)}!{col_letter(col_index)}{row}"
