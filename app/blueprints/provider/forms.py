from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    FieldList,
    Form,
    FormField,
    SelectField,
    StringField,
    SubmitField,
    TimeField,
)
from wtforms.validators import DataRequired, Length, Optional

DURATION_CHOICES = [
    (10, "10 minutes"),
    (15, "15 minutes"),
    (20, "20 minutes"),
    (30, "30 minutes"),
    (45, "45 minutes"),
    (60, "60 minutes"),
    (90, "90 minutes"),
    (120, "120 minutes"),
]


class DayForm(Form):
    """One weekday row. A plain WTForms Form, so it carries no CSRF token of its own."""

    enabled = BooleanField("Working")
    start_time = TimeField("Start", format="%H:%M", validators=[Optional()])
    end_time = TimeField("End", format="%H:%M", validators=[Optional()])


class ScheduleForm(FlaskForm):
    slot_duration_minutes = SelectField(
        "Appointment length", coerce=int, choices=DURATION_CHOICES
    )
    days = FieldList(FormField(DayForm), min_entries=7, max_entries=7)
    save = SubmitField("Save schedule")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators)
        for entry in self.days:
            day = entry.form
            if day.enabled.data and (day.start_time.data is None or day.end_time.data is None):
                day.end_time.errors = list(day.end_time.errors) + [
                    "Enter both a start and an end time."
                ]
                valid = False
        return valid


class BlockedTimeForm(FlaskForm):
    date = DateField("Date", validators=[DataRequired()])
    start_time = TimeField("From (optional)", format="%H:%M", validators=[Optional()])
    end_time = TimeField("To (optional)", format="%H:%M", validators=[Optional()])
    reason = StringField("Reason (optional)", validators=[Optional(), Length(max=255)])
    block = SubmitField("Block this time")