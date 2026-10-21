from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

from app.extensions import db
from app.models import User


def strip_text(value):
    return value.strip() if value else value


def normalize_email(value):
    return value.strip().lower() if value else value


class RegistrationForm(FlaskForm):
    name = StringField(
        "Full name",
        validators=[DataRequired(), Length(min=2, max=100)],
        filters=[strip_text],
    )
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=255)],
        filters=[normalize_email],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=8, max=128, message="Password must be at least 8 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create account")

    def validate_email(self, field):
        existing = db.session.execute(
            db.select(User).filter_by(email=field.data)
        ).scalar_one_or_none()
        if existing is not None:
            raise ValidationError("This email is already registered.")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()], filters=[normalize_email])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")