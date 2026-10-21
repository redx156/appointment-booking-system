import click
from sqlalchemy import inspect

from app.extensions import db
from app.models import AppointmentCategory, ServiceProvider, User
from app.models.common import Role

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

            if role == Role.PROVIDER and user.provider_profile is None:
                db.session.add(
                    ServiceProvider(
                        user_id=user.id,
                        category_id=category.id,
                        specialization="Academic advisor",
                        bio="Helps students plan courses and academic goals.",
                        slot_duration_minutes=30,
                    )
                )

        db.session.commit()
        click.echo("Done. These are development-only credentials; never use them in production.")