from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import Appointment, AvailabilitySchedule, BlockedTime, ServiceProvider
from app.models.common import AppointmentStatus, utcnow
from app.utils.timeutils import to_utc_naive

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MIN_SLOT_MINUTES = 10
MAX_SLOT_MINUTES = 120


class AvailabilityError(Exception):
    """A scheduling rule was violated. The message is safe to show to the user."""


def save_weekly_schedule(
    provider: ServiceProvider,
    duration_minutes: int,
    windows: dict[int, tuple[time, time]],
) -> None:
    """Replace the provider's weekly schedule.

    `windows` maps weekday (0 = Monday) to (start, end) for each working day.
    Days missing from `windows` become non-working days. Existing appointments
    are not touched: they keep their own start and end times (policy P-8).
    """
    if not MIN_SLOT_MINUTES <= duration_minutes <= MAX_SLOT_MINUTES:
        raise AvailabilityError(
            f"Appointment length must be between {MIN_SLOT_MINUTES} and {MAX_SLOT_MINUTES} minutes."
        )

    # Validate everything first, so a bad row never leaves a half-saved schedule.
    for weekday, (start, end) in windows.items():
        if weekday not in range(7):
            raise AvailabilityError("Invalid weekday.")
        if end <= start:
            raise AvailabilityError(f"{DAY_NAMES[weekday]}: end time must be after the start time.")
        window = datetime.combine(date.min, end) - datetime.combine(date.min, start)
        if window < timedelta(minutes=duration_minutes):
            raise AvailabilityError(
                f"{DAY_NAMES[weekday]}: the working window must fit at least one "
                f"{duration_minutes}-minute appointment."
            )

    provider.slot_duration_minutes = duration_minutes
    existing = {row.day_of_week: row for row in provider.schedules}
    for weekday in range(7):
        window = windows.get(weekday)
        current = existing.get(weekday)
        if window is None:
            if current is not None:
                db.session.delete(current)
        elif current is None:
            db.session.add(
                AvailabilitySchedule(
                    provider_id=provider.id,
                    day_of_week=weekday,
                    start_time=window[0],
                    end_time=window[1],
                )
            )
        else:
            current.start_time, current.end_time = window

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise AvailabilityError("Could not save the schedule. Please try again.")


def create_block(
    provider: ServiceProvider,
    day: date,
    start_time: Optional[time] = None,
    end_time: Optional[time] = None,
    reason: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> BlockedTime:
    """Block part of a local day, or the whole day when no times are given.

    Rule P-10: a period that overlaps a confirmed appointment cannot be blocked.
    """
    now_utc = now_utc or utcnow()

    if (start_time is None) != (end_time is None):
        raise AvailabilityError(
            "Enter both a start time and an end time, or leave both empty to block the whole day."
        )

    if start_time is None:
        local_start = datetime.combine(day, time.min)
        local_end = local_start + timedelta(days=1)
    else:
        if end_time <= start_time:
            raise AvailabilityError("The end time must be after the start time.")
        local_start = datetime.combine(day, start_time)
        local_end = datetime.combine(day, end_time)

    start_at = to_utc_naive(local_start)
    end_at = to_utc_naive(local_end)

    if end_at <= now_utc:
        raise AvailabilityError("You cannot block a period that is already in the past.")

    conflicts = db.session.execute(
        db.select(db.func.count(Appointment.id)).where(
            Appointment.provider_id == provider.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.start_at < end_at,
            Appointment.end_at > start_at,
        )
    ).scalar_one()
    if conflicts:
        raise AvailabilityError(
            f"This period overlaps {conflicts} confirmed appointment(s). "
            "Cancel them first, then block the time."
        )

    block = BlockedTime(
        provider_id=provider.id,
        start_at=start_at,
        end_at=end_at,
        reason=(reason or "").strip() or None,
    )
    db.session.add(block)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise AvailabilityError("Could not save the blocked period. Please try again.")
    return block