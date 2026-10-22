from datetime import date

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.provider import bp
from app.blueprints.provider.forms import BlockedTimeForm, ScheduleForm
from app.extensions import db
from app.models import BlockedTime
from app.models.common import Role, utcnow
from app.services.availability import (
    DAY_NAMES,
    AvailabilityError,
    create_block,
    save_weekly_schedule,
)
from app.services.slots import generate_slots
from app.utils.roles import role_required
from app.utils.timeutils import local_today

from sqlalchemy import and_, not_

from app.models import Appointment
from app.models.common import AppointmentStatus
from app.services.appointments import (
    AppointmentError,
    AppointmentNotFound,
    cancel_by_provider,
    complete_by_provider,
)

from app.services.dashboard import provider_summary

def current_provider():
    """The logged-in provider's own profile. Every query below is scoped to it (rule BR-4)."""
    profile = current_user.provider_profile
    if profile is None:
        abort(403)
    return profile


def build_schedule_form(provider):
    by_day = {row.day_of_week: row for row in provider.schedules}
    days = []
    for weekday in range(7):
        row = by_day.get(weekday)
        days.append(
            {
                "enabled": row is not None,
                "start_time": row.start_time if row else None,
                "end_time": row.end_time if row else None,
            }
        )
    return ScheduleForm(
        data={"slot_duration_minutes": provider.slot_duration_minutes, "days": days}
    )


def render_availability_page(provider, schedule_form, block_form):
    blocks = db.session.execute(
        db.select(BlockedTime)
        .where(BlockedTime.provider_id == provider.id, BlockedTime.end_at > utcnow())
        .order_by(BlockedTime.start_at)
    ).scalars().all()
    return render_template(
        "provider/availability.html",
        schedule_form=schedule_form,
        block_form=block_form,
        blocks=blocks,
        day_names=DAY_NAMES,
    )


@bp.route("/dashboard")
@role_required(Role.PROVIDER)
def dashboard():
    provider = current_provider()
    now = utcnow()
    return render_template(
        "provider/dashboard.html", summary=provider_summary(provider, now), now=now
    )


@bp.route("/availability")
@role_required(Role.PROVIDER)
def availability():
    provider = current_provider()
    return render_availability_page(provider, build_schedule_form(provider), BlockedTimeForm())


@bp.route("/availability/schedule", methods=["POST"])
@role_required(Role.PROVIDER)
def save_schedule():
    provider = current_provider()
    form = ScheduleForm()
    if form.validate_on_submit():
        windows = {}
        for weekday, entry in enumerate(form.days):
            day = entry.form
            if day.enabled.data:
                windows[weekday] = (day.start_time.data, day.end_time.data)
        try:
            save_weekly_schedule(provider, form.slot_duration_minutes.data, windows)
        except AvailabilityError as error:
            flash(str(error), "danger")
        else:
            flash("Availability saved.", "success")
            return redirect(url_for("provider.availability"))
    return render_availability_page(provider, form, BlockedTimeForm())


@bp.route("/availability/blocked", methods=["POST"])
@role_required(Role.PROVIDER)
def add_blocked():
    provider = current_provider()
    form = BlockedTimeForm()
    if form.validate_on_submit():
        try:
            create_block(
                provider,
                form.date.data,
                form.start_time.data,
                form.end_time.data,
                form.reason.data,
            )
        except AvailabilityError as error:
            flash(str(error), "danger")
        else:
            flash("Time blocked.", "success")
            return redirect(url_for("provider.availability"))
    return render_availability_page(provider, build_schedule_form(provider), form)


@bp.route("/availability/blocked/<int:block_id>/delete", methods=["POST"])
@role_required(Role.PROVIDER)
def delete_blocked(block_id):
    provider = current_provider()
    block = db.session.get(BlockedTime, block_id)
    if block is None or block.provider_id != provider.id:
        abort(404)  # also hides the existence of other providers' records
    db.session.delete(block)
    db.session.commit()
    flash("Blocked period removed.", "info")
    return redirect(url_for("provider.availability"))


@bp.route("/availability/preview")
@role_required(Role.PROVIDER)
def preview():
    provider = current_provider()
    day = local_today()
    raw = request.args.get("date", "")
    if raw:
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            flash("Invalid date. Showing today instead.", "danger")
    return render_template("provider/preview.html", day=day, slots=generate_slots(provider, day))


def get_own_appointment(provider, appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None or appointment.provider_id != provider.id:
        abort(404)  # providers see only their own appointments (BR-4)
    return appointment


@bp.route("/appointments")
@role_required(Role.PROVIDER)
def appointments():
    provider = current_provider()
    view = "history" if request.args.get("view") == "history" else "upcoming"
    now = utcnow()
    query = db.select(Appointment).where(Appointment.provider_id == provider.id)
    if view == "upcoming":
        query = query.where(
            Appointment.status == AppointmentStatus.CONFIRMED, Appointment.end_at > now
        ).order_by(Appointment.start_at)
    else:
        query = query.where(
            not_(and_(Appointment.status == AppointmentStatus.CONFIRMED, Appointment.end_at > now))
        ).order_by(Appointment.start_at.desc())
    items = db.session.execute(query).scalars().all()
    return render_template("provider/appointments.html", items=items, view=view, now=now)


@bp.route("/appointments/<int:appointment_id>")
@role_required(Role.PROVIDER)
def appointment_detail(appointment_id):
    appointment = get_own_appointment(current_provider(), appointment_id)
    return render_template("provider/appointment_detail.html", appointment=appointment, now=utcnow())


@bp.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
@role_required(Role.PROVIDER)
def cancel_appointment(appointment_id):
    provider = current_provider()
    try:
        cancel_by_provider(provider.id, appointment_id)
    except AppointmentNotFound:
        abort(404)
    except AppointmentError as error:
        flash(str(error), "danger")
    else:
        flash("Appointment cancelled.", "success")
    return redirect(url_for("provider.appointments"))


@bp.route("/appointments/<int:appointment_id>/complete", methods=["POST"])
@role_required(Role.PROVIDER)
def complete_appointment(appointment_id):
    provider = current_provider()
    try:
        complete_by_provider(provider.id, appointment_id)
    except AppointmentNotFound:
        abort(404)
    except AppointmentError as error:
        flash(str(error), "danger")
    else:
        flash("Appointment marked as completed.", "success")
    return redirect(url_for("provider.appointments"))