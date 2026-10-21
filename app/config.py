import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # Secrets come from the environment, never from source code.
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # A relative sqlite path is placed inside the instance/ folder by Flask-SQLAlchemy.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///app.db")

    # Business policy constants (see the Booking Policy and Scope Sheet).
    APP_TIMEZONE = "Asia/Kolkata"           # P-5
    CANCELLATION_DEADLINE_HOURS = 12        # P-3
    BOOKING_HORIZON_DAYS = 30               # P-6