from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from flask import current_app

from app.models import ServiceProvider
from app.models.common import utcnow
from app.services.slots import available_dates
from app.utils.timeutils import local_today

STATE_AVAILABLE = "available"
STATE_UNAVAILABLE = "unavailable"
STATE_OUTSIDE = "outside"


@dataclass(frozen=True)
class CalendarDay:
    day: date
    state: str


def build_calendar(
    provider: ServiceProvider, now_utc: Optional[datetime] = None
) -> list[list[CalendarDay]]:
    """Weeks (Monday to Sunday) covering today through the booking horizon.

    Days before today or after the horizon are 'outside'. Days inside the window
    are 'available' when at least one slot is open, otherwise 'unavailable'.
    """
    now_utc = now_utc or utcnow()
    today = local_today(now_utc)
    last = today + timedelta(days=current_app.config["BOOKING_HORIZON_DAYS"])
    open_days = set(available_dates(provider, now_utc))

    weeks = []
    day = today - timedelta(days=today.weekday())
    while day <= last:
        week = []
        for _ in range(7):
            if day < today or day > last:
                state = STATE_OUTSIDE
            elif day in open_days:
                state = STATE_AVAILABLE
            else:
                state = STATE_UNAVAILABLE
            week.append(CalendarDay(day, state))
            day += timedelta(days=1)
        weeks.append(week)
    return weeks