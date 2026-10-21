from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models import Appointment, AppointmentCategory, ServiceProvider, User
from app.models.common import AppointmentStatus, Role, utcnow


class AdminError(Exception):
    """An administrative rule was violated. The message is safe to show to the user."""


def _commit_or_fail(message: str) -> None:
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise AdminError(message)


def _category_name_taken(name: str, exclude_id: Optional[int] = None) -> bool:
    query = db.select(AppointmentCategory.id).where(
        db.func.lower(AppointmentCategory.name) == name.lower()
    )
    if exclude_id is not None:
        query = query.where(AppointmentCategory.id != exclude_id)
    return db.session.execute(query).first() is not None


# ---------- Categories ----------

def create_category(name: str, description: Optional[str] = None) -> AppointmentCategory:
    name = name.strip()
    if _category_name_taken(name):
        raise AdminError("A category with this name already exists.")
    category = AppointmentCategory(name=name, description=(description or "").strip() or None)
    db.session.add(category)
    _commit_or_fail("Could not save the category. Please try again.")
    return category


def update_category(
    category: AppointmentCategory, name: str, description: Optional[str] = None
) -> AppointmentCategory:
    name = name.strip()
    if _category_name_taken(name, exclude_id=category.id):
        raise AdminError("A category with this name already exists.")
    category.name = name
    category.description = (description or "").strip() or None
    _commit_or_fail("Could not save the category. Please try again.")
    return category


def delete_category(category: AppointmentCategory) -> None:
    in_use = len(category.providers)
    if in_use:
        raise AdminError(
            f"This category is used by {in_use} provider(s) and cannot be deleted. "
            "Move those providers to another category first."
        )
    db.session.delete(category)
    _commit_or_fail("Could not delete the category. Please try again.")


# ---------- Providers ----------

def create_provider(
    name: str,
    email: str,
    password: str,
    category_id: int,
    specialization: str,
    bio: Optional[str] = None,
) -> ServiceProvider:
    """Create the login account and the provider profile together, or neither."""
    category = db.session.get(AppointmentCategory, category_id)
    if category is None:
        raise AdminError("Please choose a valid category.")

    email = email.strip().lower()
    if db.session.execute(db.select(User.id).filter_by(email=email)).first() is not None:
        raise AdminError("This email is already registered.")

    try:
        user = User(name=name.strip(), email=email, role=Role.PROVIDER)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # assigns user.id inside the same transaction

        provider = ServiceProvider(
            user_id=user.id,
            category_id=category.id,
            specialization=specialization.strip(),
            bio=(bio or "").strip() or None,
        )
        db.session.add(provider)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise AdminError("This email is already registered.")
    except SQLAlchemyError:
        db.session.rollback()
        raise AdminError("Could not create the provider. Please try again.")
    return provider


def update_provider(
    provider: ServiceProvider,
    name: str,
    category_id: int,
    specialization: str,
    bio: Optional[str] = None,
) -> ServiceProvider:
    category = db.session.get(AppointmentCategory, category_id)
    if category is None:
        raise AdminError("Please choose a valid category.")
    provider.user.name = name.strip()
    provider.category_id = category.id
    provider.specialization = specialization.strip()
    provider.bio = (bio or "").strip() or None
    _commit_or_fail("Could not save the provider. Please try again.")
    return provider


# ---------- Accounts ----------

def set_user_active(
    actor: User, user: User, active: bool, now_utc: Optional[datetime] = None
) -> None:
    """Activate or deactivate an account.

    Rules: you cannot deactivate yourself, which also guarantees at least one
    active administrator always remains; and a provider with upcoming confirmed
    appointments cannot be deactivated (P-12).
    """
    now_utc = now_utc or utcnow()
    if user.is_active == active:
        return

    if not active:
        if user.id == actor.id:
            raise AdminError("You cannot deactivate your own account.")
        if user.role == Role.PROVIDER and user.provider_profile is not None:
            upcoming = db.session.execute(
                db.select(db.func.count(Appointment.id)).where(
                    Appointment.provider_id == user.provider_profile.id,
                    Appointment.status == AppointmentStatus.CONFIRMED,
                    Appointment.end_at > now_utc,
                )
            ).scalar_one()
            if upcoming:
                raise AdminError(
                    f"This provider has {upcoming} upcoming confirmed appointment(s). "
                    "Ask them to cancel or complete these first."
                )

    user.is_active = active
    _commit_or_fail("Could not update the account. Please try again.")