import pytest

from app.extensions import db
from app.models import User
from app.models.common import Role

from helpers import make_provider

PASSWORD = "Password123"


def create_user(email, role=Role.STUDENT, active=True, name="Test User"):
    user = User(name=name, email=email, role=role, is_active=active)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email, password=PASSWORD, **kwargs):
    return client.post("/auth/login", data={"email": email, "password": password}, **kwargs)


def register(client, **overrides):
    data = {
        "name": "New Student",
        "email": "new@example.com",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
    }
    data.update(overrides)
    return client.post("/auth/register", data=data)


def find_user(email):
    return db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()


# ---------- Registration ----------

def test_registration_creates_student_with_hashed_password(client):
    response = register(client)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]

    user = find_user("new@example.com")
    assert user.role == Role.STUDENT
    assert user.password_hash != PASSWORD


def test_registration_ignores_role_field(client):
    register(client, email="sneaky@example.com", role="admin")
    assert find_user("sneaky@example.com").role == Role.STUDENT


def test_duplicate_registration_rejected(client):
    create_user("dup@example.com")
    response = register(client, email="dup@example.com")
    assert response.status_code == 200
    assert b"already registered" in response.data
    assert db.session.query(User).count() == 1


def test_password_mismatch_rejected(client):
    response = register(client, confirm_password="Different123")
    assert response.status_code == 200
    assert b"Passwords must match" in response.data
    assert find_user("new@example.com") is None


def test_short_password_rejected(client):
    response = register(client, password="short", confirm_password="short")
    assert response.status_code == 200
    assert b"at least 8" in response.data
    assert find_user("new@example.com") is None


# ---------- Login ----------

def test_login_success_reaches_dashboard(client):
    create_user("s@example.com")
    response = login(client, "s@example.com", follow_redirects=True)
    assert response.status_code == 200
    assert b"Student Dashboard" in response.data


def test_login_wrong_password_shows_generic_error(client):
    create_user("s@example.com")
    response = login(client, "s@example.com", password="WrongPassword1")
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_login_unknown_email_shows_same_error(client):
    response = login(client, "nobody@example.com")
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_inactive_user_cannot_log_in(client):
    create_user("off@example.com", active=False)
    response = login(client, "off@example.com")
    assert response.status_code == 200
    assert b"deactivated" in response.data
    assert client.get("/student/dashboard").status_code == 302


def test_login_ignores_external_next_url(client):
    create_user("s@example.com")
    response = client.post(
        "/auth/login?next=https://evil.example.org",
        data={"email": "s@example.com", "password": PASSWORD},
    )
    assert response.status_code == 302
    assert "evil" not in response.headers["Location"]


def test_login_follows_safe_next_url(client):
    create_user("s@example.com")
    response = client.post(
        "/auth/login?next=/student/dashboard",
        data={"email": "s@example.com", "password": PASSWORD},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student/dashboard")


# ---------- Authorization ----------

def test_anonymous_user_redirected_to_login(client):
    response = client.get("/student/dashboard")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_student_cannot_access_other_roles(client):
    create_user("s@example.com")
    login(client, "s@example.com")
    assert client.get("/student/dashboard").status_code == 200
    assert client.get("/provider/dashboard").status_code == 403
    assert client.get("/admin/dashboard").status_code == 403


@pytest.mark.parametrize(
    "role, path, text",
    [
        (Role.PROVIDER, "/provider/dashboard", b"Provider Dashboard"),
        (Role.ADMIN, "/admin/dashboard", b"Admin Dashboard"),
    ],
)
def test_provider_and_admin_reach_own_dashboards(client, role, path, text):
    if role == Role.PROVIDER:
        make_provider("staff@example.com")  # creates the account and its provider profile
    else:
        create_user("staff@example.com", role=role)
    login(client, "staff@example.com")
    response = client.get(path)
    assert response.status_code == 200
    assert text in response.data


# ---------- Sessions ----------

def test_logout_requires_post_and_ends_session(client):
    create_user("s@example.com")
    login(client, "s@example.com")

    assert client.get("/auth/logout").status_code == 405

    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert client.get("/student/dashboard").status_code == 302


def test_deactivated_user_session_ends(client):
    user = create_user("gone@example.com")
    login(client, "gone@example.com")
    assert client.get("/student/dashboard").status_code == 200

    user.is_active = False
    db.session.commit()

    response = client.get("/student/dashboard")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]