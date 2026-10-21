from datetime import datetime, timedelta
from typing import Optional

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import Appointment
from app.models.common import AppointmentStatus, utcnow
from app.services.booking import _unavailable_message, begin_write_transaction
from app.services.slots import generate_slots
from app.utils.timeutils import to_local


class AppointmentError(Exception):
    """A rule was violated. The message is safe to show to the user."""


class AppointmentNotFound(AppointmentError):
    """Missing, or not owned by the caller (the routes turn this into a 404)."""


def _deadline_hours() -> int:
    return current_app.config["CANCELLATION_DEADLINE_HOURS"]


def _in_write_transaction(work):
    """Run `work()` inside one write-locked transaction; roll back on any failure."""
    begin_write_transaction()
    try:
        result = work()
        db.session.commit()
        return result
    except AppointmentError:
        db.session.rollback()
        raise
    except SQLAlchemyError:
        db.session.rollback()
        raise AppointmentError("Could not save the change. Please try again.")


def _load(appointment_id, student_id=None, provider_id=None) -> Appointment:
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None:
        raise AppointmentNotFound("Appointment not found.")
    if student_id is not None and appointment.student_id != student_id:
        raise AppointmentNotFound("Appointment not found.")
    if provider_id is not None and appointment.provider_id != provider_id:
        raise AppointmentNotFound("Appointment not found.")
    return appointment


def _require_confirmed(appointment: Appointment, verb: str) -> None:
    if appointment.status == AppointmentStatus.COMPLETED:
        raise AppointmentError(f"A completed appointment cannot be {verb}.")
    if appointment.status == AppointmentStatus.CANCELLED:
        raise AppointmentError("This appointment has already been cancelled.")


def cancel_by_student(student_id: int, appointment_id: int, now_utc: Optional[datetime] = None):
    """Policy P-3: allowed only if the appointment starts at least 12 hours from now."""
    now_utc = now_utc or utcnow()

    def work():
        appointment = _load(appointment_id, student_id=student_id)
        _require_confirmed(appointment, "cancelled")
        if appointment.start_at - now_utc < timedelta(hours=_deadline_hours()):
            raise AppointmentError(
                f"Appointments can only be cancelled at least {_deadline_hours()} hours before they start."
            )
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancelled_at = now_utc
        return appointment

    return _in_write_transaction(work)


def cancel_by_provider(provider_id: int, appointment_id: int, now_utc: Optional[datetime] = None):
    """Policy P-4: a provider may cancel any of their confirmed appointments before it starts."""
    now_utc = now_utc or utcnow()

    def work():
        appointment = _load(appointment_id, provider_id=provider_id)
        _require_confirmed(appointment, "cancelled")
        if appointment.start_at <= now_utc:
            raise AppointmentError(
                "This appointment has already started. Mark it as completed instead."
            )
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancelled_at = now_utc
        return appointment

    return _in_write_transaction(work)


def complete_by_provider(provider_id: int, appointment_id: int, now_utc: Optional[datetime] = None):
    """A provider may mark a confirmed appointment completed once it has started."""
    now_utc = now_utc or utcnow()

    def work():
        appointment = _load(appointment_id, provider_id=provider_id)
        if appointment.status == AppointmentStatus.COMPLETED:
            raise AppointmentError("This appointment is already completed.")
        if appointment.status == AppointmentStatus.CANCELLED:
            raise AppointmentError("A cancelled appointment cannot be completed.")
        if appointment.start_at > now_utc:
            raise AppointmentError("An appointment can only be completed after it has started.")
        appointment.status = AppointmentStatus.COMPLETED
        return appointment

    return _in_write_transaction(work)


def reschedule_appointment(
    student_id: int, appointment_id: int, new_start: datetime, now_utc: Optional[datetime] = None
):
    """Move a confirmed appointment to another slot of the same provider.

    Policies P-3 and P-9: the 12-hour rule uses the ORIGINAL start time, and the
    new slot must pass every booking rule. The appointment keeps its identity
    (same row), so its history is preserved.
    """
    now_utc = now_utc or utcnow()

    def work():
        appointment = _load(appointment_id, student_id=student_id)
        _require_confirmed(appointment, "rescheduled")
        if appointment.start_at - now_utc < timedelta(hours=_deadline_hours()):
            raise AppointmentError(
                f"Appointments can only be rescheduled at least {_deadline_hours()} hours before they start."
            )
        if new_start == appointment.start_at:
            raise AppointmentError("Please choose a different time from your current appointment.")

        provider = appointment.provider
        if not provider.user.is_active:
            raise AppointmentError("This provider is not available for booking.")

        day = to_local(new_start).date()
        slot = next(
            (
                s
                for s in generate_slots(
                    provider, day, now_utc, exclude_appointment_id=appointment.id
                )
                if s.start_at == new_start
            ),
            None,
        )
        if slot is None:
            raise AppointmentError("That time is not a valid appointment slot.")
        if not slot.available:
            raise AppointmentError(_unavailable_message(slot.reason))

        appointment.start_at = slot.start_at
        appointment.end_at = slot.end_at
        return appointment

    return _in_write_transaction(work)