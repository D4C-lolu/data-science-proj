from pathlib import Path

from flask import Flask, jsonify, redirect, url_for
from flask_login import current_user

from app.config import Config
from app.extensions import celery, csrf, db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    app.config.from_pyfile("config.py", silent=True)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["RESULT_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to access your workspace."
    csrf.init_app(app)

    # Configure Celery so both the web app (.delay) and the worker share settings.
    celery.config_from_object(app.config["CELERY"])

    # Register model mappings and the Flask-Login user loader.
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    from app.auth import auth_bp

    app.register_blueprint(auth_bp)

    from app.indices import indices_bp

    app.register_blueprint(indices_bp)

    @app.get("/")
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return redirect(url_for("indices.landing"))

    @app.get("/health")
    def health():
        return jsonify(status="ok"), 200

    return app
