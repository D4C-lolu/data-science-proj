"""Celery application entry point for the worker process.

Run the worker with::

    celery -A celery_app.celery worker --loglevel=info

The Flask application factory configures the shared Celery instance's broker
and result backend from ``config.CELERY``.
"""

from app import create_app
from app.extensions import celery

create_app()
celery.set_default()

# Import tasks so the worker registers them against this Celery instance.
from app import tasks  # noqa: E402,F401