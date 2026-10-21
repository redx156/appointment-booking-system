from datetime import datetime, timezone


class Role:
    STUDENT = "student"
    PROVIDER = "provider"
    ADMIN = "admin"
    ALL = (STUDENT, PROVIDER, ADMIN)


class AppointmentStatus:
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ALL = (CONFIRMED, CANCELLED, COMPLETED)


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (SQLite stores no timezone; see policy P-5)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)