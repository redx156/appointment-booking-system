from flask import redirect, render_template, url_for
from flask_login import current_user, login_required

from app.blueprints.main import bp
from app.utils.roles import DASHBOARD_ENDPOINTS


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    return redirect(url_for(DASHBOARD_ENDPOINTS[current_user.role]))