"""Wires adapters, repositories and services together (simple dependency injection)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.adapters.google.base import SheetsClient
from app.adapters.odoo.base import OdooAdapter
from app.config import AppSettings, EnvSettings
from app.db import Database
from app.services.call_result_service import ResultService
from app.services.google_auth_service import GoogleAuthService
from app.services.followup_service import FollowupService
from app.services.google_sheets_service import SheetService
from app.services.lead_queue_service import LeadQueueService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.mapping_service import MappingService
from app.services.odoo_service import OdooService
from app.services.session_service import SessionService
from app.services.customer_report_service import CustomerReportService
from app.services.report_service import ReportService
from app.services.settings_service import SettingsService
from app.services.sync_service import SyncService
from app.services.whatsapp_service import WhatsAppService


@dataclass
class AppContainer:
    env: EnvSettings
    db: Database
    settings: SettingsService
    auth: GoogleAuthService
    sheets: SheetService
    odoo: OdooService
    sessions: SessionService
    queue: LeadQueueService
    mappings: MappingService
    sync: SyncService
    results: ResultService
    workflow: LeadWorkflowService
    followups: FollowupService
    whatsapp: WhatsAppService
    reports: ReportService
    customer_report: CustomerReportService


def build_container(
    env: EnvSettings,
    *,
    sheets_client_factory: Callable[[AppSettings], SheetsClient] | None = None,
    odoo_adapter: OdooAdapter | None = None,
    db: Database | None = None,
) -> AppContainer:
    for path in (env.data_path, env.credentials_path, env.logs_path, env.logs_path / "screenshots",
                 env.data_path / "browser-profile"):
        path.mkdir(parents=True, exist_ok=True)
    db = db or Database(env.db_path)
    db.init()
    settings = SettingsService(db, env)
    settings.seed()
    auth = GoogleAuthService(env.credentials_path)

    if sheets_client_factory is None:
        if env.use_mocks:
            from app.adapters.google.demo_data import VALIDATIONS, demo_sheet
            from app.adapters.google.mock_client import InMemorySheetsClient

            mock = InMemorySheetsClient(demo_sheet(), validations=VALIDATIONS)
            sheets_client_factory = lambda _s: mock  # noqa: E731
        else:
            from app.adapters.google.api_client import GoogleSheetsApiClient

            def sheets_client_factory(s: AppSettings) -> SheetsClient:
                return GoogleSheetsApiClient(auth.get_credentials(s.google_auth_mode))

    if odoo_adapter is None:
        if env.use_mocks:
            from app.adapters.odoo.mock_adapter import MockOdooAdapter, demo_odoo_leads

            odoo_adapter = MockOdooAdapter(demo_odoo_leads())
        else:
            from app.adapters.odoo.browser_adapter import BrowserOdooAdapter

            odoo_adapter = BrowserOdooAdapter(
                settings.get, env.data_path / "browser-profile", env.logs_path / "screenshots",
                env.logs_path / "snapshots",
            )

    sheets = SheetService(db, settings, sheets_client_factory)
    odoo = OdooService(odoo_adapter)
    sessions = SessionService(db, settings)
    followups = FollowupService(db, settings)
    queue = LeadQueueService(db, settings, sheets, sessions, followups)
    mappings = MappingService(db, source_options=lambda: sheets.dropdown_options("source"))
    sync = SyncService(db, sheets, odoo)
    results = ResultService(db, settings, mappings, sync, sessions)
    workflow = LeadWorkflowService(db, settings, sheets, queue, sessions, odoo, mappings)
    whatsapp = WhatsAppService(db, settings, sync)
    return AppContainer(env, db, settings, auth, sheets, odoo, sessions, queue, mappings, sync, results, workflow,
                        followups, whatsapp, ReportService(db, mappings),
                        CustomerReportService(db, settings, queue, odoo))
