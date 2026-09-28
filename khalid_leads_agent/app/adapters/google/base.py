"""Google Sheets client interface. Real and in-memory implementations share it."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CellUpdate:
    """One single-cell write. ``range`` is an absolute A1 cell such as ``'Leads'!C12``."""

    range: str
    value: str
    user_entered: bool = False  # True only for values that Sheets must parse (dates)


class SheetsClient(ABC):
    """Minimal surface used by the agent – values API only, never formatting/clear calls."""

    @abstractmethod
    def spreadsheet_info(self, spreadsheet_id: str) -> dict:
        """Return ``{"title": str, "sheets": [tab names]}``."""

    @abstractmethod
    def get_values(self, spreadsheet_id: str, a1_range: str) -> list[list[str]]:
        """Formatted values of a range (rows may be ragged)."""

    @abstractmethod
    def update_cells(self, spreadsheet_id: str, updates: list[CellUpdate]) -> None:
        """Write single cells through the Values API (batchUpdate)."""

    @abstractmethod
    def dropdown_options(self, spreadsheet_id: str, sheet_name: str, col_index: int, header_row: int) -> list[str]:
        """Values allowed by the column's Data Validation (ONE_OF_LIST / ONE_OF_RANGE); [] if none."""
