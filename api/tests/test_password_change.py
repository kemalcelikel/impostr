from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.main import create_app
from app.models import AuditEvent, WebSession
from app.passwords import token_hash

PUBLIC_ORIGIN = "http://127.0.0.1:8080"


def _login(client: TestClient) -> str:
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={"username": "password-owner", "password": "original passphrase"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_self_service_password_change_replaces_current_session_and_revokes_others(
    client: TestClient,
    engine,
    settings: AppSettings,
    account_factory,
) -> None:
    account_factory("password-owner", "original passphrase")
    first_csrf = _login(client)
    original_cookie_token = client.cookies.get("impostr_session")

    with TestClient(create_app(engine, settings)) as other_tab:
        _login(other_tab)
        other_cookie_token = other_tab.cookies.get("impostr_session")

        response = client.post(
            "/api/auth/password",
            json={
                "current_password": "original passphrase",
                "new_password": "updated passphrase",
            },
            headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": first_csrf},
        )
        assert response.status_code == 200
        assert response.json()["user"]["username"] == "password-owner"
        assert client.cookies.get("impostr_session") != original_cookie_token
        assert client.get("/api/auth/session").status_code == 200
        assert other_tab.get("/api/auth/session").status_code == 401

        assert other_cookie_token is not None
        with Session(engine) as db:
            revoked = db.get(WebSession, token_hash(other_cookie_token))
            assert revoked is not None and revoked.revoked_at is not None
            assert db.scalar(
                select(AuditEvent.action).where(AuditEvent.action == "auth.password_changed")
            )

        csrf = other_tab.get("/api/auth/csrf").json()["csrf_token"]
        old_password = other_tab.post(
            "/api/auth/login",
            json={"username": "password-owner", "password": "original passphrase"},
            headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
        )
        assert old_password.status_code == 401

        csrf = other_tab.get("/api/auth/csrf").json()["csrf_token"]
        new_password = other_tab.post(
            "/api/auth/login",
            json={"username": "password-owner", "password": "updated passphrase"},
            headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
        )
        assert new_password.status_code == 200
