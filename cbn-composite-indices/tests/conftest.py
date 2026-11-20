import pytest

from app import create_app
from app.config import Config
from app.extensions import db


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    CELERY = {
        **Config.CELERY,
        "task_always_eager": True,
        "task_eager_propagates": True,
    }


@pytest.fixture
def app(tmp_path):
    config = type(
        "TmpTestConfig",
        (TestConfig,),
        {
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "RESULT_FOLDER": str(tmp_path / "results"),
        },
    )
    app = create_app(config)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
