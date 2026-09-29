"""Odoo adapter interface.

Business logic (matching, result saving) only talks to :class:`OdooAdapter`.
V1 ships :class:`~app.adapters.odoo.browser_adapter.BrowserOdooAdapter`
(Playwright on the user's own logged-in browser profile). A future
JSON-RPC/API adapter can implement the same interface without touching
services (see :mod:`app.adapters.odoo.api_adapter`).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OdooLead:
    id: int | None
    name: str = ""
    company_name: str = ""
    contact_name: str = ""
    phone: str = ""
    mobile: str = ""
    email: str = ""
    salesperson: str = ""
    stage: str = ""
    source: str = ""
    medium: str = ""
    campaign: str = ""
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""
    service_type: str = ""
    lead_type: str = ""
    active: bool = True
    latest_notes: list[str] = field(default_factory=list)
    # Full chatter history, newest first. Each item: id, date (UTC "YYYY-MM-DD HH:MM:SS"), author,
    # kind (note | message | email | tracking | system), subtype, body (plain text) and tracking
    # ([{field, old, new}]).
    chatter: list[dict[str, Any]] = field(default_factory=list)
    # Planned activities: id, date_deadline, summary, type, user, note.
    activities: list[dict[str, Any]] = field(default_factory=list)
    write_date: str = ""
    url: str = ""
    ui_index: int | None = None  # only for UI-search fallback candidates without id
    ui_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OdooLead:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class LoginStatus:
    logged_in: bool
    browser_open: bool = False
    user_name: str = ""
    url: str = ""
    message: str = ""


@dataclass
class ActionOutcome:
    success: bool
    method: str = ""  # ui | rpc | none | skipped
    message: str = ""
    screenshot: str = ""
    already_done: bool = False


class OdooRpcUnavailable(Exception):
    """The in-browser JSON-RPC endpoint cannot be used (fall back to UI)."""


class OdooRpcError(Exception):
    """Odoo answered with an error (access rights, bad field...)."""


class OdooAdapter(ABC):
    """Operations the agent needs from Odoo. All methods are async."""

    @abstractmethod
    async def login_status(self) -> LoginStatus: ...

    @abstractmethod
    async def open_login(self) -> None:
        """Show the Odoo login page so the user can sign in manually."""

    @abstractmethod
    async def open_url(self, url: str) -> None: ...

    @abstractmethod
    async def search_by_phone(self, phone_norm: str) -> list[OdooLead]:
        """Leads whose phone/mobile may match (caller re-checks with normalize_phone)."""

    @abstractmethod
    async def search_by_name(self, text: str) -> list[OdooLead]:
        """Leads whose company/lead/contact name contains ``text``."""

    @abstractmethod
    async def get_lead(self, lead_id: int) -> OdooLead: ...

    @abstractmethod
    async def open_lead(self, lead: OdooLead) -> OdooLead:
        """Open the lead in the visible browser tab and return the data read from it."""

    @abstractmethod
    async def click_call(self, lead_id: int, phone_field: str, phone: str) -> ActionOutcome:
        """Click Odoo's own call link for ``phone``/``mobile`` on the open lead."""

    @abstractmethod
    async def post_log_note(self, lead_id: int, body: str, ref: str) -> ActionOutcome:
        """Add an internal *Log note* (never "Send message"). Must be idempotent on ``ref``."""

    @abstractmethod
    async def schedule_activity(self, lead_id: int, date_deadline: str, summary: str, note: str) -> ActionOutcome: ...

    @abstractmethod
    async def diagnostics(self) -> dict[str, Any]: ...

    @abstractmethod
    async def capture_screenshot(self, name: str) -> str: ...

    @abstractmethod
    async def capture_dom(self, name: str) -> str: ...

    async def lead_signature(self, lead_id: int) -> str | None:
        """Cheap fingerprint of the lead's current state in Odoo (fields + chatter + activities).

        Used by live sync: when it changes, the agent re-reads the lead. ``None`` means
        "cannot tell right now" (e.g. browser not started) and never triggers a refresh.
        """
        return None

    async def close(self) -> None:  # pragma: no cover - optional
        return None
