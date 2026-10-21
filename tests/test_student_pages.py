from datetime import time, timedelta

import pytest

from app.extensions import db
from app.models import Appointment, AppointmentCategory
from app.models.common import AppointmentStatus, Role
from app.services.slots import generate_slots
from app.utils.timeutils import local_today
from helpers import add_schedule, login, make_appointment, make_provider, make_user


def provider_open_every_day(email="rao@example.com"):
    provider = make_provider(email)
    for weekday in range(7):
        add_schedule(provider, weekday=weekday, start=time(9, 0), end=time(17, 0))
    return provider


def open_slots(provider, count=1):
    """The first open slots tomorrow (uses the real clock, so tests never depend on today's date)."""
    day = local_today() + timedelta(days=1)
    return [s for s in generate_slots(provider, day) if s.available][:count]


def book_url(provider, slot):
    return f"/student/providers/{provider.id}/book?start={slot.start_at.isoformat()}"


STUDENT_PATHS = [
    "/student/dashboard",
    "/student/providers",
    "/student/providers/1",
    "/student/providers/1/slots?date=2030-01-07",
    "/student/providers/1/book",
]


# ---------- Access control ----------

@pytest.mark.parametrize("path", STUDENT_PATHS)
def test_student_pages_require_student_role(client, path):
    make_user("p@example.com", role=Role.PROVIDER)

    response = client.get(path)  # anonymous
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]

    login(client, "p@example.com")
    assert client.get(path).status_code == 403  # logged in, wrong role


def test_provider_cannot_post_a_booking(client):
    provider = provider_open_every_day()
    slot = open_slots(provider)[0]
    login(client, provider.user.email)
    response = client.post(
        f"/student/providers/{provider.id}/book", data={"start": slot.start_at.isoformat()}
    )
    assert response.status_code == 403
    assert db.session.query(Appointment).count() == 0


# ---------- Browsing ----------

def test_provider_list_shows_active_providers_only(client):
    provider_open_every_day("a@example.com")
    hidden = provider_open_every_day("b@example.com")
    hidden.user.name = "Dr. Hidden"
    hidden.user.is_active = False
    db.session.commit()
    make_user("s@example.com")
    login(client, "s@example.com")

    page = client.get("/student/providers").data
    assert b"Dr. Rao" in page
    assert b"Dr. Hidden" not in page


def test_provider_list_category_filter(client):
    provider_open_every_day("a@example.com")
    other = provider_open_every_day("b@example.com")
    category = AppointmentCategory(name="Wellbeing")
    db.session.add(category)
    db.session.commit()
    other.category_id = category.id
    other.user.name = "Dr. Wellbeing"
    db.session.commit()
    make_user("s@example.com")
    login(client, "s@example.com")

    page = client.get(f"/student/providers?category={category.id}").data
    assert b"Dr. Wellbeing" in page
    assert b"Dr. Rao" not in page


def test_inactive_provider_pages_return_404(client):
    provider = provider_open_every_day()
    provider.user.is_active = False
    db.session.commit()
    make_user("s@example.com")
    login(client, "s@example.com")

    assert client.get(f"/student/providers/{provider.id}").status_code == 404
    assert client.get(f"/student/providers/{provider.id}/slots?date=2030-01-07").status_code == 404
    assert client.get(f"/student/providers/{provider.id}/book").status_code == 404


def test_calendar_page_links_to_available_dates(client):
    provider = provider_open_every_day()
    make_user("s@example.com")
    login(client, "s@example.com")
    response = client.get(f"/student/providers/{provider.id}")
    assert response.status_code == 200
    assert b"Dr. Rao" in response.data
    assert b"/slots?date=" in response.data


def test_slots_page_shows_bookable_slots(client):
    provider = provider_open_every_day()
    slot = open_slots(provider)[0]
    make_user("s@example.com")
    login(client, "s@example.com")

    day = slot.local_start.date().isoformat()
    response = client.get(f"/student/providers/{provider.id}/slots?date={day}")
    assert response.status_code == 200
    assert slot.local_start.strftime("%I:%M %p").encode() in response.data
    assert b"/book?start=" in response.data


def test_slots_page_with_invalid_date_redirects_to_calendar(client):
    provider = provider_open_every_day()
    make_user("s@example.com")
    login(client, "s@example.com")
    response = client.get(
        f"/student/providers/{provider.id}/slots?date=not-a-date", follow_redirects=True
    )
    assert b"valid date" in response.data


# ---------- Booking flow ----------

def test_book_page_shows_summary_for_available_slot(client):
    provider = provider_open_every_day()
    slot = open_slots(provider)[0]
    make_user("s@example.com")
    login(client, "s@example.com")
    response = client.get(book_url(provider, slot))
    assert response.status_code == 200
    assert b"Confirm booking" in response.data
    assert b"Dr. Rao" in response.data


def test_book_page_for_taken_slot_redirects_with_message(client):
    provider = provider_open_every_day()
    slot = open_slots(provider)[0]
    other = make_user("other@example.com")
    make_appointment(other, provider, slot.start_at)
    make_user("s@example.com")
    login(client, "s@example.com")

    response = client.get(book_url(provider, slot), follow_redirects=True)
    assert b"no longer available" in response.data


def test_booking_flow_creates_confirmed_appointment(client):
    provider = provider_open_every_day()
    slot = open_slots(provider)[0]
    make_user("s@example.com")
    login(client, "s@example.com")

    response = client.post(
        f"/student/providers/{provider.id}/book",
        data={"start": slot.start_at.isoformat(), "notes": "Course planning"},
    )
    assert response.status_code == 302

    appointment = db.session.query(Appointment).one()
    assert response.headers["Location"].endswith(
        f"/student/appointments/{appointment.id}/confirmation"
    )
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.start_at == slot.start_at
    assert appointment.notes == "Course planning"

    page = client.get(response.headers["Location"])
    assert page.status_code == 200
    assert b"Booking confirmed" in page.data
    assert b"Dr. Rao" in page.data


def test_tampered_start_time_is_rejected(client):
    provider = provider_open_every_day()
    slot = open_slots(provider)[0]
    make_user("s@example.com")
    login(client, "s@example.com")
    url = f"/student/providers/{provider.id}/book"

    off_grid = (slot.start_at + timedelta(minutes=5)).isoformat()
    response = client.post(url, data={"start": off_grid}, follow_redirects=True)
    assert b"not a valid appointment slot" in response.data

    response = client.post(url, data={"start": "garbage"}, follow_redirects=True)
    assert b"Invalid booking request" in response.data

    assert db.session.query(Appointment).count() == 0


def test_second_student_cannot_book_a_taken_slot(client):
    provider = provider_open_every_day()
    slot = open_slots(provider)[0]
    url = f"/student/providers/{provider.id}/book"
    make_user("a@example.com")
    make_user("b@example.com")

    login(client, "a@example.com")
    assert client.post(url, data={"start": slot.start_at.isoformat()}).status_code == 302
    client.post("/auth/logout")

    login(client, "b@example.com")
    response = client.post(url, data={"start": slot.start_at.isoformat()}, follow_redirects=True)
    assert b"just been taken" in response.data
    assert db.session.query(Appointment).count() == 1


def test_student_cannot_hold_two_appointments_with_one_provider(client):
    provider = provider_open_every_day()
    first, second = open_slots(provider, count=2)
    make_user("s@example.com")
    login(client, "s@example.com")
    url = f"/student/providers/{provider.id}/book"

    assert client.post(url, data={"start": first.start_at.isoformat()}).status_code == 302
    response = client.post(url, data={"start": second.start_at.isoformat()}, follow_redirects=True)
    assert b"already have a confirmed appointment" in response.data
    assert db.session.query(Appointment).count() == 1


def test_confirmation_page_is_private(client):
    provider = provider_open_every_day()
    slot = open_slots(provider)[0]
    owner = make_user("owner@example.com")
    make_user("intruder@example.com")
    appointment = make_appointment(owner, provider, slot.start_at)
    path = f"/student/appointments/{appointment.id}/confirmation"

    login(client, "intruder@example.com")
    assert client.get(path).status_code == 404
    client.post("/auth/logout")

    login(client, "owner@example.com")
    assert client.get(path).status_code == 200


def test_dashboard_lists_upcoming_appointment(client):
    provider = provider_open_every_day()
    slot = open_slots(provider)[0]
    student = make_user("s@example.com")
    make_appointment(student, provider, slot.start_at)
    login(client, "s@example.com")

    page = client.get("/student/dashboard").data
    assert b"Student Dashboard" in page
    assert b"Dr. Rao" in page