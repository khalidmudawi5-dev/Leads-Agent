"""What the agent knows about each customer from the results saved so far.

* **Follow-ups**: the latest result is «متابعة لاحقًا» with a date → due today, overdue or upcoming.
* **No answer**: how many «لم يتم الرد» in a row since the last other result, and when the last one was.

Only real saves count (Dry Run results are previews). Deterministic: dates and counts only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.db import Database
from app.models import CallResult
from app.services.settings_service import SettingsService
from app.utils.timeutils import localnow, start_of_local_day_utc, utcnow


@dataclass
class LeadOutcome:
    fingerprint: str
    last_code: str
    last_at: datetime  # UTC
    followup_at: str = ""  # local "YYYY-MM-DD[ HH:MM]" when last_code is FOLLOW_UP
    followup_note: str = ""
    no_answer_streak: int = 0
    result_id: int = 0

    @property
    def followup_date(self) -> date | None:
        try:
            return datetime.strptime(self.followup_at[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    def followup_state(self, today: date) -> str:
        """due | overdue | upcoming | "" (no open follow-up)."""
        d = self.followup_date if self.last_code == "FOLLOW_UP" else None
        if d is None:
            return ""
        return "overdue" if d < today else "due" if d == today else "upcoming"


class FollowupService:
    def __init__(self, db: Database, settings: SettingsService) -> None:
        self.db = db
        self.settings = settings

    def outcomes(self, days: int = 120) -> dict[str, LeadOutcome]:
        since = utcnow() - timedelta(days=days)
        with self.db.session() as s:
            rows = s.execute(
                select(CallResult.id, CallResult.fingerprint, CallResult.result_code, CallResult.created_at,
                       CallResult.followup_at, CallResult.followup_note)
                .where(CallResult.fingerprint.is_not(None), CallResult.dry_run.is_(False),
                       CallResult.status != "failed", CallResult.created_at >= since)
                .order_by(CallResult.id)
            ).all()
        out: dict[str, LeadOutcome] = {}
        for rid, fp, code, created, fu_at, fu_note in rows:
            prev = out.get(fp)
            streak = (prev.no_answer_streak if prev and prev.last_code == "NO_ANSWER" else 0) + 1 if code == "NO_ANSWER" else 0
            out[fp] = LeadOutcome(fp, code, created, fu_at or "", fu_note or "", streak, rid)
        return out

    # ------------------------------------------------------------------ queue rules
    def not_before(self, o: LeadOutcome | None) -> datetime | None:
        """UTC time before which the customer should not come back to the queue (None = no wait)."""
        if o is None:
            return None
        s = self.settings.get()
        if o.last_code == "NO_ANSWER" and s.no_answer_retry_hours:
            return o.last_at + timedelta(hours=s.no_answer_retry_hours)
        if o.last_code == "FOLLOW_UP" and s.hide_future_followups and o.followup_date:
            if o.followup_date > localnow().date():
                return datetime.max
        return None

    def comes_back(self, o: LeadOutcome | None) -> bool:
        """Saved earlier and now due again: back in the queue even if done earlier in this session."""
        if o is None:
            return False
        today = localnow().date()
        if o.followup_state(today) in ("due", "overdue"):
            return o.last_at < start_of_local_day_utc()  # set on a previous day
        if o.last_code == "NO_ANSWER":
            wait = self.not_before(o)
            return wait is not None and utcnow() >= wait
        return False

    def is_due(self, o: LeadOutcome | None) -> bool:
        return o is not None and o.followup_state(localnow().date()) in ("due", "overdue")
