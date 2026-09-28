from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceMapping, StatusMapping


class MappingRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- status
    def statuses(self) -> list[StatusMapping]:
        return list(self.s.scalars(select(StatusMapping).order_by(StatusMapping.sort_order, StatusMapping.id)))

    def status(self, code: str) -> StatusMapping | None:
        return self.s.scalar(select(StatusMapping).where(StatusMapping.code == code))

    def upsert_status(self, code: str, label_ar: str, sheet_value: str, sort_order: int = 0) -> StatusMapping:
        row = self.status(code)
        if row is None:
            row = StatusMapping(code=code, label_ar=label_ar, sheet_value=sheet_value, sort_order=sort_order)
            self.s.add(row)
        else:
            row.label_ar, row.sheet_value, row.sort_order = label_ar, sheet_value, sort_order
        self.s.flush()
        return row

    # ---- source
    def sources(self) -> list[SourceMapping]:
        return list(self.s.scalars(select(SourceMapping).order_by(SourceMapping.odoo_value)))

    def source_by_key(self, odoo_key: str) -> SourceMapping | None:
        return self.s.scalar(select(SourceMapping).where(SourceMapping.odoo_key == odoo_key, SourceMapping.active.is_(True)))

    def upsert_source(self, odoo_value: str, odoo_key: str, sheet_value: str) -> SourceMapping:
        row = self.s.scalar(select(SourceMapping).where(SourceMapping.odoo_key == odoo_key))
        if row is None:
            row = SourceMapping(odoo_value=odoo_value, odoo_key=odoo_key, sheet_value=sheet_value, active=True)
            self.s.add(row)
        else:
            row.odoo_value, row.sheet_value, row.active = odoo_value, sheet_value, True
        self.s.flush()
        return row

    def delete_source(self, mapping_id: int) -> bool:
        row = self.s.get(SourceMapping, mapping_id)
        if row:
            self.s.delete(row)
            return True
        return False
