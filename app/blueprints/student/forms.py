from flask_wtf import FlaskForm
from wtforms import HiddenField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class BookingForm(FlaskForm):
    start = HiddenField(validators=[DataRequired()])
    notes = TextAreaField(
        "Anything the provider should know? (optional)",
        validators=[Optional(), Length(max=500)],
    )
    submit = SubmitField("Confirm booking")