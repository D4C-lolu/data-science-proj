from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from celery import Celery, Task

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
login_manager.login_message_category = "info"


class FlaskContextTask(Task):
    """Run Celery tasks inside a shared Flask application context."""

    abstract = True

    def __call__(self, *args, **kwargs):
        app = get_flask_app()
        with app.app_context():
            return self.run(*args, **kwargs)


celery = Celery("app", task_cls=FlaskContextTask)

_flask_app = None


def get_flask_app():
    """Return a process-wide Flask app, creating it on first use."""
    global _flask_app
    if _flask_app is None:
        from app import create_app

        _flask_app = create_app()
    return _flask_app
