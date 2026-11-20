from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from flask_wtf import FlaskForm
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Regexp

from app.extensions import db
from app.models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


class SignupForm(FlaskForm):
    email = StringField("Email address", validators=[DataRequired(), Email(), Length(max=255)])
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(min=3, max=80),
            Regexp(r"^[A-Za-z0-9_.-]+$", message="Use letters, numbers, dots, underscores, or hyphens."),
        ],
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField("Confirm password", validators=[DataRequired()])
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    identity = StringField("Email or username", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Sign in")


class LogoutForm(FlaskForm):
    submit = SubmitField("Sign out")


def _safe_next_url(target):
    if not target:
        return None
    host_url = urlparse(request.host_url)
    target_url = urlparse(urljoin(request.host_url, target))
    if target_url.scheme in {"http", "https"} and host_url.netloc == target_url.netloc:
        return target
    return None


@auth_bp.get("/signup")
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template("auth/signup.html", form=SignupForm())


@auth_bp.post("/signup")
def create_account():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    form = SignupForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        username = form.username.data.strip().lower()
        if form.password.data != form.confirm_password.data:
            form.confirm_password.errors.append("Passwords do not match.")
        else:
            existing = db.session.scalar(
                select(User.id).where(
                    or_(func.lower(User.email) == email, func.lower(User.username) == username.lower())
                )
            )
            if existing:
                form.email.errors.append("That email or username is already registered.")
            else:
                user = User(email=email, username=username)
                user.set_password(form.password.data)
                db.session.add(user)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    form.email.errors.append("That email or username is already registered.")
                else:
                    login_user(user)
                    flash("Your account is ready. Welcome to the workspace.", "success")
                    return redirect(url_for("index"))

    return render_template("auth/signup.html", form=form), 400


@auth_bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template("auth/login.html", form=LoginForm(), next=request.args.get("next", ""))


@auth_bp.post("/login")
def sign_in():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    form = LoginForm()
    next_url = request.form.get("next", "")
    if form.validate_on_submit():
        identity = form.identity.data.strip()
        user = db.session.scalar(
            select(User).where(
                or_(func.lower(User.email) == identity.lower(), func.lower(User.username) == identity.lower())
            )
        )
        if user is not None and user.check_password(form.password.data):
            login_user(user, remember=False)
            flash("You are signed in.", "success")
            return redirect(_safe_next_url(next_url) or url_for("index"))
        form.identity.errors.append("Check your email or username and password, then try again.")

    return render_template("auth/login.html", form=form, next=next_url), 400


@auth_bp.post("/logout")
def sign_out():
    form = LogoutForm()
    if form.validate_on_submit():
        logout_user()
        flash("You have signed out.", "success")
    return redirect(url_for("auth.login"))
