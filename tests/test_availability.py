from datetime import date, time, timedelta

import pytest

from app.extensions import db
from app.models import AvailabilitySchedule, BlockedTime
from app.models.common import AppointmentStatus
from app.services.availability import AvailabilityError, create_block, save_weekly_schedule
from app.utils.timeutils import local_today
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


def schedule_rows():
    return db.session.execute(
        db.select(AvailabilitySchedule).order_by(AvailabilitySchedule.day_of_week)
    ).scalars().all()


# ---------- save_weekly_schedule ----------

def test_save_schedule_creates_updates_and_removes_days(app):
    provider = make_provider()
    save_weekly_schedule(
        provider, 30, {0: (time(9, 0), time(17, 0)), 2: (time(10, 0), time(12, 0))}
    )
    assert [(r.day_of_week, r.start_time, r.end_time) for r in schedule_rows()] == [
        (0, time(9, 0), time(17, 0)),
        (2, time(10, 0), time(12, 0)),
    ]

    save_weekly_schedule(provider, 20, {2: (time(11, 0), time(13, 0))})
    assert [(r.day_of_week, r.start_time) for r in schedule_rows()] == [(2, time(11, 0))]
    assert provider.slot_duration_minutes == 20


def test_save_schedule_rejects_end_before_start(app):
    provider = make_provider()
    with pytest.raises(AvailabilityError, match="end time must be after the start time"):
        save_weekly_schedule(provider, 30, {0: (time(17, 0), time(9, 0))})
    assert schedule_rows() == []


def test_save_schedule_rejects_window_shorter_than_one_slot(app):
    provider = make_provider()
    with pytest.raises(AvailabilityError, match="fit at least one"):
        save_weekly_schedule(provider, 30, {0: (time(9, 0), time(9, 20))})
    assert schedule_rows() == []


def test_save_schedule_rejects_invalid_duration(app):
    provider = make_provider()
    with pytest.raises(AvailabilityError, match="between 10 and 120"):
        save_weekly_schedule(provider, 5, {0: (time(9, 0), time(17, 0))})


# ---------- create_block ----------

def test_whole_day_block_covers_the_local_day(app):
    provider = make_provider()
    block = create_block(provider, MONDAY, now_utc=NOW)
    assert block.start_at == ist(2030, 1, 7, 0, 0)
    assert block.end_at == ist(2030, 1, 8, 0, 0)


def test_partial_block_stores_utc_times_and_reason(app):
    provider = make_provider()
    block = create_block(provider, MONDAY, time(9, 30), time(10, 30), "Meeting", now_utc=NOW)
    assert block.start_at == ist(2030, 1, 7, 9, 30)
    assert block.end_at == ist(2030, 1, 7, 10, 30)
    assert block.reason == "Meeting"


def test_block_needs_both_times_or_neither(app):
    provider = make_provider()
    with pytest.raises(AvailabilityError, match="both"):
        create_block(provider, MONDAY, time(9, 30), None, now_utc=NOW)


def test_block_end_must_be_after_start(app):
    provider = make_provider()
    with pytest.raises(AvailabilityError, match="end time must be after"):
        create_block(provider, MONDAY, time(10, 0), time(9, 0), now_utc=NOW)


def test_block_in_the_past_is_rejected(app):
    provider = make_provider()
    with pytest.raises(AvailabilityError, match="already in the past"):
        create_block(provider, date(2029, 12, 31), now_utc=NOW)


def test_block_overlapping_confirmed_appointment_is_rejected(app):
    provider = make_provider()
    student = make_user("s@example.com")
    make_appointment(student, provider, ist(2030, 1, 7, 9, 30))
    with pytest.raises(AvailabilityError, match="overlaps 1 confirmed"):
        create_block(provider, MONDAY, time(9, 0), time(10, 0), now_utc=NOW)
    assert db.session.query(BlockedTime).count() == 0


def test_block_over_cancelled_appointment_is_allowed(app):
    provider = make_provider()
    student = make_user("s@example.com")
    make_appointment(
        student, provider, ist(2030, 1, 7, 9, 30), status=AppointmentStatus.CANCELLED
    )
    create_block(provider, MONDAY, time(9, 0), time(10, 0), now_utc=NOW)
    assert db.session.query(BlockedTime).count() == 1


def test_block_starting_when_an_appointment_ends_is_allowed(app):
    provider = make_provider()
    student = make_user("s@example.com")
    make_appointment(student, provider, ist(2030, 1, 7, 9, 30))  # 09:30-10:00
    create_block(provider, MONDAY, time(10, 0), time(11, 0), now_utc=NOW)
    assert db.session.query(BlockedTime).count() == 1


# ---------- provider pages ----------

def test_availability_page_access_control(client):
    provider = make_provider()
    make_user("s@example.com")

    assert client.get("/provider/availability").status_code == 302  # anonymous

    login(client, "s@example.com")
    assert client.get("/provider/availability").status_code == 403  # wrong role
    client.post("/auth/logout")

    login(client, provider.user.email)
    assert client.get("/provider/availability").status_code == 200


def test_provider_saves_schedule_through_the_form(client):
    provider = make_provider()
    login(client, provider.user.email)
    response = client.post(
        "/provider/availability/schedule",
        data={
            "slot_duration_minutes": "45",
            "days-0-enabled": "y",
            "days-0-start_time": "09:00",
            "days-0-end_time": "17:00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Availability saved" in response.data

    db.session.expire_all()
    rows = schedule_rows()
    assert [(r.day_of_week, r.start_time, r.end_time) for r in rows] == [
        (0, time(9, 0), time(17, 0))
    ]
    assert provider.slot_duration_minutes == 45


def test_schedule_form_shows_rule_error_and_saves_nothing(client):
    provider = make_provider()
    login(client, provider.user.email)
    response = client.post(
        "/provider/availability/schedule",
        data={
            "slot_duration_minutes": "30",
            "days-0-enabled": "y",
            "days-0-start_time": "17:00",
            "days-0-end_time": "09:00",
        },
    )
    assert response.status_code == 200
    assert b"end time must be after the start time" in response.data
    assert schedule_rows() == []


def test_schedule_form_requires_both_times_for_a_working_day(client):
    provider = make_provider()
    login(client, provider.user.email)
    response = client.post(
        "/provider/availability/schedule",
        data={"slot_duration_minutes": "30", "days-0-enabled": "y"},
    )
    assert response.status_code == 200
    assert b"Enter both a start and an end time" in response.data
    assert schedule_rows() == []


def test_provider_blocks_time_through_the_form(client):
    provider = make_provider()
    login(client, provider.user.email)
    response = client.post(
        "/provider/availability/blocked",
        data={
            "date": "2030-01-07",
            "start_time": "09:30",
            "end_time": "10:30",
            "reason": "Meeting",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Time blocked" in response.data

    blocks = db.session.query(BlockedTime).all()
    assert len(blocks) == 1
    assert blocks[0].start_at == ist(2030, 1, 7, 9, 30)


def test_blocking_over_a_confirmed_appointment_shows_error(client):
    provider = make_provider()
    student = make_user("s@example.com")
    make_appointment(student, provider, ist(2030, 1, 7, 9, 30))
    login(client, provider.user.email)
    response = client.post(
        "/provider/availability/blocked",
        data={"date": "2030-01-07", "start_time": "09:00", "end_time": "10:00"},
    )
    assert response.status_code == 200
    assert b"overlaps 1 confirmed appointment" in response.data
    assert db.session.query(BlockedTime).count() == 0


def test_provider_cannot_delete_another_providers_block(client):
    provider_a = make_provider("a@example.com")
    provider_b = make_provider("b@example.com")
    block = add_block(provider_b, ist(2030, 1, 7, 9, 0), ist(2030, 1, 7, 10, 0))

    login(client, provider_a.user.email)
    response = client.post(f"/provider/availability/blocked/{block.id}/delete")
    assert response.status_code == 404
    assert db.session.query(BlockedTime).count() == 1


def test_provider_can_delete_own_block(client):
    provider = make_provider()
    block = add_block(provider, ist(2030, 1, 7, 9, 0), ist(2030, 1, 7, 10, 0))

    login(client, provider.user.email)
    response = client.post(f"/provider/availability/blocked/{block.id}/delete")
    assert response.status_code == 302
    assert db.session.query(BlockedTime).count() == 0


def test_preview_shows_available_slots(client):
    provider = make_provider()
    tomorrow = local_today() + timedelta(days=1)
    add_schedule(provider, weekday=tomorrow.weekday())
    login(client, provider.user.email)
    response = client.get(f"/provider/availability/preview?date={tomorrow.isoformat()}")
    assert response.status_code == 200
    assert b"Available" in response.data


def test_preview_with_invalid_date_falls_back_to_today(client):
    provider = make_provider()
    login(client, provider.user.email)
    response = client.get("/provider/availability/preview?date=not-a-date")
    assert response.status_code == 200
    assert b"Invalid date" in response.data