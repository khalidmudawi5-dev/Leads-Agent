"""Status and source mappings (deterministic, user-defined – no guessing)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.adapters.odoo.base import OdooLead
from app.db import Database
from app.errors import AgentError
from app.repositories.mapping_repo import MappingRepository
from app.utils.text import normalize_text

_SEP = re.compile(r"\s*(?:\|\||\||/|\\|›|>|-)\s*")


def source_key(value: str) -> str:
    """Normalize an Odoo source label: 'Meta/Leads' == 'meta / leads' == 'Meta || Leads'."""
    parts = [p for p in _SEP.split(normalize_text(value)) if p]
    return " / ".join(parts)


@dataclass
class SourceResolution:
    mapped: bool
    sheet_value: str = ""
    odoo_value: str = ""  # the Odoo label that matched (or the best label to map)
    candidates: list[str] = field(default_factory=list)  # Odoo labels, in priority order

    def to_dict(self) -> dict:
        return {"mapped": self.mapped, "sheet_value": self.sheet_value, "odoo_value": self.odoo_value,
                "candidates": self.candidates}


def odoo_source_labels(lead: OdooLead | None) -> list[str]:
    """Odoo values to look up, most specific first."""
    if lead is None:
        return []
    labels: list[str] = []

    def add(*parts: str) -> None:
        clean = [p.strip() for p in parts if p and p.strip()]
        if len(clean) == len(parts) and clean:
            label = " / ".join(clean)
            if label not in labels:
                labels.append(label)

    add(lead.source, lead.medium)
    add(lead.utm_source, lead.utm_medium)
    add(lead.source)
    add(lead.utm_source)
    add(lead.campaign)
    add(lead.utm_campaign)
    add(lead.medium)
    return labels


class MappingService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------ status
    def statuses(self) -> list[dict]:
        with self.db.session() as s:
            return [{"code": m.code, "label": m.label_ar, "sheet_value": m.sheet_value, "sort_order": m.sort_order}
                    for m in MappingRepository(s).statuses()]

    def status_sheet_value(self, code: str) -> str:
        with self.db.session() as s:
            row = MappingRepository(s).status(code)
        if row is None:
            raise AgentError("UNKNOWN_RESULT", "نتيجة غير معروفة.")
        if not row.sheet_value.strip():
            raise AgentError(
                "STATUS_NOT_MAPPED",
                f"النتيجة «{row.label_ar}» غير مربوطة بقيمة في Google Sheet. اربطها من الإعدادات > Status Mapping.",
                actions=["open_settings"],
            )
        return row.sheet_value

    def status_label(self, code: str) -> str:
        with self.db.session() as s:
            row = MappingRepository(s).status(code)
        return row.label_ar if row else code

    def save_statuses(self, items: list[dict]) -> None:
        with self.db.session() as s:
            repo = MappingRepository(s)
            for i, item in enumerate(items):
                existing = repo.status(item["code"])
                if existing is None:
                    raise AgentError("UNKNOWN_RESULT", "نتيجة غير معروفة.")
                repo.upsert_status(item["code"], item.get("label") or existing.label_ar,
                                   (item.get("sheet_value") or "").strip(), item.get("sort_order", i))

    # ------------------------------------------------------------ source
    def sources(self) -> list[dict]:
        with self.db.session() as s:
            return [{"id": m.id, "odoo_value": m.odoo_value, "sheet_value": m.sheet_value}
                    for m in MappingRepository(s).sources()]

    def save_source(self, odoo_value: str, sheet_value: str) -> dict:
        key = source_key(odoo_value)
        if not key or not sheet_value.strip():
            raise AgentError("BAD_MAPPING", "أدخل قيمة Odoo وقيمة Google Sheet.")
        with self.db.session() as s:
            row = MappingRepository(s).upsert_source(odoo_value.strip(), key, sheet_value.strip())
            return {"id": row.id, "odoo_value": row.odoo_value, "sheet_value": row.sheet_value}

    def delete_source(self, mapping_id: int) -> None:
        with self.db.session() as s:
            MappingRepository(s).delete_source(mapping_id)

    def resolve_source(self, lead: OdooLead | None) -> SourceResolution:
        """Exact (normalized) lookup only. Unmapped → the UI asks the user to pick."""
        labels = odoo_source_labels(lead)
        with self.db.session() as s:
            repo = MappingRepository(s)
            for label in labels:
                row = repo.source_by_key(source_key(label))
                if row:
                    return SourceResolution(True, row.sheet_value, label, labels)
        return SourceResolution(False, "", labels[0] if labels else "", labels)
