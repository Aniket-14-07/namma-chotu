"""India Standard Time helpers. A swappable clock keeps tests deterministic."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_fixed_now: datetime | None = None


def now_ist() -> datetime:
    return _fixed_now if _fixed_now is not None else datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def set_fixed_now(dt: datetime | None) -> None:
    """Tests only."""
    global _fixed_now
    _fixed_now = dt


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday


def month_start(d: date) -> date:
    return d.replace(day=1)
