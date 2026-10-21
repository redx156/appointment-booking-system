from datetime import time, timedelta

import pytest

from app.extensions import db
from app.models import Appointment
from app.models.common import AppointmentStatus, Role, utcnow
from app.services.appointments import (
    AppointmentError,
    AppointmentNotFound,
    cancel_by_provider,
    cancel_by_student,
    complete_by_provider,
    reschedule_appointment,
)
from app.services.booking import book_appointment
from app.services.slots import generate_slots
from app.utils.timeutils import local_today, to_local
from helpers import (
    MONDAY,
    NOW,
    add_block,
    add_schedule,
    ist,
    login,
    make_appointment,
    make_provider,
    make_user,
)

SLOT = ist(2030, 1, 7, 9, 0)  # Monday 09:00 IST
CONFIRMED = AppointmentStatus.CONFIRMED
CANCELLED = AppointmentStatus.CANCELLED
COMPLETED = AppointmentStatus.COMPLETED


def setup_booked(minutes=30):
    provider = make_provider()
    add_schedule(provider)  # Mondays 09:00-11:00, 30-minute slots
    student = make_user("s@example.com")
    appointment = make_appointment(student, provider, SLOT, minutes=minutes)
    return provider, student, appointment


# ---------- Student cancellation ----------

def test_student_cancels_and_slot_reopens(app):
    provider, student, appt = setup_booked()
    cancel_by_student(student.id, appt.id, now_utc=NOW)
    assert appt.status == CANCELLED
    assert appt.cancelled_at == NOW
    assert all(s.available for s in generate_slots(provider, MONDAY, NOW))


def test_student_cancellation_deadline_boundary(app):
    provider, student, appt = setup_booked()
    just_too_late = SLOT - timedelta(hours=12) + timedelta(minutes=1)
    with pytest.raises(AppointmentError, match="at least 12 hours"):
        cancel_by_student(student.id, appt.id, now_utc=just_too_late)
    assert appt.status == CONFIRMED

    cancel_by_student(student.id, appt.id, now_utc=SLOT - timedelta(hours=12))  # exactly 12h
    assert appt.status == CANCELLED


def test_student_cannot_cancel_completed_or_cancelled(app):
    provider, student, appt = setup_booked()
    appt.status = COMPLETED
    db.session.commit()
    with pytest.raises(AppointmentError, match="completed appointment cannot be cancelled"):
        cancel_by_student(student.id, appt.id, now_utc=NOW)

    appt.status = CANCELLED
    db.session.commit()
    with pytest.raises(AppointmentError, match="already been cancelled"):
        cancel_by_student(student.id, appt.id, now_utc=NOW)


def test_student_cannot_cancel_someone_elses_appointment(app):
    provider, student, appt = setup_booked()
    other = make_user("other@example.com")
    with pytest.raises(AppointmentNotFound):
        cancel_by_student(other.id, appt.id, now_utc=NOW)
    assert appt.status == CONFIRMED


# ---------- Provider actions ----------

def test_provider_cancels_before_start(app):
    provider, student, appt = setup_booked()
    cancel_by_provider(provider.id, appt.id, now_utc=SLOT - timedelta(hours=1))  # inside 12h: allowed
    assert appt.status == CANCELLED


def test_provider_cannot_cancel_started_appointment(app):
    provider, student, appt = setup_booked()
    with pytest.raises(AppointmentError, match="already started"):
        cancel_by_provider(provider.id, appt.id, now_utc=SLOT + timedelta(minutes=5))
    assert appt.status == CONFIRMED


def test_provider_cannot_touch_another_providers_appointment(app):
    provider, student, appt = setup_booked()
    other = make_provider("other.provider@example.com")
    with pytest.raises(AppointmentNotFound):
        cancel_by_provider(other.id, appt.id, now_utc=NOW)
    with pytest.raises(AppointmentNotFound):
        complete_by_provider(other.id, appt.id, now_utc=SLOT + timedelta(hours=1))


def test_provider_completes_after_start(app):
    provider, student, appt = setup_booked()
    complete_by_provider(provider.id, appt.id, now_utc=SLOT + timedelta(minutes=1))
    assert appt.status == COMPLETED


def test_provider_cannot_complete_before_start_twice_or_cancelled(app):
    provider, student, appt = setup_booked()
    with pytest.raises(AppointmentError, match="after it has started"):
        complete_by_provider(provider.id, appt.id, now_utc=SLOT - timedelta(minutes=1))

    complete_by_provider(provider.id, appt.id, now_utc=SLOT + timedelta(minutes=1))
    with pytest.raises(AppointmentError, match="already completed"):
        complete_by_provider(provider.id, appt.id, now_utc=SLOT + timedelta(minutes=2))

    appt.status = CANCELLED
    db.session.commit()
    with pytest.raises(AppointmentError, match="cancelled appointment cannot be completed"):
        complete_by_provider(provider.id, appt.id, now_utc=SLOT + timedelta(minutes=3))


# ---------- Rescheduling ----------

def test_reschedule_moves_the_same_appointment(app):
    provider, student, appt = setup_booked()
    original_id = appt.id
    reschedule_appointment(student.id, appt.id, ist(2030, 1, 7, 10, 0), now_utc=NOW)
    assert appt.id == original_id
    assert appt.start_at == ist(2030, 1, 7, 10, 0)
    assert appt.end_at == ist(2030, 1, 7, 10, 30)
    assert appt.status == CONFIRMED
    assert db.session.query(Appointment).count() == 1


def test_reschedule_frees_old_slot_and_takes_new_one(app):
    provider, student, appt = setup_booked()
    reschedule_appointment(student.id, appt.id, ist(2030, 1, 7, 10, 0), now_utc=NOW)
    result = {s.local_start.strftime("%H:%M"): s.reason for s in generate_slots(provider, MONDAY, NOW)}
    assert result["09:00"] is None
    assert result["10:00"] == "booked"


def test_reschedule_may_overlap_own_current_time(app):
    provider, student, appt = setup_booked(minutes=45)  # 09:00-09:45, provider slots are 30 min
    reschedule_appointment(student.id, appt.id, ist(2030, 1, 7, 9, 30), now_utc=NOW)
    assert appt.start_at == ist(2030, 1, 7, 9, 30)
    assert appt.end_at == ist(2030, 1, 7, 10, 0)


def test_reschedule_to_taken_or_blocked_slot_rejected(app):
    provider, student, appt = setup_booked()
    other = make_user("other@example.com")
    make_appointment(other, provider, ist(2030, 1, 7, 10, 0))
    add_block(provider, ist(2030, 1, 7, 10, 30), ist(2030, 1, 7, 11, 0))

    with pytest.raises(AppointmentError, match="just been taken"):
        reschedule_appointment(student.id, appt.id, ist(2030, 1, 7, 10, 0), now_utc=NOW)
    with pytest.raises(AppointmentError, match="not available at that time"):
        reschedule_appointment(student.id, appt.id, ist(2030, 1, 7, 10, 30), now_utc=NOW)
    assert appt.start_at == SLOT


def test_reschedule_rejects_invalid_slot_and_same_time(app):
    provider, student, appt = setup_booked()
    with pytest.raises(AppointmentError, match="not a valid appointment slot"):
        reschedule_appointment(student.id, appt.id, ist(2030, 1, 7, 9, 15), now_utc=NOW)
    with pytest.raises(AppointmentError, match="different time"):
        reschedule_appointment(student.id, appt.id, SLOT, now_utc=NOW)
    assert appt.start_at == SLOT


def test_reschedule_to_a_past_slot_rejected(app):
    provider = make_provider()
    add_schedule(provider)  # Mondays 09:00-11:00
    student = make_user("s@example.com")
    appt = make_appointment(student, provider, ist(2030, 1, 14, 9, 0))  # a week ahead

    now = ist(2030, 1, 7, 10, 15)  # the 10:00 slot today has already started
    with pytest.raises(AppointmentError, match="already passed"):
        reschedule_appointment(student.id, appt.id, ist(2030, 1, 7, 10, 0), now_utc=now)
    assert appt.start_at == ist(2030, 1, 14, 9, 0)


def test_reschedule_uses_original_start_for_deadline(app):
    provider, student, appt = setup_booked()
    with pytest.raises(AppointmentError, match="rescheduled at least 12 hours"):
        reschedule_appointment(
            student.id, appt.id, ist(2030, 1, 7, 10, 0), now_utc=SLOT - timedelta(hours=11)
        )
    assert appt.start_at == SLOT


def test_cannot_reschedule_completed_or_someone_elses(app):
    provider, student, appt = setup_booked()
    other = make_user("other@example.com")
    with pytest.raises(AppointmentNotFound):
        reschedule_appointment(other.id, appt.id, ist(2030, 1, 7, 10, 0), now_utc=NOW)
    appt.status = COMPLETED
    db.session.commit()
    with pytest.raises(AppointmentError, match="cannot be rescheduled"):
        reschedule_appointment(student.id, appt.id, ist(2030, 1, 7, 10, 0), now_utc=NOW)


# ---------- P-7 fix ----------

def test_past_unfinished_appointment_does_not_block_rebooking(app):
    provider = make_provider()
    add_schedule(provider)
    student = make_user("s@example.com")
    make_appointment(student, provider, SLOT)  # confirmed, never marked completed

    later = ist(2030, 1, 8, 9, 0)
    new = book_appointment(student.id, provider.id, ist(2030, 1, 14, 9, 0), now_utc=later)
    assert new.status == CONFIRMED
    assert db.session.query(Appointment).count() == 2


# ---------- Pages ----------

def provider_open_every_day(email="rao@example.com"):
    provider = make_provider(email)
    for weekday in range(7):
        add_schedule(provider, weekday=weekday, start=time(9, 0), end=time(17, 0))
    return provider


def future_slot_start(provider, days=3, index=0):
    """An open slot `days` days ahead (always beyond the 12-hour rule), using the real clock."""
    day = local_today() + timedelta(days=days)
    return [s for s in generate_slots(provider, day) if s.available][index].start_at


def test_student_sees_upcoming_and_history(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    make_appointment(student, provider, future_slot_start(provider, 3, 0))
    make_appointment(student, provider, future_slot_start(provider, 4, 0), status=CANCELLED)
    login(client, "s@example.com")

    upcoming = client.get("/student/appointments")
    assert upcoming.status_code == 200
    assert b"Dr. Rao" in upcoming.data and b"Reschedule" in upcoming.data

    history = client.get("/student/appointments/history")
    assert history.status_code == 200
    assert b"Cancelled" in history.data


def test_student_cancels_through_page(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    appt = make_appointment(student, provider, future_slot_start(provider, 3, 0))
    login(client, "s@example.com")

    response = client.post(f"/student/appointments/{appt.id}/cancel")
    assert response.status_code == 302
    db.session.expire_all()
    assert appt.status == CANCELLED


def test_student_cancel_inside_deadline_shows_error(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    appt = make_appointment(student, provider, utcnow() + timedelta(hours=2))
    login(client, "s@example.com")

    response = client.post(f"/student/appointments/{appt.id}/cancel", follow_redirects=True)
    assert b"at least 12 hours" in response.data
    db.session.expire_all()
    assert appt.status == CONFIRMED


def test_student_cannot_cancel_or_open_others_appointment(client):
    provider = provider_open_every_day()
    owner = make_user("owner@example.com")
    make_user("intruder@example.com")
    appt = make_appointment(owner, provider, future_slot_start(provider, 3, 0))
    login(client, "intruder@example.com")

    assert client.post(f"/student/appointments/{appt.id}/cancel").status_code == 404
    assert client.get(f"/student/appointments/{appt.id}/reschedule").status_code == 404
    db.session.expire_all()
    assert appt.status == CONFIRMED


def test_reschedule_flow_through_pages(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    appt = make_appointment(student, provider, future_slot_start(provider, 3, 0))
    new_start = future_slot_start(provider, 4, 0)
    login(client, "s@example.com")
    url = f"/student/appointments/{appt.id}/reschedule"

    assert client.get(url).status_code == 200
    day = to_local(new_start).date().isoformat()
    page = client.get(f"{url}?date={day}")
    assert page.status_code == 200
    assert b'name="start"' in page.data

    response = client.post(url, data={"start": new_start.isoformat()})
    assert response.status_code == 302
    db.session.expire_all()
    assert appt.start_at == new_start


def test_provider_appointment_pages_require_provider_role(client):
    make_user("s@example.com")
    paths = ["/provider/appointments", "/provider/appointments/1"]
    for path in paths:
        assert client.get(path).status_code == 302  # anonymous
    login(client, "s@example.com")
    for path in paths:
        assert client.get(path).status_code == 403  # wrong role


def test_provider_lists_and_opens_appointment_details(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    appt = make_appointment(student, provider, future_slot_start(provider, 3, 0))
    login(client, provider.user.email)

    assert b"Test User" in client.get("/provider/appointments").data
    detail = client.get(f"/provider/appointments/{appt.id}")
    assert detail.status_code == 200
    assert b"s@example.com" in detail.data


def test_provider_cannot_open_another_providers_appointment(client):
    provider = provider_open_every_day("a@example.com")
    other = provider_open_every_day("b@example.com")
    student = make_user("s@example.com")
    appt = make_appointment(student, other, future_slot_start(other, 3, 0))
    login(client, provider.user.email)

    assert client.get(f"/provider/appointments/{appt.id}").status_code == 404
    assert client.post(f"/provider/appointments/{appt.id}/cancel").status_code == 404


def test_provider_cancels_through_page(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    appt = make_appointment(student, provider, future_slot_start(provider, 3, 0))
    login(client, provider.user.email)

    assert client.post(f"/provider/appointments/{appt.id}/cancel").status_code == 302
    db.session.expire_all()
    assert appt.status == CANCELLED


def test_provider_completes_started_appointment_through_page(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    appt = make_appointment(student, provider, utcnow() - timedelta(hours=2))
    login(client, provider.user.email)

    history = client.get("/provider/appointments?view=history")
    assert b"Awaiting completion" in history.data

    assert client.post(f"/provider/appointments/{appt.id}/complete").status_code == 302
    db.session.expire_all()
    assert appt.status == COMPLETED


def test_admin_appointment_monitor(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    make_user("admin@example.com", role=Role.ADMIN)
    make_appointment(student, provider, future_slot_start(provider, 3, 0))
    make_appointment(student, provider, future_slot_start(provider, 4, 0), status=CANCELLED)

    login(client, "s@example.com")
    assert client.get("/admin/appointments").status_code == 403
    client.post("/auth/logout")

    login(client, "admin@example.com")
    everything = client.get("/admin/appointments")
    assert everything.status_code == 200
    assert b"Dr. Rao" in everything.data
    assert client.get("/admin/appointments?status=cancelled").status_code == 200
    assert client.get("/admin/appointments?status=bogus").status_code == 200