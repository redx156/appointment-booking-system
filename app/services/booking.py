from datetime import datetime
from typing import Optional

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models import Appointment, ServiceProvider, User
from app.models.common import AppointmentStatus, Role, utcnow
from app.services.slots import (
    REASON_BLOCKED,
    REASON_BOOKED,
    REASON_PAST,
    REASON_TOO_FAR,
    generate_slots,
)
from app.utils.timeutils import to_local


class BookingError(Exception):
    """A booking rule was violated. The message is safe to show to the user."""


UNAVAILABLE_MESSAGES = {
    REASON_PAST: "That time has already passed.",
    REASON_BLOCKED: "The provider is not available at that time.",
    REASON_BOOKED: "That slot has just been taken. Please choose another time.",
}


def _unavailable_message(reason: Optional[str]) -> str:
    if reason == REASON_TOO_FAR:
        days = current_app.config["BOOKING_HORIZON_DAYS"]
        return f"Appointments can only be booked up to {days} days ahead."
    return UNAVAILABLE_MESSAGES.get(reason, "That slot is not available.")


def begin_write_transaction() -> None:
    """Take SQLite's write lock before reading, so check-then-insert is atomic.

    Any transaction opened earlier in the request (for example by the login
    check) is ended first. BEGIN IMMEDIATE then makes a competing booking wait
    here until this one commits, and it will then see this booking.
    Other databases would need row-level locks instead.
    """
    db.session.rollback()
    if db.engine.dialect.name == "sqlite":
        db.session.execute(text("BEGIN IMMEDIATE"))


def book_appointment(
    student_id: int,
    provider_id: int,
    start_at: datetime,
    notes: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> Appointment:
    """Book one slot for a student. `start_at` is naive UTC.

    Every rule is checked inside one write transaction, so the slot cannot be
    taken by someone else between the check and the insert. Raises BookingError
    with a user-safe message if any rule fails; nothing is saved in that case.
    """
    now_utc = now_utc or utcnow()
    notes = (notes or "").strip() or None

    begin_write_transaction()
    try:
        student = db.session.get(User, student_id)
        if student is None or not student.is_active or student.role != Role.STUDENT:
            raise BookingError("Only active student accounts can book appointments.")

        provider = db.session.get(ServiceProvider, provider_id)
        if provider is None or not provider.user.is_active:
            raise BookingError("This provider is not available for booking.")

        # The time must be exactly one of the provider's generated slots.
        # This single check covers working hours, slot duration and alignment.
        local_day = to_local(start_at).date()
        slot = next(
            (s for s in generate_slots(provider, local_day, now_utc) if s.start_at == start_at),
            None,
        )
        if slot is None:
            raise BookingError("That time is not a valid appointment slot.")
        if not slot.available:
            raise BookingError(_unavailable_message(slot.reason))

        # Policy P-7: one confirmed appointment per student per provider.
        already = db.session.execute(
            db.select(db.func.count(Appointment.id)).where(
                Appointment.student_id == student.id,
                Appointment.provider_id == provider.id,
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.end_at > now_utc,  # only upcoming ones count (P-7)
            )
        ).scalar_one()
        if already:
            raise BookingError(
                "You already have a confirmed appointment with this provider. "
                "Cancel or complete it before booking another."
            )

        appointment = Appointment(
            student_id=student.id,
            provider_id=provider.id,
            start_at=slot.start_at,
            end_at=slot.end_at,
            status=AppointmentStatus.CONFIRMED,
            notes=notes,
        )
        db.session.add(appointment)
        db.session.commit()
    except BookingError:
        db.session.rollback()
        raise
    except IntegrityError:
        # Database safety net (the partial unique indexes from Step 3).
        db.session.rollback()
        raise BookingError("That slot has just been taken. Please choose another time.")
    except SQLAlchemyError:
        db.session.rollback()
        raise BookingError("Could not complete the booking. Please try again.")
    return appointment