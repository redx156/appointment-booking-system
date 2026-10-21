from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from app.models.common import Role

# Where each role lands after login.
DASHBOARD_ENDPOINTS = {
    Role.STUDENT: "student.dashboard",
    Role.PROVIDER: "provider.dashboard",
    Role.ADMIN: "admin.dashboard",
}


def role_required(*roles):
    """Allow only logged-in users whose role is in `roles`.

    Anonymous users are redirected to the login page (login_required).
    Logged-in users with the wrong role receive 403 Forbidden.
    """

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator