"""Placeholder for a future server-side Odoo API adapter (JSON-RPC / JSON-2).

V1 deliberately uses the user's browser session (no stored Odoo password).
To add API access later:

1. Store an API key (not a password) outside SQLite, e.g. Windows Credential Manager.
2. Implement every method of :class:`OdooAdapter` with ``/json/2`` or ``/jsonrpc`` calls.
3. Select it in ``app/container.py`` – services stay unchanged.
"""
from __future__ import annotations

from typing import Any

from app.adapters.odoo.base import ActionOutcome, LoginStatus, OdooAdapter, OdooLead


class FutureApiOdooAdapter(OdooAdapter):  # pragma: no cover - intentionally not implemented in V1
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url, self.api_key = base_url, api_key

    def _nyi(self):
        raise NotImplementedError("FutureApiOdooAdapter is planned for V2")

    async def login_status(self) -> LoginStatus: self._nyi()
    async def open_login(self) -> None: self._nyi()
    async def open_url(self, url: str) -> None: self._nyi()
    async def search_by_phone(self, phone_norm: str) -> list[OdooLead]: self._nyi()
    async def search_by_name(self, text: str) -> list[OdooLead]: self._nyi()
    async def get_lead(self, lead_id: int) -> OdooLead: self._nyi()
    async def open_lead(self, lead: OdooLead) -> OdooLead: self._nyi()
    async def click_call(self, lead_id: int, phone_field: str, phone: str) -> ActionOutcome: self._nyi()
    async def post_log_note(self, lead_id: int, body: str, ref: str) -> ActionOutcome: self._nyi()
    async def schedule_activity(self, lead_id: int, date_deadline: str, summary: str, note: str) -> ActionOutcome: self._nyi()
    async def diagnostics(self) -> dict[str, Any]: self._nyi()
    async def capture_screenshot(self, name: str) -> str: self._nyi()
    async def capture_dom(self, name: str) -> str: self._nyi()
