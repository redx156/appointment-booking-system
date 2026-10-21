"""Slot generation: turns a provider's weekly schedule into concrete slots.

Slots are derived data. They are computed on demand from the schedule, the
blocked periods and the existing appointments, and are never stored.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from flask import current_app

from app.extensions import db
from app.models import Appointment, AvailabilitySchedule, BlockedTime, ServiceProvider
from app.models.common import AppointmentStatus, utcnow
from app.utils.timeutils import get_app_tz, local_today, to_local, to_utc_naive

REASON_PAST = "past"
REASON_TOO_FAR = "too_far"
REASON_BLOCKED = "blocked"
REASON_BOOKED = "booked"


def intervals_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open intervals [start, end): intervals that only touch do not overlap."""
    return a_start < b_end and a_end > b_start


@dataclass(frozen=True)
class Slot:
    start_at: datetime      # naive UTC (what we store and compare)
    end_at: datetime        # naive UTC
    local_start: datetime   # aware, application timezone (what we display)
    local_end: datetime
    available: bool
    reason: Optional[str] = None  # why it is unavailable; None when available


def generate_slots(
    provider: ServiceProvider, day: date, now_utc: Optional[datetime] = None
) -> list[Slot]:
    """All slots of `provider` on local date `day`, each marked available or not."""
    now_utc = now_utc or utcnow()
    tz = get_app_tz()

    schedule = db.session.execute(
        db.select(AvailabilitySchedule).filter_by(
            provider_id=provider.id, day_of_week=day.weekday()
        )
    ).scalar_one_or_none()
    if schedule is None:
        return []

    duration = timedelta(minutes=provider.slot_duration_minutes)
    window_start = datetime.combine(day, schedule.start_time)  # naive local time
    window_end = datetime.combine(day, schedule.end_time)
    range_start = to_utc_naive(window_start, tz)
    range_end = to_utc_naive(window_end, tz)

    # Fetch everything that touches the working window once, then compare in Python.
    blocks = db.session.execute(
        db.select(BlockedTime).where(
            BlockedTime.provider_id == provider.id,
            BlockedTime.start_at < range_end,
            BlockedTime.end_at > range_start,
        )
    ).scalars().all()
    booked = db.session.execute(
        db.select(Appointment).where(
            Appointment.provider_id == provider.id,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.start_at < range_end,
            Appointment.end_at > range_start,
        )
    ).scalars().all()

    horizon_day = local_today(now_utc, tz) + timedelta(
        days=current_app.config["BOOKING_HORIZON_DAYS"]
    )
    too_far = day > horizon_day

    slots: list[Slot] = []
    cursor = window_start
    while cursor + duration <= window_end:  # a slot must end inside working hours
        start_at = to_utc_naive(cursor, tz)
        end_at = to_utc_naive(cursor + duration, tz)

        reason = None
        if start_at <= now_utc:
            reason = REASON_PAST
        elif too_far:
            reason = REASON_TOO_FAR
        elif any(intervals_overlap(start_at, end_at, b.start_at, b.end_at) for b in blocks):
            reason = REASON_BLOCKED
        elif any(intervals_overlap(start_at, end_at, a.start_at, a.end_at) for a in booked):
            reason = REASON_BOOKED

        slots.append(
            Slot(
                start_at=start_at,
                end_at=end_at,
                local_start=to_local(start_at, tz),
                local_end=to_local(end_at, tz),
                available=reason is None,
                reason=reason,
            )
        )
        cursor += duration

    return slots


def available_dates(provider: ServiceProvider, now_utc: Optional[datetime] = None) -> list[date]:
    """Local dates (today through the booking horizon) that have at least one open slot."""
    now_utc = now_utc or utcnow()
    today = local_today(now_utc)
    horizon = current_app.config["BOOKING_HORIZON_DAYS"]

    dates = []
    for offset in range(horizon + 1):
        day = today + timedelta(days=offset)
        if any(slot.available for slot in generate_slots(provider, day, now_utc)):
            dates.append(day)
    return dates