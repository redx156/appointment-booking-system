from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.common import AppointmentStatus, utcnow


class Appointment(db.Model):
    """A booked interval [start_at, end_at) in UTC for one student with one provider."""

    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_appointments_interval"),
        CheckConstraint(
            "status IN ('confirmed', 'cancelled', 'completed')",
            name="ck_appointments_status",
        ),
        Index("ix_appointments_provider_start", "provider_id", "start_at"),
        Index("ix_appointments_student_start", "student_id", "start_at"),
        # Safety net: two confirmed appointments cannot start at the same moment.
        # (The one-upcoming-appointment-per-provider rule P-7 lives in the booking service.)
        Index(
            "uq_confirmed_provider_start",
            "provider_id",
            "start_at",
            unique=True,
            sqlite_where=text("status = 'confirmed'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider_id: Mapped[int] = mapped_column(ForeignKey("service_providers.id"))
    start_at: Mapped[datetime]
    end_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(default=AppointmentStatus.CONFIRMED)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    cancelled_at: Mapped[Optional[datetime]]

    student = relationship("User", back_populates="appointments")
    provider = relationship("ServiceProvider", back_populates="appointments")

    def __repr__(self) -> str:
        return f"<Appointment {self.id} {self.status} {self.start_at}>"