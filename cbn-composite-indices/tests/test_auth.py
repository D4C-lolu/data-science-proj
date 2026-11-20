from app.extensions import db
from app.models import User


def test_signup_creates_user_and_signs_them_in(client, app):
    response = client.post(
        "/auth/signup",
        data={
            "email": "Analyst@example.com",
            "username": "analyst_1",
            "password": "secure-password-1",
            "confirm_password": "secure-password-1",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with app.app_context():
        user = db.session.query(User).one()
        assert user.email == "analyst@example.com"
        assert user.username == "analyst_1"
        assert user.check_password("secure-password-1")
        assert user.password_hash != "secure-password-1"

    assert client.get("/").status_code == 302


def test_signup_rejects_mismatched_passwords(client):
    response = client.post(
        "/auth/signup",
        data={
            "email": "analyst@example.com",
            "username": "analyst",
            "password": "secure-password-1",
            "confirm_password": "different-password",
        },
    )

    assert response.status_code == 400
    assert b"Passwords do not match" in response.data


def test_signup_rejects_duplicate_email_or_username(client):
    client.post(
        "/auth/signup",
        data={
            "email": "analyst@example.com",
            "username": "analyst",
            "password": "secure-password-1",
            "confirm_password": "secure-password-1",
        },
    )
    client.post("/auth/logout")

    response = client.post(
        "/auth/signup",
        data={
            "email": "ANALYST@example.com",
            "username": "another-user",
            "password": "secure-password-1",
            "confirm_password": "secure-password-1",
        },
    )

    assert response.status_code == 400
    assert b"already registered" in response.data


def test_login_accepts_username_or_email_and_logout(client):
    client.post(
        "/auth/signup",
        data={
            "email": "analyst@example.com",
            "username": "analyst",
            "password": "secure-password-1",
            "confirm_password": "secure-password-1",
        },
    )
    client.post("/auth/logout")

    response = client.post(
        "/auth/login",
        data={"identity": "ANALYST", "password": "secure-password-1"},
    )
    assert response.status_code == 302
    assert client.get("/").status_code == 302
    assert client.get("/indices/").status_code == 200

    client.post("/auth/logout")
    assert client.get("/").status_code == 302


def test_login_rejects_invalid_credentials(client):
    response = client.post(
        "/auth/login",
        data={"identity": "nobody", "password": "not-the-password"},
    )

    assert response.status_code == 400
    assert b"Check your email or username and password" in response.data


def test_next_redirect_must_be_local(client):
    client.post(
        "/auth/signup",
        data={
            "email": "analyst@example.com",
            "username": "analyst",
            "password": "secure-password-1",
            "confirm_password": "secure-password-1",
        },
    )
    client.post("/auth/logout")

    response = client.post(
        "/auth/login",
        data={
            "identity": "analyst@example.com",
            "password": "secure-password-1",
            "next": "https://evil.example/steal-session",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
