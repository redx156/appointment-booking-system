from urllib.parse import urlsplit

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from app.blueprints.auth import bp
from app.blueprints.auth.forms import LoginForm, RegistrationForm
from app.extensions import db
from app.models import User
from app.models.common import Role


def is_safe_redirect(target):
    """Allow only same-site relative paths (prevents open-redirect attacks)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegistrationForm()
    if form.validate_on_submit():
        # The role is set here on the server. Public registration only creates students.
        user = User(name=form.name.data, email=form.email.data, role=Role.STUDENT)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            # Two people registering the same email at the same moment.
            db.session.rollback()
            form.email.errors.append("This email is already registered.")
        else:
            flash("Account created. Please log in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.execute(
            db.select(User).filter_by(email=form.email.data)
        ).scalar_one_or_none()

        if user is None or not user.check_password(form.password.data):
            # One generic message, so attackers cannot discover which emails exist.
            flash("Invalid email or password.", "danger")
        elif not user.is_active:
            flash("This account has been deactivated. Please contact an administrator.", "warning")
        else:
            login_user(user)
            next_url = request.args.get("next")
            if is_safe_redirect(next_url):
                return redirect(next_url)
            return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))