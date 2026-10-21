import os

from flask import Flask

from app.cli import register_cli
from app.config import Config
from app.errors import register_error_handlers
from app.extensions import csrf, db, login_manager
from app.utils.timeutils import format_local


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is not set. Add it to your .env file.")

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "warning"

    app.add_template_filter(format_local, "local_dt")

    from app import models  # noqa: F401  (registers tables and the user_loader)

    register_cli(app)
    register_error_handlers(app)

    from app.blueprints.admin import bp as admin_bp
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.provider import bp as provider_bp
    from app.blueprints.student import bp as student_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(provider_bp)
    app.register_blueprint(admin_bp)

    return app