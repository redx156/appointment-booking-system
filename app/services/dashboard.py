from datetime import datetime, time, timedelta
from typing import Optional

from sqlalchemy import func

from app.extensions import db
from app.models import Appointment, AppointmentCategory, User
from app.models.common import AppointmentStatus, Role, utcnow
from app.utils.timeutils import local_today, to_utc_naive

CONFIRMED = AppointmentStatus.CONFIRMED
COMPLETED = AppointmentStatus.COMPLETED
CANCELLED = AppointmentStatus.CANCELLED


def _count(*conditions) -> int:
    return db.session.execute(
        db.select(func.count(Appointment.id)).where(*conditions)
    ).scalar_one()


def _upcoming(now):
    """Confirmed and not yet finished."""
    return (Appointment.status == CONFIRMED, Appointment.end_at > now)


def student_summary(student_id: int, now_utc: Optional[datetime] = None) -> dict:
    now = now_utc or utcnow()
    mine = Appointment.student_id == student_id
    upcoming = db.session.execute(
        db.select(Appointment).where(mine, *_upcoming(now)).order_by(Appointment.start_at).limit(5)
    ).scalars().all()
    return {
        "upcoming": upcoming,
        "next": upcoming[0] if upcoming else None,
        "upcoming_count": _count(mine, *_upcoming(now)),
        "completed_count": _count(mine, Appointment.status == COMPLETED),
        "cancelled_count": _count(mine, Appointment.status == CANCELLED),
    }


def provider_summary(provider, now_utc: Optional[datetime] = None) -> dict:
    now = now_utc or utcnow()
    mine = Appointment.provider_id == provider.id

    today = local_today(now)
    day_start = to_utc_naive(datetime.combine(today, time.min))
    day_end = to_utc_naive(datetime.combine(today + timedelta(days=1), time.min))

    upcoming = db.session.execute(
        db.select(Appointment).where(mine, *_upcoming(now)).order_by(Appointment.start_at).limit(5)
    ).scalars().all()
    awaiting = db.session.execute(
        db.select(Appointment)
        .where(mine, Appointment.status == CONFIRMED, Appointment.end_at <= now)
        .order_by(Appointment.start_at)
        .limit(5)
    ).scalars().all()

    return {
        "upcoming": upcoming,
        "awaiting": awaiting,
        "today_count": _count(
            mine, Appointment.status == CONFIRMED,
            Appointment.start_at >= day_start, Appointment.start_at < day_end,
        ),
        "upcoming_count": _count(mine, *_upcoming(now)),
        "awaiting_count": _count(mine, Appointment.status == CONFIRMED, Appointment.end_at <= now),
        "completed_count": _count(mine, Appointment.status == COMPLETED),
        "has_schedule": bool(provider.schedules),
    }


def admin_summary(now_utc: Optional[datetime] = None) -> dict:
    now = now_utc or utcnow()
    role_counts = dict(
        db.session.execute(db.select(User.role, func.count(User.id)).group_by(User.role)).all()
    )
    status_counts = dict(
        db.session.execute(
            db.select(Appointment.status, func.count(Appointment.id)).group_by(Appointment.status)
        ).all()
    )
    stats = {
        "students": role_counts.get(Role.STUDENT, 0),
        "providers": role_counts.get(Role.PROVIDER, 0),
        "admins": role_counts.get(Role.ADMIN, 0),
        "inactive": db.session.scalar(
            db.select(func.count(User.id)).where(User.is_active.is_(False))
        ),
        "categories": db.session.scalar(db.select(func.count(AppointmentCategory.id))),
        "upcoming": _count(*_upcoming(now)),
        "completed": status_counts.get(COMPLETED, 0),
        "cancelled": status_counts.get(CANCELLED, 0),
    }
    recent = db.session.execute(
        db.select(Appointment).order_by(Appointment.created_at.desc(), Appointment.id.desc()).limit(5)
    ).scalars().all()
    return {"stats": stats, "recent": recent}