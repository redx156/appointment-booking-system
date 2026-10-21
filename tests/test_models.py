from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Appointment, AppointmentCategory, ServiceProvider, User
from app.models.common import AppointmentStatus, Role

START = datetime(2030, 1, 7, 4, 30)  # naive UTC


def make_user(email, role=Role.STUDENT, name="Test User"):
    user = User(name=name, email=email, role=role)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    return user


def make_provider(email="rao@example.com"):
    user = make_user(email, role=Role.PROVIDER, name="Dr. Rao")
    category = AppointmentCategory(name="Academic Counseling")
    db.session.add(category)
    db.session.commit()
    provider = ServiceProvider(
        user_id=user.id, category_id=category.id, specialization="Academic advisor"
    )
    db.session.add(provider)
    db.session.commit()
    return provider


def make_appointment(student, provider, start=START, minutes=30,
                     status=AppointmentStatus.CONFIRMED):
    return Appointment(
        student_id=student.id,
        provider_id=provider.id,
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        status=status,
    )


def test_password_is_hashed_and_verifiable(app):
    user = make_user("a@example.com")
    assert user.password_hash != "password123"
    assert user.check_password("password123") is True
    assert user.check_password("wrong-password") is False


def test_duplicate_email_rejected(app):
    make_user("same@example.com")
    with pytest.raises(IntegrityError):
        make_user("same@example.com")
    db.session.rollback()


def test_appointment_end_must_be_after_start(app):
    student = make_user("s@example.com")
    provider = make_provider()
    bad = make_appointment(student, provider, minutes=-30)
    db.session.add(bad)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_two_confirmed_appointments_cannot_share_provider_start(app):
    provider = make_provider()
    s1 = make_user("s1@example.com")
    s2 = make_user("s2@example.com")
    db.session.add(make_appointment(s1, provider))
    db.session.commit()

    db.session.add(make_appointment(s2, provider))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_cancelled_appointment_frees_the_slot(app):
    provider = make_provider()
    s1 = make_user("s1@example.com")
    s2 = make_user("s2@example.com")
    db.session.add(make_appointment(s1, provider, status=AppointmentStatus.CANCELLED))
    db.session.commit()

    db.session.add(make_appointment(s2, provider))
    db.session.commit()  # must succeed
    assert db.session.query(Appointment).count() == 2


def test_student_has_one_confirmed_appointment_per_provider(app):
    provider = make_provider()
    student = make_user("s@example.com")
    db.session.add(make_appointment(student, provider, start=START))
    db.session.commit()

    db.session.add(make_appointment(student, provider, start=START + timedelta(hours=2)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_foreign_keys_are_enforced(app):
    orphan = Appointment(
        student_id=999,
        provider_id=999,
        start_at=START,
        end_at=START + timedelta(minutes=30),
    )
    db.session.add(orphan)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()