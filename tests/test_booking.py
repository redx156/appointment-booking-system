import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Appointment
from app.models.common import AppointmentStatus, Role
from app.services.booking import BookingError, book_appointment
from app.services.calendar_view import (
    STATE_AVAILABLE,
    STATE_OUTSIDE,
    STATE_UNAVAILABLE,
    build_calendar,
)
from helpers import NOW, add_block, add_schedule, ist, make_appointment, make_provider, make_user


def count_appointments():
    return db.session.query(Appointment).count()


def book(student, provider, start, **kwargs):
    return book_appointment(student.id, provider.id, start, now_utc=NOW, **kwargs)


# ---------- Successful booking ----------

def test_books_a_valid_slot(app):
    provider = make_provider()
    add_schedule(provider)  # Monday 09:00-11:00, 30-minute slots
    student = make_user("s@example.com")

    appointment = book(student, provider, ist(2030, 1, 7, 9, 30), notes="  Course planning ")

    assert appointment.id is not None
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.start_at == ist(2030, 1, 7, 9, 30)
    assert appointment.end_at == ist(2030, 1, 7, 10, 0)
    assert appointment.notes == "Course planning"
    assert count_appointments() == 1


# ---------- Rejections ----------

def test_rejects_time_that_is_not_a_slot_start(app):
    provider = make_provider()
    add_schedule(provider)
    student = make_user("s@example.com")
    with pytest.raises(BookingError, match="not a valid appointment slot"):
        book(student, provider, ist(2030, 1, 7, 9, 15))
    assert count_appointments() == 0


def test_rejects_slot_outside_working_hours(app):
    provider = make_provider()
    add_schedule(provider)  # 09:00-11:00
    student = make_user("s@example.com")
    for start in (ist(2030, 1, 7, 8, 30), ist(2030, 1, 7, 11, 0)):
        with pytest.raises(BookingError, match="not a valid appointment slot"):
            book(student, provider, start)
    assert count_appointments() == 0


def test_rejects_past_slot(app):
    provider = make_provider()
    add_schedule(provider)
    student = make_user("s@example.com")
    with pytest.raises(BookingError, match="already passed"):
        book_appointment(
            student.id, provider.id, ist(2030, 1, 7, 9, 0), now_utc=ist(2030, 1, 7, 9, 45)
        )
    assert count_appointments() == 0


def test_rejects_slot_beyond_booking_horizon(app):
    provider = make_provider()
    add_schedule(provider, weekday=4)  # Friday 2030-02-01 is 31 days after NOW
    student = make_user("s@example.com")
    with pytest.raises(BookingError, match="up to 30 days"):
        book(student, provider, ist(2030, 2, 1, 9, 0))
    assert count_appointments() == 0


def test_rejects_already_booked_slot(app):
    provider = make_provider()
    add_schedule(provider)
    first = make_user("a@example.com")
    second = make_user("b@example.com")
    book(first, provider, ist(2030, 1, 7, 9, 0))
    with pytest.raises(BookingError, match="just been taken"):
        book(second, provider, ist(2030, 1, 7, 9, 0))
    assert count_appointments() == 1


def test_rejects_slot_overlapping_a_longer_existing_appointment(app):
    provider = make_provider()  # now offers 30-minute slots
    add_schedule(provider)
    first = make_user("a@example.com")
    second = make_user("b@example.com")
    # Booked earlier when the provider used 45-minute slots: 09:00-09:45.
    make_appointment(first, provider, ist(2030, 1, 7, 9, 0), minutes=45)

    with pytest.raises(BookingError, match="just been taken"):
        book(second, provider, ist(2030, 1, 7, 9, 30))  # 09:30-10:00 overlaps it

    appointment = book(second, provider, ist(2030, 1, 7, 10, 0))  # starts after it ends
    assert appointment.start_at == ist(2030, 1, 7, 10, 0)


def test_rejects_blocked_slot(app):
    provider = make_provider()
    add_schedule(provider)
    add_block(provider, ist(2030, 1, 7, 9, 30), ist(2030, 1, 7, 10, 30))
    student = make_user("s@example.com")
    with pytest.raises(BookingError, match="not available at that time"):
        book(student, provider, ist(2030, 1, 7, 10, 0))
    assert count_appointments() == 0


def test_student_may_hold_one_confirmed_appointment_per_provider(app):
    provider = make_provider()
    add_schedule(provider)
    student = make_user("s@example.com")
    book(student, provider, ist(2030, 1, 7, 9, 0))
    with pytest.raises(BookingError, match="already have a confirmed appointment"):
        book(student, provider, ist(2030, 1, 7, 10, 0))
    assert count_appointments() == 1


def test_rejects_inactive_provider(app):
    provider = make_provider()
    add_schedule(provider)
    provider.user.is_active = False
    db.session.commit()
    student = make_user("s@example.com")
    with pytest.raises(BookingError, match="not available for booking"):
        book(student, provider, ist(2030, 1, 7, 9, 0))


def test_rejects_unknown_provider(app):
    student = make_user("s@example.com")
    with pytest.raises(BookingError, match="not available for booking"):
        book_appointment(student.id, 999, ist(2030, 1, 7, 9, 0), now_utc=NOW)


def test_rejects_non_student_account(app):
    provider = make_provider()
    add_schedule(provider)
    with pytest.raises(BookingError, match="Only active student accounts"):
        book_appointment(provider.user.id, provider.id, ist(2030, 1, 7, 9, 0), now_utc=NOW)
    assert count_appointments() == 0


# ---------- Re-booking and cleanup ----------

def test_cancelled_slot_can_be_booked_again(app):
    provider = make_provider()
    add_schedule(provider)
    first = make_user("a@example.com")
    second = make_user("b@example.com")
    make_appointment(first, provider, ist(2030, 1, 7, 9, 0), status=AppointmentStatus.CANCELLED)

    appointment = book(second, provider, ist(2030, 1, 7, 9, 0))
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert count_appointments() == 2


def test_student_can_rebook_same_provider_after_cancelling(app):
    provider = make_provider()
    add_schedule(provider)
    student = make_user("s@example.com")
    first = book(student, provider, ist(2030, 1, 7, 9, 0))

    first.status = AppointmentStatus.CANCELLED
    db.session.commit()

    second = book(student, provider, ist(2030, 1, 7, 9, 30))
    assert second.status == AppointmentStatus.CONFIRMED


def test_failed_booking_does_not_block_later_bookings(app):
    provider = make_provider()
    add_schedule(provider)
    first = make_user("a@example.com")
    second = make_user("b@example.com")
    with pytest.raises(BookingError):
        book(first, provider, ist(2030, 1, 7, 9, 15))  # invalid slot
    appointment = book(second, provider, ist(2030, 1, 7, 9, 0))
    assert appointment.id is not None
    assert count_appointments() == 1


# ---------- Concurrency (real threads, real SQLite file) ----------

def make_file_app(tmp_path):
    db_file = (tmp_path / "race.db").as_posix()
    config = type(
        "RaceConfig",
        (Config,),
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file}",
            "WTF_CSRF_ENABLED": False,
        },
    )
    return create_app(config)


def run_concurrently(app, jobs):
    """Run (student_id, provider_id, start_at) bookings at the same moment."""
    barrier = threading.Barrier(len(jobs))

    def attempt(job):
        student_id, provider_id, start_at = job
        with app.app_context():
            barrier.wait()
            try:
                book_appointment(student_id, provider_id, start_at, now_utc=NOW)
                return "booked"
            except BookingError:
                return "rejected"

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return list(pool.map(attempt, jobs))


def test_concurrent_bookings_for_the_same_slot_only_one_succeeds(tmp_path):
    app = make_file_app(tmp_path)
    workers = 6
    with app.app_context():
        db.create_all()
        provider = make_provider()
        add_schedule(provider)
        provider_id = provider.id
        student_ids = [make_user(f"s{i}@example.com").id for i in range(workers)]

    start_at = ist(2030, 1, 7, 9, 0)
    results = run_concurrently(app, [(sid, provider_id, start_at) for sid in student_ids])

    with app.app_context():
        confirmed = (
            db.session.query(Appointment)
            .filter_by(status=AppointmentStatus.CONFIRMED)
            .count()
        )
        db.engine.dispose()

    assert results.count("booked") == 1
    assert results.count("rejected") == workers - 1
    assert confirmed == 1


def test_concurrent_bookings_for_different_slots_all_succeed(tmp_path):
    app = make_file_app(tmp_path)
    with app.app_context():
        db.create_all()
        provider = make_provider()
        add_schedule(provider)  # four slots: 09:00, 09:30, 10:00, 10:30
        provider_id = provider.id
        student_ids = [make_user(f"s{i}@example.com").id for i in range(4)]

    starts = [ist(2030, 1, 7, 9, 0), ist(2030, 1, 7, 9, 30), ist(2030, 1, 7, 10, 0), ist(2030, 1, 7, 10, 30)]
    results = run_concurrently(app, [(sid, provider_id, st) for sid, st in zip(student_ids, starts)])

    with app.app_context():
        total = db.session.query(Appointment).count()
        db.engine.dispose()

    assert results == ["booked"] * 4
    assert total == 4


# ---------- Calendar ----------

def test_calendar_marks_available_unavailable_and_outside_days(app):
    provider = make_provider()
    add_schedule(provider)  # Mondays only
    weeks = build_calendar(provider, NOW)  # NOW is Tuesday 2030-01-01 (IST)

    assert len(weeks) == 5
    assert all(len(week) == 7 for week in weeks)
    states = {cell.day: cell.state for week in weeks for cell in week}
    assert states[date(2029, 12, 31)] == STATE_OUTSIDE      # before today
    assert states[date(2030, 1, 1)] == STATE_UNAVAILABLE    # today, not a working day
    assert states[date(2030, 1, 7)] == STATE_AVAILABLE      # a Monday with open slots
    assert states[date(2030, 1, 31)] == STATE_UNAVAILABLE   # last bookable day
    assert states[date(2030, 2, 1)] == STATE_OUTSIDE        # beyond the horizon