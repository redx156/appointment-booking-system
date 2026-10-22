from datetime import time, timedelta

import click
from sqlalchemy import inspect

from app.extensions import db
from app.models import (
    Appointment,
    AppointmentCategory,
    AvailabilitySchedule,
    ServiceProvider,
    User,
)
from app.models.common import AppointmentStatus, Role, utcnow

# Development-only demo accounts (name, email, password, role).
SEED_ACCOUNTS = [
    ("Admin User", "admin@campus.edu", "Admin@12345", Role.ADMIN),
    ("Dr. Rao", "rao@campus.edu", "Provider@12345", Role.PROVIDER),
    ("Test Student", "student@campus.edu", "Student@12345", Role.STUDENT),
]


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all database tables (existing tables are left untouched)."""
        db.create_all()
        tables = sorted(inspect(db.engine).get_table_names())
        click.echo("Tables in database: " + ", ".join(tables))

    @app.cli.command("reset-db")
    def reset_db():
        """DELETE all data and recreate the tables (development only)."""
        click.confirm("This deletes ALL data. Continue?", abort=True)
        db.drop_all()
        db.create_all()
        click.echo("Database reset.")

    @app.cli.command("seed-dev")
    def seed_dev():
        """Create a sample category and demo accounts (safe to run repeatedly)."""
        category = db.session.execute(
            db.select(AppointmentCategory).filter_by(name="Academic Counseling")
        ).scalar_one_or_none()
        if category is None:
            category = AppointmentCategory(
                name="Academic Counseling",
                description="Course planning and academic guidance",
            )
            db.session.add(category)
            db.session.flush()

        for name, email, password, role in SEED_ACCOUNTS:
            user = db.session.execute(
                db.select(User).filter_by(email=email)
            ).scalar_one_or_none()
            if user is None:
                user = User(name=name, email=email, role=role)
                user.set_password(password)
                db.session.add(user)
                db.session.flush()
                click.echo(f"Created {role}: {email} / {password}")
            else:
                click.echo(f"Already exists: {email}")

            if role == Role.PROVIDER:
                profile = user.provider_profile
                if profile is None:
                    profile = ServiceProvider(
                        user_id=user.id,
                        category_id=category.id,
                        specialization="Academic advisor",
                        bio="Helps students plan courses and academic goals.",
                        slot_duration_minutes=30,
                    )
                    db.session.add(profile)
                    db.session.flush()
                if not profile.schedules:
                    for weekday in range(5):  # Monday to Friday
                        db.session.add(
                            AvailabilitySchedule(
                                provider_id=profile.id,
                                day_of_week=weekday,
                                start_time=time(9, 0),
                                end_time=time(17, 0),
                            )
                        )
                    click.echo(f"Added Mon-Fri 09:00-17:00 schedule for {email}")

        db.session.commit()
        click.echo("Done. These are development-only credentials; never use them in production.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Add sample appointments in every state for the demo accounts (run seed-dev first)."""
        student = db.session.execute(
            db.select(User).filter_by(email="student@campus.edu")
        ).scalar_one_or_none()
        provider_user = db.session.execute(
            db.select(User).filter_by(email="rao@campus.edu")
        ).scalar_one_or_none()
        if student is None or provider_user is None or provider_user.provider_profile is None:
            raise click.ClickException("Run 'flask --app run seed-dev' first.")

        if db.session.query(Appointment).count():
            click.echo("Appointments already exist; nothing added.")
            return

        provider = provider_user.provider_profile
        now = utcnow().replace(minute=0, second=0, microsecond=0)
        length = timedelta(minutes=provider.slot_duration_minutes)
        samples = [
            (now - timedelta(days=2), AppointmentStatus.CONFIRMED),   # started: awaiting completion
            (now - timedelta(days=9), AppointmentStatus.COMPLETED),
            (now - timedelta(days=5), AppointmentStatus.CANCELLED),
            (now + timedelta(days=3), AppointmentStatus.CONFIRMED),   # upcoming
        ]
        for start, status in samples:
            db.session.add(
                Appointment(
                    student_id=student.id,
                    provider_id=provider.id,
                    start_at=start,
                    end_at=start + length,
                    status=status,
                    notes="Demo appointment",
                    cancelled_at=now - timedelta(days=6)
                    if status == AppointmentStatus.CANCELLED
                    else None,
                )
            )
        db.session.commit()
        click.echo("Added 4 demo appointments (awaiting completion, completed, cancelled, upcoming).")