import pytest

from app.extensions import db
from app.models import AppointmentCategory, ServiceProvider, User
from app.models.common import AppointmentStatus, Role
from app.services.admin import (
    AdminError,
    create_category,
    create_provider,
    delete_category,
    set_user_active,
    update_category,
)
from helpers import NOW, PASSWORD, ist, login, make_appointment, make_provider, make_user


def make_category(name="Career Guidance"):
    category = AppointmentCategory(name=name)
    db.session.add(category)
    db.session.commit()
    return category


def make_admin(email="admin@example.com"):
    return make_user(email, role=Role.ADMIN, name="Admin User")


# ---------- Categories (service) ----------

def test_create_category_trims_input(app):
    category = create_category("  Wellbeing  ", "  Support  ")
    assert category.name == "Wellbeing"
    assert category.description == "Support"
    assert db.session.query(AppointmentCategory).count() == 1


def test_category_name_must_be_unique_ignoring_case(app):
    create_category("Wellbeing")
    with pytest.raises(AdminError, match="already exists"):
        create_category("wellbeing")
    assert db.session.query(AppointmentCategory).count() == 1


def test_rename_category_to_existing_name_rejected(app):
    create_category("Alpha")
    beta = create_category("Beta")
    with pytest.raises(AdminError, match="already exists"):
        update_category(beta, "alpha")
    assert beta.name == "Beta"


def test_rename_category_changing_only_case_is_allowed(app):
    category = create_category("Wellbeing")
    update_category(category, "WELLBEING", "Updated")
    assert category.name == "WELLBEING"


def test_delete_unused_category(app):
    category = make_category()
    delete_category(category)
    assert db.session.query(AppointmentCategory).count() == 0


def test_delete_category_in_use_is_rejected(app):
    provider = make_provider()
    with pytest.raises(AdminError, match="cannot be deleted"):
        delete_category(provider.category)
    assert db.session.query(AppointmentCategory).count() == 1


# ---------- Providers (service) ----------

def test_create_provider_makes_account_and_profile(app):
    category = make_category()
    provider = create_provider(
        "Dr. Rao", "  RAO@Example.com ", PASSWORD, category.id, "Advisor", "Helpful bio"
    )
    user = provider.user
    assert user.email == "rao@example.com"
    assert user.role == Role.PROVIDER
    assert user.password_hash != PASSWORD
    assert user.check_password(PASSWORD)
    assert provider.slot_duration_minutes == 30
    assert provider.category_id == category.id


def test_create_provider_with_duplicate_email_creates_nothing(app):
    make_user("dup@example.com")
    category = make_category()
    users_before = db.session.query(User).count()
    with pytest.raises(AdminError, match="already registered"):
        create_provider("Dr. Dup", "dup@example.com", PASSWORD, category.id, "Advisor")
    assert db.session.query(User).count() == users_before
    assert db.session.query(ServiceProvider).count() == 0


def test_create_provider_with_unknown_category_rejected(app):
    with pytest.raises(AdminError, match="valid category"):
        create_provider("Dr. X", "x@example.com", PASSWORD, 999, "Advisor")
    assert db.session.query(User).count() == 0


# ---------- Account activation (service) ----------

def test_cannot_deactivate_own_account(app):
    admin = make_admin()
    with pytest.raises(AdminError, match="own account"):
        set_user_active(admin, admin, False)
    assert admin.is_active


def test_deactivate_and_reactivate_student(app):
    admin = make_admin()
    student = make_user("s@example.com")
    set_user_active(admin, student, False)
    assert not student.is_active
    set_user_active(admin, student, True)
    assert student.is_active


def test_cannot_deactivate_provider_with_upcoming_confirmed_appointment(app):
    admin = make_admin()
    provider = make_provider()
    student = make_user("s@example.com")
    make_appointment(student, provider, ist(2030, 1, 7, 9, 30))
    with pytest.raises(AdminError, match="upcoming confirmed"):
        set_user_active(admin, provider.user, False, now_utc=NOW)
    assert provider.user.is_active


def test_can_deactivate_provider_with_only_cancelled_or_past_appointments(app):
    admin = make_admin()
    provider = make_provider()
    s1 = make_user("s1@example.com")
    s2 = make_user("s2@example.com")
    make_appointment(s1, provider, ist(2030, 1, 7, 9, 30), status=AppointmentStatus.CANCELLED)
    make_appointment(s2, provider, ist(2029, 12, 1, 9, 0))  # confirmed but already in the past
    set_user_active(admin, provider.user, False, now_utc=NOW)
    assert not provider.user.is_active


# ---------- Pages ----------

ADMIN_PATHS = [
    "/admin/dashboard",
    "/admin/users",
    "/admin/categories",
    "/admin/providers",
    "/admin/providers/new",
]


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_admin_pages_require_admin_role(client, path):
    make_user("s@example.com")

    response = client.get(path)  # anonymous
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]

    login(client, "s@example.com")
    assert client.get(path).status_code == 403  # logged in, wrong role


def test_student_cannot_post_admin_actions(client):
    make_user("s@example.com")
    target = make_user("target@example.com")
    login(client, "s@example.com")

    response = client.post(f"/admin/users/{target.id}/active", data={"active": "0"})
    assert response.status_code == 403
    assert client.post("/admin/categories", data={"name": "Sneaky"}).status_code == 403

    db.session.expire_all()
    assert target.is_active
    assert db.session.query(AppointmentCategory).count() == 0


def test_admin_can_open_every_page(client):
    make_admin()
    make_provider("rao@example.com")
    login(client, "admin@example.com")

    for path in ADMIN_PATHS:
        assert client.get(path).status_code == 200

    assert b"Admin Dashboard" in client.get("/admin/dashboard").data
    assert b"rao@example.com" in client.get("/admin/users").data
    assert b"Dr. Rao" in client.get("/admin/providers").data


def test_user_list_role_filter(client):
    make_admin()
    make_user("stud@example.com")
    make_provider("rao@example.com")
    login(client, "admin@example.com")

    students = client.get("/admin/users?role=student").data
    assert b"stud@example.com" in students
    assert b"rao@example.com" not in students

    everything = client.get("/admin/users?role=hacker")
    assert everything.status_code == 200
    assert b"stud@example.com" in everything.data and b"rao@example.com" in everything.data


def test_admin_creates_category_through_the_form(client):
    make_admin()
    login(client, "admin@example.com")
    response = client.post(
        "/admin/categories",
        data={"name": "Wellbeing", "description": "Support"},
        follow_redirects=True,
    )
    assert b"Category added" in response.data
    assert db.session.query(AppointmentCategory).count() == 1


def test_duplicate_category_shows_error(client):
    make_admin()
    create_category("Wellbeing")
    login(client, "admin@example.com")
    response = client.post("/admin/categories", data={"name": "wellbeing"})
    assert response.status_code == 200
    assert b"already exists" in response.data
    assert db.session.query(AppointmentCategory).count() == 1


def test_admin_creates_provider_and_provider_can_log_in(client):
    make_admin()
    category = make_category()
    login(client, "admin@example.com")
    response = client.post(
        "/admin/providers/new",
        data={
            "name": "Dr. New",
            "email": "new.provider@example.com",
            "password": PASSWORD,
            "specialization": "Career advisor",
            "bio": "",
            "category_id": str(category.id),
        },
        follow_redirects=True,
    )
    assert b"Provider account created" in response.data

    client.post("/auth/logout")
    login(client, "new.provider@example.com")
    assert client.get("/provider/availability").status_code == 200


def test_new_provider_page_needs_a_category(client):
    make_admin()
    login(client, "admin@example.com")
    response = client.get("/admin/providers/new", follow_redirects=True)
    assert b"Create at least one category" in response.data


def test_deactivated_user_cannot_log_in(client):
    make_admin()
    student = make_user("stud@example.com")
    login(client, "admin@example.com")
    response = client.post(
        f"/admin/users/{student.id}/active",
        data={"active": "0", "return_to": "users"},
        follow_redirects=True,
    )
    assert b"has been deactivated" in response.data

    client.post("/auth/logout")
    response = login(client, "stud@example.com")
    assert response.status_code == 200
    assert b"deactivated" in response.data


def test_admin_cannot_deactivate_self_through_the_page(client):
    admin = make_admin()
    login(client, "admin@example.com")
    response = client.post(
        f"/admin/users/{admin.id}/active", data={"active": "0"}, follow_redirects=True
    )
    assert b"cannot deactivate your own account" in response.data
    db.session.expire_all()
    assert admin.is_active


def test_admin_edits_provider_profile(client):
    make_admin()
    provider = make_provider()
    other_category = make_category("Career Guidance")
    login(client, "admin@example.com")
    response = client.post(
        f"/admin/providers/{provider.id}/edit",
        data={
            "name": "Dr. Rao Kumar",
            "specialization": "Senior advisor",
            "bio": "Updated",
            "category_id": str(other_category.id),
        },
        follow_redirects=True,
    )
    assert b"Provider updated" in response.data
    db.session.expire_all()
    assert provider.user.name == "Dr. Rao Kumar"
    assert provider.category_id == other_category.id


def test_deleting_a_category_in_use_shows_error(client):
    make_admin()
    provider = make_provider()
    login(client, "admin@example.com")
    response = client.post(
        f"/admin/categories/{provider.category_id}/delete", follow_redirects=True
    )
    assert b"cannot be deleted" in response.data
    assert db.session.query(AppointmentCategory).count() == 1