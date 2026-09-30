"""Request bodies for the JSON API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ResultIn(BaseModel):
    """A call result coming from the result panel.

    ``input_channel`` is "form" in V1. V2 TODO: a "voice" channel will fill the
    same model (see ``call_result_service`` module docstring).
    """

    idempotency_key: str = Field(min_length=8, max_length=80)
    fingerprint: str | None = None
    odoo_lead_id: int | None = None
    result_code: str
    note: str = ""
    source_value: str = ""
    save_source_mapping: bool = False
    source_odoo_value: str = ""
    not_subscribed_reason: str = ""
    trial_registered: str = ""  # value for «هل تم التسجيل بالنسخة التجريبية» ("" = no change)
    subscription_expiry: str = ""
    followup_date: str = ""
    followup_time: str = ""
    followup_note: str = ""
    update_sheet: bool = True
    add_odoo_note: bool = True
    call_started_at: datetime | None = None
    call_ended_at: datetime | None = None
    input_channel: Literal["form", "voice"] = "form"
    preview_only: bool = False
    manual_company: str = ""
    manual_phone: str = ""


class SkipIn(BaseModel):
    mode: Literal["10m", "30m", "today", "session"] = "session"
    reason: str = ""


class SessionStartIn(BaseModel):
    resume: bool = True


class SearchIn(BaseModel):
    query: str = ""


class CreateLeadIn(BaseModel):
    company: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=40)
    contact_name: str = Field(default="", max_length=120)
    source: str | None = Field(default=None, max_length=200)  # sheet source value; None = the sheet's own
    force: bool = False


class SelectCandidateIn(BaseModel):
    odoo_id: int | None = None
    ui_index: int | None = None
    ui_query: str = ""


class ManualOpenIn(BaseModel):
    odoo_id: int


class SourceMappingIn(BaseModel):
    odoo_value: str
    sheet_value: str


class StatusMappingItem(BaseModel):
    code: str
    label: str = ""
    sheet_value: str = ""
    sort_order: int = 0


class StatusMappingIn(BaseModel):
    items: list[StatusMappingItem]


class StatusFilterIn(BaseModel):
    """Follow-up statuses the queue should look for ("" = empty cell)."""

    values: list[str] = Field(default_factory=list, max_length=100)


class CallIn(BaseModel):
    """Which number to call (auto | phone | mobile | sheet) and whether to skip the phone check."""

    target: Literal["auto", "phone", "mobile", "sheet"] = "auto"
    force: bool = False
    odoo_id: int | None = None
    # The page dials the returned tel: itself (agent opened from a phone): nothing is launched on the PC.
    client_dial: bool = False
