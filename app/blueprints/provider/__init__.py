from flask import Blueprint

bp = Blueprint("provider", __name__, url_prefix="/provider")

from app.blueprints.provider import routes  # noqa: E402,F401