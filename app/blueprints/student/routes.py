from datetime import date, datetime
from typing import Optional

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.student import bp
from app.blueprints.student.forms import BookingForm
from app.extensions import db
from app.models import Appointment, AppointmentCategory, ServiceProvider, User
from app.models.common import AppointmentStatus, Role, utcnow
from app.services.booking import BookingError, book_appointment
from app.services.calendar_view import STATE_AVAILABLE, build_calendar
from app.services.slots import generate_slots
from app.utils.roles import role_required
from app.utils.timeutils import to_local

from sqlalchemy import and_, not_

from app.services.appointments import (
    AppointmentError,
    AppointmentNotFound,
    cancel_by_student,
    reschedule_appointment,
)

def get_bookable_provider(provider_id: int) -> ServiceProvider:
    provider = db.session.get(ServiceProvider, provider_id)
    if provider is None or not provider.user.is_active:
        abort(404)
    return provider


def parse_iso_date(raw: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(raw or "")
    except ValueError:
        return None


def parse_utc_start(raw: Optional[str]) -> Optional[datetime]:
    """Parse the naive-UTC slot start that the slot links carry."""
    try:
        value = datetime.fromisoformat(raw or "")
    except ValueError:
        return None
    return value if value.tzinfo is None else None


@bp.route("/dashboard")
@role_required(Role.STUDENT)
def dashboard():
    upcoming = db.session.execute(
        db.select(Appointment)
        .where(
            Appointment.student_id == current_user.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.end_at > utcnow(),
        )
        .order_by(Appointment.start_at)
        .limit(5)
    ).scalars().all()
    return render_template("student/dashboard.html", upcoming=upcoming)


@bp.route("/providers")
@role_required(Role.STUDENT)
def providers():
    category_id = request.args.get("category", type=int)
    query = (
        db.select(ServiceProvider)
        .join(User, ServiceProvider.user_id == User.id)
        .where(User.is_active.is_(True))
        .order_by(User.name)
    )
    if category_id:
        query = query.where(ServiceProvider.category_id == category_id)
    items = db.session.execute(query).scalars().all()
    categories = db.session.execute(
        db.select(AppointmentCategory).order_by(AppointmentCategory.name)
    ).scalars().all()
    return render_template(
        "student/providers.html", providers=items, categories=categories, selected=category_id
    )


@bp.route("/providers/<int:provider_id>")
@role_required(Role.STUDENT)
def provider_calendar(provider_id):
    provider = get_bookable_provider(provider_id)
    weeks = build_calendar(provider)
    has_open_days = any(cell.state == STATE_AVAILABLE for week in weeks for cell in week)
    return render_template(
        "student/calendar.html", provider=provider, weeks=weeks, has_open_days=has_open_days
    )


@bp.route("/providers/<int:provider_id>/slots")
@role_required(Role.STUDENT)
def slots(provider_id):
    provider = get_bookable_provider(provider_id)
    day = parse_iso_date(request.args.get("date"))
    if day is None:
        flash("Please choose a valid date.", "danger")
        return redirect(url_for("student.provider_calendar", provider_id=provider.id))
    return render_template(
        "student/slots.html", provider=provider, day=day, slots=generate_slots(provider, day)
    )


@bp.route("/providers/<int:provider_id>/book", methods=["GET", "POST"])
@role_required(Role.STUDENT)
def book(provider_id):
    provider = get_bookable_provider(provider_id)
    calendar_url = url_for("student.provider_calendar", provider_id=provider.id)

    if request.method == "POST":
        form = BookingForm()
        start = parse_utc_start(form.start.data) if form.validate_on_submit() else None
        if start is None:
            flash("Invalid booking request. Please choose a time again.", "danger")
            return redirect(calendar_url)

        try:
            appointment = book_appointment(current_user.id, provider.id, start, form.notes.data)
        except BookingError as error:
            flash(str(error), "danger")
            return redirect(
                url_for(
                    "student.slots",
                    provider_id=provider.id,
                    date=to_local(start).date().isoformat(),
                )
            )
        flash("Your appointment is confirmed.", "success")
        return redirect(url_for("student.confirmation", appointment_id=appointment.id))

    # GET: show a summary of the chosen slot, if it is still bookable.
    start = parse_utc_start(request.args.get("start"))
    if start is None:
        flash("Please choose a time first.", "warning")
        return redirect(calendar_url)

    day = to_local(start).date()
    slot = next((s for s in generate_slots(provider, day) if s.start_at == start), None)
    if slot is None or not slot.available:
        flash("That time is no longer available. Please choose another slot.", "warning")
        return redirect(url_for("student.slots", provider_id=provider.id, date=day.isoformat()))

    form = BookingForm(start=start.isoformat())
    return render_template("student/book.html", provider=provider, slot=slot, form=form)


@bp.route("/appointments/<int:appointment_id>/confirmation")
@role_required(Role.STUDENT)
def confirmation(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None or appointment.student_id != current_user.id:
        abort(404)  # students can see only their own appointments (BR-3)
    return render_template("student/confirmation.html", appointment=appointment)


@bp.route("/appointments")
@role_required(Role.STUDENT)
def appointments():
    now = utcnow()
    items = db.session.execute(
        db.select(Appointment)
        .where(
            Appointment.student_id == current_user.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.end_at > now,
        )
        .order_by(Appointment.start_at)
    ).scalars().all()
    return render_template("student/appointments.html", items=items, view="upcoming", now=now)


@bp.route("/appointments/history")
@role_required(Role.STUDENT)
def history():
    now = utcnow()
    items = db.session.execute(
        db.select(Appointment)
        .where(
            Appointment.student_id == current_user.id,
            not_(and_(Appointment.status == AppointmentStatus.CONFIRMED, Appointment.end_at > now)),
        )
        .order_by(Appointment.start_at.desc())
    ).scalars().all()
    return render_template("student/appointments.html", items=items, view="history", now=now)


@bp.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
@role_required(Role.STUDENT)
def cancel(appointment_id):
    try:
        cancel_by_student(current_user.id, appointment_id)
    except AppointmentNotFound:
        abort(404)
    except AppointmentError as error:
        flash(str(error), "danger")
    else:
        flash("Your appointment has been cancelled.", "success")
    return redirect(url_for("student.appointments"))


@bp.route("/appointments/<int:appointment_id>/reschedule", methods=["GET", "POST"])
@role_required(Role.STUDENT)
def reschedule(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None or appointment.student_id != current_user.id:
        abort(404)
    provider = appointment.provider
    page_url = url_for("student.reschedule", appointment_id=appointment.id)

    if request.method == "POST":
        start = parse_utc_start(request.form.get("start"))
        if start is None:
            flash("Invalid request. Please choose a time again.", "danger")
            return redirect(page_url)
        try:
            reschedule_appointment(current_user.id, appointment.id, start)
        except AppointmentNotFound:
            abort(404)
        except AppointmentError as error:
            flash(str(error), "danger")
            return redirect(page_url)
        flash("Your appointment has been rescheduled.", "success")
        return redirect(url_for("student.confirmation", appointment_id=appointment_id))

    if appointment.status != AppointmentStatus.CONFIRMED:
        flash("Only confirmed appointments can be rescheduled.", "warning")
        return redirect(url_for("student.appointments"))

    day = parse_iso_date(request.args.get("date"))
    if day is None:
        return render_template(
            "student/reschedule.html",
            appointment=appointment,
            provider=provider,
            weeks=build_calendar(provider),
            day=None,
            slots=None,
        )
    slots = generate_slots(provider, day, exclude_appointment_id=appointment.id)
    return render_template(
        "student/reschedule.html",
        appointment=appointment,
        provider=provider,
        weeks=None,
        day=day,
        slots=slots,
    )