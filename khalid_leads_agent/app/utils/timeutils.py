"""Time helpers. Timestamps are stored in UTC; UI shows local machine time."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def localnow() -> datetime:
    return datetime.now()


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def fmt_local(dt: datetime | None, pattern: str = "%d/%m/%Y %H:%M") -> str:
    local = to_local(dt)
    return local.strftime(pattern) if local else ""


def end_of_local_day_utc() -> datetime:
    """UTC timestamp of the end of the current local day."""
    local_end = datetime.combine(localnow().date(), time(23, 59, 59))
    return local_end.astimezone(timezone.utc).replace(tzinfo=None)


def start_of_local_day_utc(days_back: int = 0) -> datetime:
    local_start = datetime.combine(localnow().date() - timedelta(days=days_back), time(0, 0))
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


def start_of_local_week_utc() -> datetime:
    """Week starts on Sunday (Saudi work week)."""
    today = localnow().date()
    delta = (today.weekday() + 1) % 7  # Monday=0 … Sunday=6 → Sunday offset 0
    return start_of_local_day_utc(delta)
