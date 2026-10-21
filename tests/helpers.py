from datetime import date, datetime, time, timedelta

from app.extensions import db
from app.models import (
    Appointment,
    AppointmentCategory,
    AvailabilitySchedule,
    BlockedTime,
    ServiceProvider,
    User,
)
from app.models.common import AppointmentStatus, Role

PASSWORD = "Password123"
NOW = datetime(2030, 1, 1, 0, 0)  # the "current time" (naive UTC) for service tests
MONDAY = date(2030, 1, 7)         # a Monday inside the booking horizon of NOW
IST_OFFSET = timedelta(hours=5, minutes=30)


def ist(year, month, day, hour=0, minute=0):
    """Naive UTC datetime for a wall-clock time in IST.

    Deliberately computed by hand (not with the app's own converter),
    so the tests check the production code independently.
    """
    return datetime(year, month, day, hour, minute) - IST_OFFSET


def make_user(email, role=Role.STUDENT, name="Test User"):
    user = User(name=name, email=email, role=role)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def make_provider(email="rao@example.com", duration=30):
    user = make_user(email, role=Role.PROVIDER, name="Dr. Rao")
    category = db.session.execute(
        db.select(AppointmentCategory).filter_by(name="Academic Counseling")
    ).scalar_one_or_none()
    if category is None:
        category = AppointmentCategory(name="Academic Counseling")
        db.session.add(category)
        db.session.commit()
    provider = ServiceProvider(
        user_id=user.id,
        category_id=category.id,
        specialization="Academic advisor",
        slot_duration_minutes=duration,
    )
    db.session.add(provider)
    db.session.commit()
    return provider


def add_schedule(provider, weekday=0, start=time(9, 0), end=time(11, 0)):
    row = AvailabilitySchedule(
        provider_id=provider.id, day_of_week=weekday, start_time=start, end_time=end
    )
    db.session.add(row)
    db.session.commit()
    return row


def make_appointment(student, provider, start_at, minutes=30, status=AppointmentStatus.CONFIRMED):
    appointment = Appointment(
        student_id=student.id,
        provider_id=provider.id,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=minutes),
        status=status,
    )
    db.session.add(appointment)
    db.session.commit()
    return appointment


def add_block(provider, start_at, end_at, reason=None):
    block = BlockedTime(provider_id=provider.id, start_at=start_at, end_at=end_at, reason=reason)
    db.session.add(block)
    db.session.commit()
    return block


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", data={"email": email, "password": password})