from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional

from app.blueprints.auth.forms import normalize_email, strip_text


class CategoryForm(FlaskForm):
    name = StringField(
        "Category name",
        validators=[DataRequired(), Length(min=2, max=100)],
        filters=[strip_text],
    )
    description = StringField(
        "Description (optional)", validators=[Optional(), Length(max=255)], filters=[strip_text]
    )
    submit = SubmitField("Save category")


class ProviderEditForm(FlaskForm):
    name = StringField(
        "Full name", validators=[DataRequired(), Length(min=2, max=100)], filters=[strip_text]
    )
    category_id = SelectField("Category", coerce=int, choices=[])
    specialization = StringField(
        "Specialization", validators=[DataRequired(), Length(min=2, max=120)], filters=[strip_text]
    )
    bio = TextAreaField("Bio (optional)", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Save changes")


class ProviderCreateForm(ProviderEditForm):
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=255)],
        filters=[normalize_email],
    )
    password = PasswordField(
        "Initial password",
        validators=[DataRequired(), Length(min=8, max=128, message="Password must be at least 8 characters.")],
    )
    submit = SubmitField("Create provider")