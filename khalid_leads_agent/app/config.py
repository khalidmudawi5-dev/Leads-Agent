"""Configuration.

Two layers:

* :class:`EnvSettings` – bootstrap values from ``.env`` (host, port, paths, first-run defaults).
* :class:`AppSettings` – user-editable settings persisted in SQLite (``settings`` table).
  Values missing from the DB fall back to ``.env`` defaults.

Secrets (Google/Odoo passwords) are never stored here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class EnvSettings(BaseSettings):
    """Values read from ``.env`` (UTF-8, BOM tolerated for Windows Notepad)."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8-sig", extra="ignore"
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8765
    agent_owner: str = "خالد"
    odoo_base_url: str = "https://worldofss.odoo.com"
    google_spreadsheet_id: str = ""
    google_sheet_name: str = ""
    google_auth_mode: Literal["oauth", "service_account"] = "oauth"
    dry_run: bool = True
    browser_headless: bool = False
    browser_channel: str = "chromium"
    browser_executable_path: str = ""
    log_level: str = "INFO"
    data_dir: str = ""
    logs_dir: str = ""
    open_browser_on_start: bool = True
    # Open the agent from your phone/other devices over Tailscale (see README_AR). Off by default.
    remote_access: bool = False
    access_pin: str = ""
    # Development only: use in-memory Google sheet + fake Odoo adapter.
    use_mocks: bool = False

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir) if self.data_dir else PROJECT_ROOT / "data"

    @property
    def logs_path(self) -> Path:
        return Path(self.logs_dir) if self.logs_dir else PROJECT_ROOT / "logs"

    @property
    def credentials_path(self) -> Path:
        return self.data_path / "credentials"

    @property
    def db_path(self) -> Path:
        return self.data_path / "agent.db"


DEFAULT_COLUMN_MAPPING: dict[str, str] = {
    "company_name": "اسم المنشأة",
    "phone": "رقم الجوال",
    "owner": "المسؤول الحالي",
    "followup_status": "حالة المتابعة",
    "source": "مصدر العميل",
    "trial_registered": "هل تم التسجيل بالنسخة التجريبية",
    "not_subscribed_reason": "سبب عدم الاشتراك",
    "subscription_expiry": "تاريخ انتهاء الاشتراك",
    "notes": "الملاحظات",
    "lead_date": "",
}
REQUIRED_COLUMNS = ("company_name", "phone", "owner", "followup_status")
COLUMN_LABELS_AR: dict[str, str] = {
    "company_name": "اسم المنشأة",
    "phone": "رقم الجوال",
    "owner": "المسؤول الحالي",
    "followup_status": "حالة المتابعة",
    "source": "مصدر العميل",
    "trial_registered": "التسجيل بالنسخة التجريبية",
    "not_subscribed_reason": "سبب عدم الاشتراك",
    "subscription_expiry": "تاريخ انتهاء الاشتراك",
    "notes": "الملاحظات",
    "lead_date": "تاريخ العميل (اختياري للترتيب)",
}

EMPTY_TOKEN = "(فارغ)"

# Before 1.7 the note carried an agent header, the source and a "KLA-…" reference line.
LEGACY_NOTE_TEMPLATE = (
    "متابعة آلية بواسطة Khalid Leads Agent\n"
    "نتيجة التواصل: {result}\n"
    "الملاحظات: {notes}\n"
    "التاريخ: {date}\n"
    "المصدر: {source}\n"
    "المرجع: {ref}"
)
DEFAULT_NOTE_TEMPLATE = (
    "نتيجة التواصل: {result}\n"
    "الملاحظات: {notes}\n"
    "التاريخ: {date}"
)


class AppSettings(BaseModel):
    """User-editable settings (Settings screen / setup wizard)."""

    # General
    agent_owner: str = "خالد"
    setup_completed: bool = False
    # Google
    google_auth_mode: Literal["oauth", "service_account"] = "oauth"
    spreadsheet_id: str = ""
    sheet_name: str = ""
    header_row: int = Field(default=1, ge=1, le=50)
    column_mapping: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_COLUMN_MAPPING))
    pending_status_values: list[str] = Field(default_factory=lambda: ["", "لم يتم الرد", "متابعة"])
    append_notes: bool = True
    note_stamp_format: str = "[{date} - {owner}]"
    validate_dropdown_values: bool = True
    # Odoo
    odoo_base_url: str = "https://worldofss.odoo.com"
    odoo_crm_url: str = ""
    odoo_lead_url_template: str = "{base}/odoo/crm.lead/{id}"
    odoo_note_template: str = DEFAULT_NOTE_TEMPLATE
    odoo_write_method: Literal["ui_first", "rpc_first"] = "ui_first"
    odoo_activity_type_xmlid: str = "mail.mail_activity_data_todo"
    # Customers missing from Odoo are added from the agent as a Lead (CRM > Leads, like the other
    # customers) or as an Opportunity (CRM > Pipeline).
    odoo_new_record_type: Literal["lead", "opportunity"] = "lead"
    # fast: hand the Odoo number straight to Windows/Phone Link (instant, no browser);
    # odoo_click: open the lead and click Odoo's own Call link; windows_handler: read that link, then Windows.
    call_launch_mode: Literal["fast", "odoo_click", "windows_handler"] = "fast"
    # Block calling a number that fails the phone check (the user can still choose "call anyway").
    call_check_phone: bool = True
    call_fallback_windows_handler: bool = False
    # Automation
    auto_load_next: bool = True
    auto_sync_source: bool = True
    auto_open_odoo_lead: bool = True
    next_lead_delay_seconds: int = Field(default=3, ge=0, le=60)
    dry_run: bool = True
    lead_ordering: Literal["sheet_order", "sheet_reverse", "oldest_first", "newest_first"] = "sheet_order"
    duplicate_window_seconds: int = Field(default=60, ge=0, le=3600)
    # Live sync: poll the open lead in Odoo and refresh the agent when anything changes there.
    live_sync_enabled: bool = True
    live_sync_interval_seconds: int = Field(default=5, ge=2, le=120)
    chatter_history_limit: int = Field(default=40, ge=5, le=200)
    # Advanced
    browser_profile_path: str = ""
    browser_channel: str = "chromium"
    browser_executable_path: str = ""
    browser_headless: bool = False
    navigation_timeout_ms: int = Field(default=30000, ge=3000, le=180000)
    action_timeout_ms: int = Field(default=10000, ge=1000, le=120000)
    retry_attempts: int = Field(default=2, ge=1, le=5)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("odoo_base_url")
    @classmethod
    def _strip_url(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @property
    def crm_url(self) -> str:
        return self.odoo_crm_url.strip() or f"{self.odoo_base_url}/odoo/crm"

    def lead_url(self, lead_id: int) -> str:
        return self.odoo_lead_url_template.format(base=self.odoo_base_url, id=lead_id)

    def pending_values_normalized(self) -> set[str]:
        from app.utils.text import normalize_text

        return {"" if v.strip() == EMPTY_TOKEN else normalize_text(v) for v in self.pending_status_values}

    def missing_basics(self) -> list[str]:
        """Human (Arabic) list of what is still missing for the dashboard to work."""
        missing: list[str] = []
        if not self.agent_owner.strip():
            missing.append("اسم المستخدم")
        if not self.spreadsheet_id.strip():
            missing.append("Spreadsheet ID")
        if not self.sheet_name.strip():
            missing.append("اسم الـTab")
        for key in REQUIRED_COLUMNS:
            if not self.column_mapping.get(key, "").strip():
                missing.append(f"ربط عمود {COLUMN_LABELS_AR[key]}")
        if not self.odoo_base_url:
            missing.append("رابط Odoo")
        return missing


def defaults_from_env(env: EnvSettings) -> AppSettings:
    """First-run defaults: AppSettings seeded from .env values."""
    return AppSettings(
        agent_owner=env.agent_owner,
        google_auth_mode=env.google_auth_mode,
        spreadsheet_id=env.google_spreadsheet_id,
        sheet_name=env.google_sheet_name,
        odoo_base_url=env.odoo_base_url,
        dry_run=env.dry_run,
        browser_headless=env.browser_headless,
        browser_channel=env.browser_channel,
        browser_executable_path=env.browser_executable_path,
        log_level=env.log_level.upper() if env.log_level.upper() in {"DEBUG", "INFO", "WARNING", "ERROR"} else "INFO",
    )
