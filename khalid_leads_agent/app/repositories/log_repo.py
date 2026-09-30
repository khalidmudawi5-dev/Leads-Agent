from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, ErrorLog, SyncLog


class LogRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def add_sync(self, **fields) -> SyncLog:
        row = SyncLog(**fields)
        self.s.add(row)
        return row

    def add_audit(self, **fields) -> AuditLog:
        row = AuditLog(**fields)
        self.s.add(row)
        return row

    def add_error(self, **fields) -> ErrorLog:
        row = ErrorLog(**fields)
        self.s.add(row)
        self.s.flush()
        return row

    def errors(self, limit: int = 300, include_resolved: bool = False) -> list[ErrorLog]:
        q = select(ErrorLog)
        if not include_resolved:
            q = q.where(ErrorLog.resolved.is_(False))
        return list(self.s.scalars(q.order_by(ErrorLog.id.desc()).limit(limit)))

    def resolve_all(self) -> None:
        for row in self.s.scalars(select(ErrorLog).where(ErrorLog.resolved.is_(False))):
            row.resolved = True

    def audits(self, limit: int = 300) -> list[AuditLog]:
        return list(self.s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)))

    def syncs_for(self, action_id: str) -> list[SyncLog]:
        return list(self.s.scalars(select(SyncLog).where(SyncLog.action_id == action_id).order_by(SyncLog.id)))
