"""Queue of the owner's pending leads (sheet order by default)."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from app.config import AppSettings
from app.db import Database
from app.repositories.lead_repo import LeadCacheRepository, SkipRepository
from app.services.followup_service import FollowupService
from app.services.google_sheets_service import SheetLead, SheetService
from app.services.session_service import SessionService
from app.services.settings_service import SettingsService
from app.utils.text import normalize_text
from app.utils.timeutils import utcnow

log = logging.getLogger(__name__)

_DATE_PATTERNS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S")


def parse_sheet_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    value = re.sub(r"\s+", " ", value)
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def is_pending(lead: SheetLead, settings: AppSettings) -> bool:
    return normalize_text(lead.followup_status) in settings.pending_values_normalized()


def order_leads(leads: list[SheetLead], ordering: str) -> list[SheetLead]:
    """sheet_order (default, top → bottom), sheet_reverse, oldest_first / newest_first (lead_date column)."""
    if ordering == "sheet_reverse":
        return sorted(leads, key=lambda lead: lead.sheet_row, reverse=True)
    if ordering in ("oldest_first", "newest_first"):
        newest = ordering == "newest_first"
        dated = [(parse_sheet_date(lead.lead_date), lead) for lead in leads]
        with_date = [t for t in dated if t[0] is not None]
        without = [lead for d, lead in dated if d is None]
        with_date.sort(key=lambda t: (t[0], t[1].sheet_row), reverse=newest)
        # rows without a date keep sheet order (top→bottom for oldest, bottom→top for newest)
        without.sort(key=lambda lead: lead.sheet_row, reverse=newest)
        return [lead for _, lead in with_date] + without
    return sorted(leads, key=lambda lead: lead.sheet_row)


class LeadQueueService:
    def __init__(self, db: Database, settings: SettingsService, sheets: SheetService, sessions: SessionService,
                 followups: FollowupService | None = None) -> None:
        self.db = db
        self.settings = settings
        self.sheets = sheets
        self.sessions = sessions
        self.followups = followups
        self.owner_leads: list[SheetLead] = []
        self.all_leads: list[SheetLead] = []  # every owner's rows (duplicate detection)
        self.loaded = False

    def refresh(self) -> list[SheetLead]:
        """Re-read the sheet and cache the owner's rows locally."""
        snap = self.sheets.load()
        leads = self.sheets.owner_leads(snap)
        self.all_leads = list(snap.leads)
        with self.db.session() as s:
            repo = LeadCacheRepository(s)
            for lead in leads:
                repo.upsert(
                    lead.fingerprint, sheet_row=lead.sheet_row, company_name=lead.company_name,
                    phone_raw=lead.phone_raw, phone_norm=lead.phone_norm, owner=lead.owner,
                    followup_status=lead.followup_status, sheet_source=lead.source, notes=lead.notes,
                    row_values=lead.values,
                )
        self.owner_leads = leads
        self.loaded = True
        return leads

    def pending(self) -> list[SheetLead]:
        s = self.settings.get()
        return order_leads([lead for lead in self.owner_leads if is_pending(lead, s)], s.lead_ordering)

    def queue(self) -> list[SheetLead]:
        """Pending leads minus the ones completed/skipped in this session or snoozed.

        With saved results: a «لم يتم الرد» waits ``no_answer_retry_hours`` then comes back, a future
        follow-up waits for its date, and due follow-ups come back (first, when ``followups_first``).
        """
        sess = self.sessions.ensure()
        completed = set(sess.completed_fingerprints or [])
        skipped = set(sess.skipped_fingerprints or [])
        with self.db.session() as s:
            skipped |= SkipRepository(s).active_fingerprints(sess.id)
        outcomes = self.followups.outcomes() if self.followups else {}
        now = utcnow()
        out: list[SheetLead] = []
        for lead in self.pending():
            fp = lead.fingerprint
            if fp in skipped:
                continue
            o = outcomes.get(fp)
            if self.followups:
                wait = self.followups.not_before(o)
                if wait is not None and now < wait:
                    continue
                if fp in completed and not self.followups.comes_back(o):
                    continue
            elif fp in completed:
                continue
            out.append(lead)
        if self.followups and self.settings.get().followups_first:
            def key(lead: SheetLead):
                o = outcomes.get(lead.fingerprint)
                return (0, o.followup_at) if self.followups.is_due(o) else (1, "")
            out.sort(key=key)  # stable: the rest keeps the sheet order
        return out

    def find(self, fingerprint: str) -> SheetLead | None:
        return next((lead for lead in self.owner_leads if lead.fingerprint == fingerprint), None)
