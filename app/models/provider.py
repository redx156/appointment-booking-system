from datetime import datetime, time
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class AppointmentCategory(db.Model):
    __tablename__ = "appointment_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))

    providers = relationship("ServiceProvider", back_populates="category")

    def __repr__(self) -> str:
        return f"<AppointmentCategory {self.name}>"


class ServiceProvider(db.Model):
    __tablename__ = "service_providers"
    __table_args__ = (
        CheckConstraint(
            "slot_duration_minutes BETWEEN 10 AND 120",
            name="ck_providers_slot_duration",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("appointment_categories.id"))
    specialization: Mapped[str] = mapped_column(String(120))
    bio: Mapped[Optional[str]] = mapped_column(Text)
    slot_duration_minutes: Mapped[int] = mapped_column(default=30)

    user = relationship("User", back_populates="provider_profile")
    category = relationship("AppointmentCategory", back_populates="providers")
    schedules = relationship(
        "AvailabilitySchedule", back_populates="provider", cascade="all, delete-orphan"
    )
    blocked_times = relationship(
        "BlockedTime", back_populates="provider", cascade="all, delete-orphan"
    )
    appointments = relationship("Appointment", back_populates="provider")

    @property
    def name(self) -> str:
        return self.user.name

    def __repr__(self) -> str:
        return f"<ServiceProvider {self.id}>"


class AvailabilitySchedule(db.Model):
    """One weekly working window per provider per weekday (0 = Monday ... 6 = Sunday)."""

    __tablename__ = "availability_schedules"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_schedule_day"),
        CheckConstraint("end_time > start_time", name="ck_schedule_times"),
        UniqueConstraint("provider_id", "day_of_week", name="uq_schedule_provider_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("service_providers.id"))
    day_of_week: Mapped[int]
    start_time: Mapped[time]
    end_time: Mapped[time]

    provider = relationship("ServiceProvider", back_populates="schedules")


class BlockedTime(db.Model):
    """A period (stored in UTC) when the provider is unavailable."""

    __tablename__ = "blocked_times"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_blocked_interval"),
        Index("ix_blocked_provider_start", "provider_id", "start_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("service_providers.id"))
    start_at: Mapped[datetime]
    end_at: Mapped[datetime]
    reason: Mapped[Optional[str]] = mapped_column(String(255))

    provider = relationship("ServiceProvider", back_populates="blocked_times")