from flask import render_template
from flask_wtf.csrf import CSRFError

from app.extensions import db


def _render(code, title, message):
    return render_template("errors/error.html", code=code, title=title, message=message), code


def register_error_handlers(app):
    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return _render(
            400,
            "Form expired",
            "Your form session expired or was invalid. Please go back, refresh the page and try again.",
        )

    @app.errorhandler(403)
    def forbidden(error):
        return _render(403, "Access denied", "You do not have permission to view this page.")

    @app.errorhandler(404)
    def not_found(error):
        return _render(404, "Page not found", "The page you are looking for does not exist.")

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return _render(500, "Something went wrong", "An unexpected error occurred. Please try again.")