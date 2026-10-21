from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from flask import current_app

from app.models.common import utcnow

UTC = timezone.utc


def get_app_tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["APP_TIMEZONE"])


def to_utc_naive(local_dt: datetime, tz: Optional[ZoneInfo] = None) -> datetime:
    """Convert a wall-clock datetime in the application timezone to naive UTC (for storage)."""
    tz = tz or get_app_tz()
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    return local_dt.astimezone(UTC).replace(tzinfo=None)


def to_local(utc_naive: datetime, tz: Optional[ZoneInfo] = None) -> datetime:
    """Convert a stored naive-UTC datetime to an aware datetime in the application timezone."""
    tz = tz or get_app_tz()
    return utc_naive.replace(tzinfo=UTC).astimezone(tz)


def local_today(now_utc: Optional[datetime] = None, tz: Optional[ZoneInfo] = None) -> date:
    return to_local(now_utc or utcnow(), tz).date()


def format_local(value: Optional[datetime], fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Jinja filter: show a stored UTC datetime in the application timezone."""
    if value is None:
        return ""
    return to_local(value).strftime(fmt)