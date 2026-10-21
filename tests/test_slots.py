from datetime import date, time, timedelta

from app.models.common import AppointmentStatus
from app.services.slots import (
    REASON_BLOCKED,
    REASON_BOOKED,
    REASON_PAST,
    REASON_TOO_FAR,
    available_dates,
    generate_slots,
)
from helpers import (
    MONDAY,
    NOW,
    add_block,
    add_schedule,
    ist,
    make_appointment,
    make_provider,
    make_user,
)


def reasons(slots):
    """Map local 'HH:MM' to the reason it is unavailable (None means available)."""
    return {s.local_start.strftime("%H:%M"): s.reason for s in slots}


def test_generates_slots_within_working_hours(app):
    provider = make_provider()
    add_schedule(provider)  # Monday 09:00-11:00, 30-minute slots
    slots = generate_slots(provider, MONDAY, NOW)
    assert reasons(slots) == {"09:00": None, "09:30": None, "10:00": None, "10:30": None}
    assert slots[0].start_at == ist(2030, 1, 7, 9, 0)
    assert slots[-1].local_end.strftime("%H:%M") == "11:00"


def test_no_slots_on_a_non_working_day(app):
    provider = make_provider()
    add_schedule(provider)  # Monday only
    assert generate_slots(provider, date(2030, 1, 8), NOW) == []  # Tuesday


def test_slot_must_end_inside_working_hours(app):
    provider = make_provider()
    add_schedule(provider, end=time(10, 15))  # 10:00-10:30 would run past 10:15
    assert list(reasons(generate_slots(provider, MONDAY, NOW))) == ["09:00", "09:30"]


def test_slot_duration_is_respected(app):
    provider = make_provider(duration=45)
    add_schedule(provider)  # 09:00-11:00 holds two 45-minute slots, not three
    assert list(reasons(generate_slots(provider, MONDAY, NOW))) == ["09:00", "09:45"]


def test_past_slots_are_unavailable(app):
    provider = make_provider()
    add_schedule(provider)
    now = ist(2030, 1, 7, 9, 45)
    assert reasons(generate_slots(provider, MONDAY, now)) == {
        "09:00": REASON_PAST,
        "09:30": REASON_PAST,
        "10:00": None,
        "10:30": None,
    }


def test_slot_starting_exactly_now_is_unavailable(app):
    provider = make_provider()
    add_schedule(provider)
    now = ist(2030, 1, 7, 9, 0)
    assert reasons(generate_slots(provider, MONDAY, now))["09:00"] == REASON_PAST
    assert reasons(generate_slots(provider, MONDAY, now))["09:30"] is None


def test_booked_slot_is_unavailable(app):
    provider = make_provider()
    add_schedule(provider)
    student = make_user("s@example.com")
    make_appointment(student, provider, ist(2030, 1, 7, 9, 30))
    assert reasons(generate_slots(provider, MONDAY, NOW)) == {
        "09:00": None,
        "09:30": REASON_BOOKED,
        "10:00": None,
        "10:30": None,
    }


def test_cancelled_appointment_frees_its_slot(app):
    provider = make_provider()
    add_schedule(provider)
    student = make_user("s@example.com")
    make_appointment(
        student, provider, ist(2030, 1, 7, 9, 30), status=AppointmentStatus.CANCELLED
    )
    assert all(s.available for s in generate_slots(provider, MONDAY, NOW))


def test_partially_overlapping_appointment_blocks_both_slots(app):
    provider = make_provider()
    add_schedule(provider)
    student = make_user("s@example.com")
    make_appointment(student, provider, ist(2030, 1, 7, 9, 15))  # 09:15-09:45
    assert reasons(generate_slots(provider, MONDAY, NOW)) == {
        "09:00": REASON_BOOKED,
        "09:30": REASON_BOOKED,
        "10:00": None,
        "10:30": None,
    }


def test_adjacent_appointment_does_not_block_next_slot(app):
    provider = make_provider()
    add_schedule(provider)
    student = make_user("s@example.com")
    make_appointment(student, provider, ist(2030, 1, 7, 9, 0))  # ends exactly at 09:30
    result = reasons(generate_slots(provider, MONDAY, NOW))
    assert result["09:00"] == REASON_BOOKED
    assert result["09:30"] is None


def test_blocked_time_makes_slots_unavailable(app):
    provider = make_provider()
    add_schedule(provider)
    add_block(provider, ist(2030, 1, 7, 9, 30), ist(2030, 1, 7, 10, 30))
    assert reasons(generate_slots(provider, MONDAY, NOW)) == {
        "09:00": None,
        "09:30": REASON_BLOCKED,
        "10:00": REASON_BLOCKED,
        "10:30": None,
    }


def test_booking_horizon_boundary(app):
    provider = make_provider()
    add_schedule(provider, weekday=3)  # Thursday 2030-01-31 = NOW + 30 days
    add_schedule(provider, weekday=4)  # Friday   2030-02-01 = NOW + 31 days
    inside = generate_slots(provider, date(2030, 1, 31), NOW)
    outside = generate_slots(provider, date(2030, 2, 1), NOW)
    assert inside and all(s.available for s in inside)
    assert outside and {s.reason for s in outside} == {REASON_TOO_FAR}


def test_available_dates_lists_working_days_within_horizon(app):
    provider = make_provider()
    add_schedule(provider)  # Mondays
    assert available_dates(provider, NOW) == [
        date(2030, 1, 7),
        date(2030, 1, 14),
        date(2030, 1, 21),
        date(2030, 1, 28),
    ]


def test_fully_booked_day_is_not_available(app):
    provider = make_provider()
    add_schedule(provider)
    for i in range(4):  # one student per slot (a student may hold only one active booking)
        student = make_user(f"s{i}@example.com")
        make_appointment(student, provider, ist(2030, 1, 7, 9, 0) + timedelta(minutes=30 * i))
    assert date(2030, 1, 7) not in available_dates(provider, NOW)
    assert date(2030, 1, 14) in available_dates(provider, NOW)