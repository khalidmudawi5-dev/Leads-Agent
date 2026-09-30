from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SettingEntry


class SettingsRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def all(self) -> dict[str, Any]:
        return {row.key: row.value for row in self.s.scalars(select(SettingEntry))}

    def set_many(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            row = self.s.get(SettingEntry, key)
            if row is None:
                self.s.add(SettingEntry(key=key, value=value))
            else:
                row.value = value
