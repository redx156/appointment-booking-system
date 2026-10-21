import os

from flask import Flask

from app.cli import register_cli
from app.config import Config
from app.extensions import csrf, db


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is not set. Add it to your .env file.")

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    # Flask-Login (login_manager.init_app) is added in Step 4,
    # once the user_loader exists.

    from app import models  # noqa: F401  (registers tables with SQLAlchemy)

    register_cli(app)

    from app.blueprints.main import bp as main_bp

    app.register_blueprint(main_bp)

    return app