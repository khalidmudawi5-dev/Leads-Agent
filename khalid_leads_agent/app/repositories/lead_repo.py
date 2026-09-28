from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LeadCache, LeadSession, SkippedLead
from app.utils.timeutils import utcnow


class LeadCacheRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, fingerprint: str) -> LeadCache | None:
        return self.s.scalar(select(LeadCache).where(LeadCache.fingerprint == fingerprint))

    def upsert(self, fingerprint: str, **fields) -> LeadCache:
        row = self.get(fingerprint)
        if row is None:
            row = LeadCache(fingerprint=fingerprint, **fields)
            self.s.add(row)
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        row.last_seen_at = utcnow()
        self.s.flush()
        return row

    def count_by_match_status(self, statuses: tuple[str, ...]) -> int:
        return self.s.scalar(select(func.count()).select_from(LeadCache).where(LeadCache.match_status.in_(statuses))) or 0

    def find_by_phone(self, phone_norm: str) -> list[LeadCache]:
        return list(self.s.scalars(select(LeadCache).where(LeadCache.phone_norm == phone_norm)))


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def active(self, owner: str) -> LeadSession | None:
        return self.s.scalar(
            select(LeadSession).where(LeadSession.status == "active", LeadSession.owner == owner)
            .order_by(LeadSession.id.desc())
        )

    def get(self, session_id: int) -> LeadSession | None:
        return self.s.get(LeadSession, session_id)

    def create(self, owner: str) -> LeadSession:
        row = LeadSession(owner=owner, status="active", completed_fingerprints=[], skipped_fingerprints=[], errors=[])
        self.s.add(row)
        self.s.flush()
        return row

    def close_all(self, owner: str) -> None:
        for row in self.s.scalars(select(LeadSession).where(LeadSession.status == "active", LeadSession.owner == owner)):
            row.status = "closed"
            row.closed_at = utcnow()


class SkipRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def add(self, **fields) -> SkippedLead:
        row = SkippedLead(**fields)
        self.s.add(row)
        self.s.flush()
        return row

    def active_fingerprints(self, session_id: int | None) -> set[str]:
        now = utcnow()
        result: set[str] = set()
        for row in self.s.scalars(select(SkippedLead).where(SkippedLead.active.is_(True))):
            if row.mode == "session":
                if row.session_id == session_id:
                    result.add(row.fingerprint)
            elif row.until and row.until > now:
                result.add(row.fingerprint)
        return result

    def list_recent(self, limit: int = 300) -> list[SkippedLead]:
        return list(self.s.scalars(select(SkippedLead).order_by(SkippedLead.id.desc()).limit(limit)))

    def deactivate(self, skip_id: int) -> SkippedLead | None:
        row = self.s.get(SkippedLead, skip_id)
        if row:
            row.active = False
        return row

    def deactivate_fingerprint(self, fingerprint: str) -> None:
        for row in self.s.scalars(select(SkippedLead).where(SkippedLead.fingerprint == fingerprint, SkippedLead.active.is_(True))):
            row.active = False
