from datetime import timedelta

from app.extensions import db
from app.models import Appointment
from app.models.common import AppointmentStatus, Role, utcnow
from app.services.dashboard import admin_summary, provider_summary, student_summary
from helpers import (
    NOW,
    add_schedule,
    future_slot_start,
    ist,
    login,
    make_appointment,
    make_provider,
    make_user,
    provider_open_every_day,
)

CONFIRMED = AppointmentStatus.CONFIRMED
COMPLETED = AppointmentStatus.COMPLETED
CANCELLED = AppointmentStatus.CANCELLED


def seed_states(provider, student):
    """NOW is 2030-01-01 05:30 IST. One appointment in each interesting state."""
    make_appointment(student, provider, ist(2029, 12, 31, 9, 0))                    # awaiting completion
    make_appointment(student, provider, ist(2030, 1, 1, 15, 0))                     # today, upcoming
    make_appointment(student, provider, ist(2030, 1, 7, 9, 0))                      # later, upcoming
    make_appointment(student, provider, ist(2029, 12, 20, 9, 0), status=COMPLETED)
    make_appointment(student, provider, ist(2030, 1, 3, 9, 0), status=CANCELLED)


# ---------- Summaries (service) ----------

def test_student_summary_counts(app):
    provider = make_provider()
    student = make_user("s@example.com")
    seed_states(provider, student)

    summary = student_summary(student.id, NOW)
    assert summary["upcoming_count"] == 2
    assert summary["completed_count"] == 1
    assert summary["cancelled_count"] == 1
    assert summary["next"].start_at == ist(2030, 1, 1, 15, 0)
    assert len(summary["upcoming"]) == 2


def test_student_summary_is_private_to_the_student(app):
    provider = make_provider()
    student = make_user("s@example.com")
    other = make_user("other@example.com")
    seed_states(provider, student)

    summary = student_summary(other.id, NOW)
    assert summary["upcoming_count"] == 0
    assert summary["next"] is None


def test_provider_summary_counts(app):
    provider = make_provider()
    student = make_user("s@example.com")
    seed_states(provider, student)

    summary = provider_summary(provider, NOW)
    assert summary["today_count"] == 1
    assert summary["upcoming_count"] == 2
    assert summary["awaiting_count"] == 1
    assert summary["completed_count"] == 1
    assert summary["has_schedule"] is False

    add_schedule(provider)
    db.session.refresh(provider)
    assert provider_summary(provider, NOW)["has_schedule"] is True


def test_admin_summary_counts(app):
    provider = make_provider()
    student = make_user("s@example.com")
    inactive = make_user("gone@example.com")
    inactive.is_active = False
    db.session.commit()
    seed_states(provider, student)

    summary = admin_summary(NOW)
    stats = summary["stats"]
    assert stats["students"] == 2
    assert stats["providers"] == 1
    assert stats["inactive"] == 1
    assert stats["upcoming"] == 2
    assert stats["completed"] == 1
    assert stats["cancelled"] == 1
    assert len(summary["recent"]) == 5


# ---------- Dashboard pages ----------

def test_student_dashboard_page(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    login(client, "s@example.com")

    empty = client.get("/student/dashboard").data
    assert b"Student Dashboard" in empty
    assert b"No upcoming appointments" in empty

    make_appointment(student, provider, future_slot_start(provider, 3, 0))
    make_appointment(student, provider, utcnow() - timedelta(days=3), status=COMPLETED)
    page = client.get("/student/dashboard").data
    assert b"Next appointment" in page
    assert b"Dr. Rao" in page


def test_provider_dashboard_warns_when_no_schedule_and_shows_awaiting(client):
    provider = make_provider()
    student = make_user("s@example.com")
    make_appointment(student, provider, utcnow() - timedelta(hours=3))
    login(client, provider.user.email)

    page = client.get("/provider/dashboard").data
    assert b"Provider Dashboard" in page
    assert b"not set your working hours" in page
    assert b"awaiting completion" in page
    assert b"Mark completed" in page


def test_provider_dashboard_without_alerts_when_set_up(client):
    provider = provider_open_every_day()
    login(client, provider.user.email)
    page = client.get("/provider/dashboard").data
    assert b"not set your working hours" not in page
    assert b"No upcoming appointments" in page


def test_admin_dashboard_page(client):
    provider = provider_open_every_day()
    student = make_user("s@example.com")
    make_user("admin@example.com", role=Role.ADMIN)
    make_appointment(student, provider, future_slot_start(provider, 3, 0))
    login(client, "admin@example.com")

    page = client.get("/admin/dashboard").data
    assert b"Admin Dashboard" in page
    assert b"Recent bookings" in page
    assert b"Dr. Rao" in page


# ---------- Demo data command ----------

def test_seed_commands_create_demo_data_once(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed-dev"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(args=["seed-demo"])
    assert result.exit_code == 0, result.output
    assert db.session.query(Appointment).count() == 4

    again = runner.invoke(args=["seed-demo"])
    assert again.exit_code == 0
    assert "already exist" in again.output
    assert db.session.query(Appointment).count() == 4