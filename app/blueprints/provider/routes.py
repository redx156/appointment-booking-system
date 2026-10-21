from flask import render_template

from app.blueprints.provider import bp
from app.models.common import Role
from app.utils.roles import role_required


@bp.route("/dashboard")
@role_required(Role.PROVIDER)
def dashboard():
    return render_template("dashboard_placeholder.html", title="Provider Dashboard")