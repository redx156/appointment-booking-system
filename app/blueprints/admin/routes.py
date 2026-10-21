from flask import render_template

from app.blueprints.admin import bp
from app.models.common import Role
from app.utils.roles import role_required


@bp.route("/dashboard")
@role_required(Role.ADMIN)
def dashboard():
    return render_template("dashboard_placeholder.html", title="Admin Dashboard")