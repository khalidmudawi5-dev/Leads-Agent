"""Merged settings (.env defaults + values saved from the Settings screen)."""
from __future__ import annotations

import threading
from typing import Any

from app.config import AppSettings, EnvSettings, defaults_from_env
from app.db import Database
from app.repositories.mapping_repo import MappingRepository
from app.repositories.settings_repo import SettingsRepository
from app.utils.logging import set_level

# code, Arabic label (button), default sheet dropdown value
RESULT_CODES: list[tuple[str, str, str]] = [
    ("INTERESTED", "مهتم", "مهتم"),
    ("NOT_INTERESTED", "غير مهتم", "غير مهتم"),
    ("NO_ANSWER", "لم يتم الرد", "لم يتم الرد"),
    ("INVALID_NUMBER", "رقم غير صحيح", "بيانات التواصل غير صحيحة"),
    ("FOLLOW_UP", "متابعة لاحقًا", "متابعة"),
    ("SUBSCRIBED", "تم الاشتراك", "تم الاشتراك"),
]
RESULT_LABELS = {code: label for code, label, _ in RESULT_CODES}


class SettingsService:
    def __init__(self, db: Database, env: EnvSettings) -> None:
        self.db = db
        self.env = env
        self._cache: AppSettings | None = None
        self._lock = threading.Lock()

    def seed(self) -> None:
        """Insert default status mappings on first run (never overwrites user edits)."""
        with self.db.session() as s:
            srepo = SettingsRepository(s)
            # 1.3: the fast call mode became the default; switch once (the old default was never a choice).
            stored = srepo.all()
            if "call_mode_v13" not in stored:
                if stored.get("call_launch_mode") == "odoo_click":
                    srepo.set_many({"call_launch_mode": "fast"})
                srepo.set_many({"call_mode_v13": True})
        self._cache = None
        with self.db.session() as s:
            repo = MappingRepository(s)
            existing = {m.code for m in repo.statuses()}
            for order, (code, label, value) in enumerate(RESULT_CODES):
                if code not in existing:
                    repo.upsert_status(code, label, value, order)

    def get(self) -> AppSettings:
        with self._lock:
            if self._cache is None:
                data = defaults_from_env(self.env).model_dump()
                with self.db.session() as s:
                    stored = SettingsRepository(s).all()
                data.update({k: v for k, v in stored.items() if k in AppSettings.model_fields})
                self._cache = AppSettings.model_validate(data)
            return self._cache

    def update(self, values: dict[str, Any]) -> AppSettings:
        """Validate and persist a partial update. ``column_mapping`` is merged key by key."""
        current = self.get().model_dump()
        clean = {k: v for k, v in values.items() if k in AppSettings.model_fields}
        if "column_mapping" in clean and isinstance(clean["column_mapping"], dict):
            merged = dict(current.get("column_mapping", {}))
            merged.update({k: (v or "").strip() for k, v in clean["column_mapping"].items()})
            clean["column_mapping"] = merged
        current.update(clean)
        validated = AppSettings.model_validate(current)
        to_store = {k: getattr(validated, k) for k in clean}
        with self.db.session() as s:
            SettingsRepository(s).set_many(to_store)
        with self._lock:
            self._cache = validated
        if "log_level" in clean:
            set_level(validated.log_level)
        return validated

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None
