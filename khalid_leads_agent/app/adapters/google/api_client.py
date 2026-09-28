"""Real Google Sheets client (google-api-python-client)."""
from __future__ import annotations

import logging

from app.adapters.google.base import CellUpdate, SheetsClient
from app.utils.a1 import col_letter, quote_sheet

log = logging.getLogger(__name__)


class GoogleSheetsApiClient(SheetsClient):
    def __init__(self, credentials) -> None:
        from googleapiclient.discovery import build

        self._svc = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def spreadsheet_info(self, spreadsheet_id: str) -> dict:
        meta = self._svc.spreadsheets().get(
            spreadsheetId=spreadsheet_id, fields="properties.title,sheets.properties.title"
        ).execute()
        return {
            "title": meta.get("properties", {}).get("title", ""),
            "sheets": [s["properties"]["title"] for s in meta.get("sheets", [])],
        }

    def get_values(self, spreadsheet_id: str, a1_range: str) -> list[list[str]]:
        resp = self._svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=a1_range, valueRenderOption="FORMATTED_VALUE",
            majorDimension="ROWS",
        ).execute()
        return [[str(c) for c in row] for row in resp.get("values", [])]

    def update_cells(self, spreadsheet_id: str, updates: list[CellUpdate]) -> None:
        # Values API only: writes the exact cells, never formats/validation/formulas elsewhere.
        for user_entered in (False, True):
            data = [{"range": u.range, "values": [[u.value]]} for u in updates if u.user_entered == user_entered]
            if not data:
                continue
            self._svc.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED" if user_entered else "RAW", "data": data},
            ).execute()

    def dropdown_options(self, spreadsheet_id: str, sheet_name: str, col_index: int, header_row: int) -> list[str]:
        col = col_letter(col_index)
        rng = f"{quote_sheet(sheet_name)}!{col}{header_row + 1}:{col}"  # open-ended: never exceeds the grid
        meta = self._svc.spreadsheets().get(
            spreadsheetId=spreadsheet_id, ranges=[rng], includeGridData=True,
            fields="sheets.data.rowData.values.dataValidation",
        ).execute()
        options: list[str] = []
        ranges: list[str] = []
        for sheet in meta.get("sheets", []):
            for data in sheet.get("data", []):
                for row in data.get("rowData", []) or []:
                    for cell in row.get("values", []) or []:
                        cond = (cell.get("dataValidation") or {}).get("condition") or {}
                        values = [v.get("userEnteredValue", "") for v in cond.get("values", [])]
                        if cond.get("type") == "ONE_OF_LIST":
                            for v in values:
                                if v and v not in options:
                                    options.append(v)
                        elif cond.get("type") == "ONE_OF_RANGE" and values:
                            ref = values[0].lstrip("=")
                            if ref not in ranges:
                                ranges.append(ref)
        for ref in ranges[:3]:
            try:
                for row in self.get_values(spreadsheet_id, ref):
                    for v in row:
                        if v and v not in options:
                            options.append(v)
            except Exception:  # noqa: BLE001 - options are best-effort
                log.warning("Could not read validation range %s", ref, exc_info=True)
        return options
