import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "local-development-key-change-before-deploying")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://indices:indices-dev-password@localhost:5432/indices",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "data/uploads")
    RESULT_FOLDER = os.environ.get("RESULT_FOLDER", "data/results")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 50 * 1024 * 1024))
    ALLOWED_UPLOAD_EXTENSIONS = {"csv", "xlsx", "xls"}

    CELERY = {
        "broker_url": os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        "result_backend": os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        "task_track_started": True,
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        "timezone": "UTC",
        "enable_utc": True,
    }

    LOGIN_VIEW = "auth.login"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
