from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from app.blueprints.admin import bp
from app.blueprints.admin.forms import CategoryForm, ProviderCreateForm, ProviderEditForm
from app.extensions import db
from app.models import Appointment, AppointmentCategory, ServiceProvider, User
from app.models.common import AppointmentStatus, Role, utcnow
from app.services import admin as admin_service
from app.services.admin import AdminError
from app.utils.roles import role_required

# Pages the activate/deactivate button may return to (a whitelist, never a raw URL).
RETURN_ENDPOINTS = {"users": "admin.users", "providers": "admin.providers"}


def category_choices():
    categories = db.session.execute(
        db.select(AppointmentCategory).order_by(AppointmentCategory.name)
    ).scalars().all()
    return [(c.id, c.name) for c in categories]


def get_or_404(model, object_id):
    obj = db.session.get(model, object_id)
    if obj is None:
        abort(404)
    return obj


@bp.route("/dashboard")
@role_required(Role.ADMIN)
def dashboard():
    role_counts = dict(
        db.session.execute(db.select(User.role, func.count(User.id)).group_by(User.role)).all()
    )
    status_counts = dict(
        db.session.execute(
            db.select(Appointment.status, func.count(Appointment.id)).group_by(Appointment.status)
        ).all()
    )
    stats = {
        "students": role_counts.get(Role.STUDENT, 0),
        "providers": role_counts.get(Role.PROVIDER, 0),
        "admins": role_counts.get(Role.ADMIN, 0),
        "categories": db.session.scalar(db.select(func.count(AppointmentCategory.id))),
        "confirmed": status_counts.get(AppointmentStatus.CONFIRMED, 0),
        "completed": status_counts.get(AppointmentStatus.COMPLETED, 0),
        "cancelled": status_counts.get(AppointmentStatus.CANCELLED, 0),
    }
    return render_template("admin/dashboard.html", stats=stats)


# ---------- Users ----------

@bp.route("/users")
@role_required(Role.ADMIN)
def users():
    role = request.args.get("role", "")
    query = db.select(User).order_by(User.role, User.name)
    if role in Role.ALL:
        query = query.where(User.role == role)
    else:
        role = ""
    items = db.session.execute(query).scalars().all()
    return render_template("admin/users.html", users=items, role=role)


@bp.route("/users/<int:user_id>/active", methods=["POST"])
@role_required(Role.ADMIN)
def set_active(user_id):
    user = get_or_404(User, user_id)
    active = request.form.get("active") == "1"
    try:
        admin_service.set_user_active(current_user, user, active)
    except AdminError as error:
        flash(str(error), "danger")
    else:
        flash(f"{user.name} has been {'activated' if active else 'deactivated'}.", "success")
    target = RETURN_ENDPOINTS.get(request.form.get("return_to"), "admin.users")
    return redirect(url_for(target))


# ---------- Categories ----------

@bp.route("/categories", methods=["GET", "POST"])
@role_required(Role.ADMIN)
def categories():
    form = CategoryForm()
    if form.validate_on_submit():
        try:
            admin_service.create_category(form.name.data, form.description.data)
        except AdminError as error:
            flash(str(error), "danger")
        else:
            flash("Category added.", "success")
            return redirect(url_for("admin.categories"))
    items = db.session.execute(
        db.select(AppointmentCategory).order_by(AppointmentCategory.name)
    ).scalars().all()
    return render_template("admin/categories.html", form=form, categories=items)


@bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@role_required(Role.ADMIN)
def edit_category(category_id):
    category = get_or_404(AppointmentCategory, category_id)
    form = CategoryForm(obj=category)
    if form.validate_on_submit():
        try:
            admin_service.update_category(category, form.name.data, form.description.data)
        except AdminError as error:
            flash(str(error), "danger")
        else:
            flash("Category updated.", "success")
            return redirect(url_for("admin.categories"))
    return render_template("admin/category_form.html", form=form, category=category)


@bp.route("/categories/<int:category_id>/delete", methods=["POST"])
@role_required(Role.ADMIN)
def delete_category(category_id):
    category = get_or_404(AppointmentCategory, category_id)
    try:
        admin_service.delete_category(category)
    except AdminError as error:
        flash(str(error), "danger")
    else:
        flash("Category deleted.", "info")
    return redirect(url_for("admin.categories"))


# ---------- Providers ----------

@bp.route("/providers")
@role_required(Role.ADMIN)
def providers():
    items = db.session.execute(
        db.select(ServiceProvider)
        .join(User, ServiceProvider.user_id == User.id)
        .order_by(User.name)
    ).scalars().all()
    return render_template("admin/providers.html", providers=items)


@bp.route("/providers/new", methods=["GET", "POST"])
@role_required(Role.ADMIN)
def new_provider():
    choices = category_choices()
    if not choices:
        flash("Create at least one category before adding a provider.", "warning")
        return redirect(url_for("admin.categories"))

    form = ProviderCreateForm()
    form.category_id.choices = choices
    if form.validate_on_submit():
        try:
            admin_service.create_provider(
                form.name.data,
                form.email.data,
                form.password.data,
                form.category_id.data,
                form.specialization.data,
                form.bio.data,
            )
        except AdminError as error:
            flash(str(error), "danger")
        else:
            flash("Provider account created.", "success")
            return redirect(url_for("admin.providers"))
    return render_template("admin/provider_form.html", form=form, is_new=True)


@bp.route("/providers/<int:provider_id>/edit", methods=["GET", "POST"])
@role_required(Role.ADMIN)
def edit_provider(provider_id):
    provider = get_or_404(ServiceProvider, provider_id)
    form = ProviderEditForm(obj=provider)
    form.category_id.choices = category_choices()
    if form.validate_on_submit():
        try:
            admin_service.update_provider(
                provider,
                form.name.data,
                form.category_id.data,
                form.specialization.data,
                form.bio.data,
            )
        except AdminError as error:
            flash(str(error), "danger")
        else:
            flash("Provider updated.", "success")
            return redirect(url_for("admin.providers"))
    return render_template("admin/provider_form.html", form=form, is_new=False, provider=provider)


@bp.route("/appointments")
@role_required(Role.ADMIN)
def appointments():
    status = request.args.get("status", "")
    query = db.select(Appointment)
    if status in AppointmentStatus.ALL:
        query = query.where(Appointment.status == status)
    else:
        status = ""
    items = db.session.execute(query.order_by(Appointment.start_at.desc()).limit(200)).scalars().all()
    return render_template("admin/appointments.html", items=items, status=status, now=utcnow())