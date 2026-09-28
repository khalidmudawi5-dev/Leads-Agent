from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import CallResult


class CallResultRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def by_key(self, key: str) -> CallResult | None:
        return self.s.scalar(select(CallResult).where(CallResult.idempotency_key == key))

    def get(self, result_id: int) -> CallResult | None:
        return self.s.get(CallResult, result_id)

    def recent_same(self, fingerprint: str | None, phone_norm: str, result_code: str, since: datetime) -> CallResult | None:
        """A non-dry-run save of the same lead + same result after ``since`` (duplicate protection)."""
        cond = CallResult.fingerprint == fingerprint if fingerprint else CallResult.phone_norm == phone_norm
        return self.s.scalar(
            select(CallResult)
            .where(cond, CallResult.result_code == result_code, CallResult.created_at >= since,
                   CallResult.dry_run.is_(False), CallResult.status != "failed")
            .order_by(CallResult.id.desc())
        )

    def add(self, row: CallResult) -> CallResult:
        self.s.add(row)
        self.s.flush()
        return row

    def counts_since(self, since: datetime) -> dict[str, int]:
        rows = self.s.execute(
            select(CallResult.result_code, func.count()).where(CallResult.created_at >= since).group_by(CallResult.result_code)
        ).all()
        return {code: n for code, n in rows}

    def search(
        self,
        since: datetime | None = None,
        name: str = "",
        phone_norm: str = "",
        result_code: str = "",
        odoo_ok: bool | None = None,
        sheet_ok: bool | None = None,
        limit: int = 500,
    ) -> list[CallResult]:
        q = select(CallResult)
        if since:
            q = q.where(CallResult.created_at >= since)
        if name:
            q = q.where(CallResult.company_name.contains(name))
        if phone_norm:
            q = q.where(CallResult.phone_norm.contains(phone_norm[-9:]))
        if result_code:
            q = q.where(CallResult.result_code == result_code)
        if odoo_ok is True:
            q = q.where(CallResult.odoo_note_status.in_(("success", "dry_run")))
        elif odoo_ok is False:
            q = q.where(CallResult.odoo_note_status == "failed")
        if sheet_ok is True:
            q = q.where(CallResult.sheet_status.in_(("success", "dry_run")))
        elif sheet_ok is False:
            q = q.where(or_(CallResult.sheet_status == "failed", CallResult.sheet_status == "blocked"))
        return list(self.s.scalars(q.order_by(CallResult.id.desc()).limit(limit)))
