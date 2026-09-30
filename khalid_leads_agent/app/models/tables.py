"""SQLite tables for the agent."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.utils.timeutils import utcnow


class SettingEntry(Base, TimestampMixin):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)


class LeadSession(Base, TimestampMixin):
    """A working session of the owner (resumable after restart)."""

    __tablename__ = "lead_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | closed
    current_fingerprint: Mapped[str | None] = mapped_column(String(40), nullable=True)
    current_sheet_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_fingerprints: Mapped[list] = mapped_column(JSON, default=list)
    skipped_fingerprints: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LeadCache(Base, TimestampMixin):
    """Last known snapshot of a sheet lead + its Odoo match. Row number is for performance only."""

    __tablename__ = "lead_cache"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    sheet_row: Mapped[int] = mapped_column(Integer)
    company_name: Mapped[str] = mapped_column(String(300), default="")
    phone_raw: Mapped[str] = mapped_column(String(100), default="")
    phone_norm: Mapped[str] = mapped_column(String(30), default="", index=True)
    owner: Mapped[str] = mapped_column(String(100), default="")
    followup_status: Mapped[str] = mapped_column(String(200), default="")
    sheet_source: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    row_values: Mapped[dict] = mapped_column(JSON, default=dict)
    odoo_lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    odoo_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    match_status: Mapped[str] = mapped_column(String(20), default="unknown")  # unknown|matched|multiple|not_found|error
    match_candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    match_strategy: Mapped[str] = mapped_column(String(30), default="")  # phone | company_partial | ui_search ...
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CallResult(Base, TimestampMixin):
    __tablename__ = "call_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    sheet_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    company_name: Mapped[str] = mapped_column(String(300), default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    phone_norm: Mapped[str] = mapped_column(String(30), default="", index=True)
    odoo_lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_code: Mapped[str] = mapped_column(String(40), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    source_value: Mapped[str] = mapped_column(String(200), default="")
    not_subscribed_reason: Mapped[str] = mapped_column(String(300), default="")
    subscription_expiry: Mapped[str] = mapped_column(String(20), default="")
    followup_at: Mapped[str] = mapped_column(String(30), default="")
    followup_note: Mapped[str] = mapped_column(Text, default="")
    call_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    update_sheet: Mapped[bool] = mapped_column(Boolean, default=True)
    add_odoo_note: Mapped[bool] = mapped_column(Boolean, default=True)
    odoo_note_status: Mapped[str] = mapped_column(String(20), default="pending")  # success|failed|skipped|dry_run|pending
    odoo_activity_status: Mapped[str] = mapped_column(String(20), default="skipped")
    sheet_status: Mapped[str] = mapped_column(String(20), default="pending")
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing|done|partial|failed
    errors: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    preview: Mapped[dict] = mapped_column(JSON, default=dict)


class OutreachMessage(Base, TimestampMixin):
    """A WhatsApp message opened from the agent (the user sends it from WhatsApp)."""

    __tablename__ = "outreach_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    company_name: Mapped[str] = mapped_column(String(300), default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    odoo_lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    template: Mapped[str] = mapped_column(String(100), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    odoo_status: Mapped[str] = mapped_column(String(20), default="skipped")
    sheet_status: Mapped[str] = mapped_column(String(20), default="skipped")


class SyncLog(Base, TimestampMixin):
    """Per-cell Google Sheet change log (local backup of old values)."""

    __tablename__ = "sync_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_id: Mapped[str] = mapped_column(String(40), index=True)
    sheet_row: Mapped[int] = mapped_column(Integer)
    company_name: Mapped[str] = mapped_column(String(300), default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    column: Mapped[str] = mapped_column(String(200))
    cell: Mapped[str] = mapped_column(String(50), default="")
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20))  # success|failed|dry_run|blocked


class AuditLog(Base, TimestampMixin):
    """Every external change attempt (GOOGLE_SHEETS / ODOO)."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_id: Mapped[str] = mapped_column(String(40), index=True)
    system: Mapped[str] = mapped_column(String(20), index=True)
    action: Mapped[str] = mapped_column(String(50))
    record: Mapped[str] = mapped_column(String(300), default="")
    before: Mapped[Any] = mapped_column(JSON, nullable=True)
    after: Mapped[Any] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")


class ErrorLog(Base, TimestampMixin):
    __tablename__ = "error_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), index=True)
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    technical: Mapped[str] = mapped_column(Text, default="")
    screenshot: Mapped[str] = mapped_column(String(300), default="")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class SourceMapping(Base, TimestampMixin):
    __tablename__ = "source_mappings"
    __table_args__ = (UniqueConstraint("odoo_key", name="uq_source_odoo_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    odoo_value: Mapped[str] = mapped_column(String(300))
    odoo_key: Mapped[str] = mapped_column(String(300))  # normalized odoo_value
    sheet_value: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class StatusMapping(Base, TimestampMixin):
    __tablename__ = "status_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    label_ar: Mapped[str] = mapped_column(String(100))
    sheet_value: Mapped[str] = mapped_column(String(300), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SkippedLead(Base, TimestampMixin):
    __tablename__ = "skipped_leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(40), index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    company_name: Mapped[str] = mapped_column(String(300), default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    sheet_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(String(20))  # 10m|30m|today|session
    until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(String(300), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
