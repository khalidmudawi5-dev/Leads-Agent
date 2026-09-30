"""Status and source mappings (deterministic, user-defined – no guessing)."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.adapters.odoo.base import OdooLead
from app.db import Database
from app.errors import AgentError
from app.repositories.mapping_repo import MappingRepository
from app.utils.text import normalize_text

log = logging.getLogger(__name__)
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
    auto: bool = False  # matched an identical sheet dropdown value (no saved mapping needed)

    def to_dict(self) -> dict:
        return {"mapped": self.mapped, "sheet_value": self.sheet_value, "odoo_value": self.odoo_value,
                "candidates": self.candidates, "auto": self.auto}


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
    def __init__(self, db: Database, source_options: Callable[[], list[str]] | None = None) -> None:
        self.db = db
        # Allowed values of the sheet's source column (dropdown), used for identical-value matching.
        self.source_options = source_options

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

    def _sheet_source_options(self) -> list[str]:
        if self.source_options is None:
            return []
        try:
            return self.source_options()
        except Exception:  # noqa: BLE001 - Google not reachable: fall back to saved mappings only
            log.debug("Could not read sheet source options", exc_info=True)
            return []

    def resolve_source(self, lead: OdooLead | None) -> SourceResolution:
        """Deterministic only: a saved mapping first, then an *identical* sheet dropdown value.

        "Identical" means equal after normalization (case, spaces, and the separators / | || - are
        ignored), e.g. Odoo "Meta / Leads" == sheet "Meta || Leads". Nothing fuzzy; if no single
        identical value exists the UI asks the user to pick.
        """
        labels = odoo_source_labels(lead)
        with self.db.session() as s:
            repo = MappingRepository(s)
            for label in labels:
                row = repo.source_by_key(source_key(label))
                if row:
                    return SourceResolution(True, row.sheet_value, label, labels)
        if labels:
            options = self._sheet_source_options()
            for label in labels:
                same = [o for o in options if o.strip() and source_key(o) == source_key(label)]
                if len(same) == 1:
                    return SourceResolution(True, same[0], label, labels, auto=True)
        return SourceResolution(False, "", labels[0] if labels else "", labels)
