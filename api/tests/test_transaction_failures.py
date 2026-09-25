"""A flush is not a durable acknowledgement of a security-sensitive request."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import AuditEvent, User, WebSession
from app.passwords import token_hash, verify_password

ORIGIN = "http://127.0.0.1:8080"


def headers(csrf: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf}


def login(client: TestClient, username: str, password: str) -> str:
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    result = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers=headers(csrf),
    )
    assert result.status_code == 200
    return result.json()["csrf_token"]


def fail_commit(monkeypatch: pytest.MonkeyPatch, *, number: int = 1) -> None:
    """Fail a single requested commit, leaving earlier rate-limit writes intact."""
    original = Session.commit
    count = 0

    def injected(db: Session) -> None:
        nonlocal count
        count += 1
        if count == number:
            raise OperationalError("COMMIT", {}, Exception("injected failure"))
        original(db)

    monkeypatch.setattr(Session, "commit", injected)


def assert_unavailable(result) -> None:
    assert result.status_code == 503
    assert result.json() == {"detail": "Database unavailable"}
    assert "set-cookie" not in result.headers


def test_failed_login_commit_never_returns_credentials(
    client, engine, account_factory, monkeypatch
) -> None:
    account_factory("member", "correct horse battery")
    preauth = client.get("/api/auth/csrf").json()["csrf_token"]
    fail_commit(monkeypatch, number=2)  # First commit persists login rate buckets.

    result = client.post(
        "/api/auth/login",
        json={"username": "member", "password": "correct horse battery"},
        headers=headers(preauth),
    )
    assert_unavailable(result)
    assert client.cookies.get("impostr_session") is None
    with Session(engine) as db:
        assert db.scalar(select(WebSession)) is None
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.login")) is None


def test_failed_password_change_commit_keeps_old_session_and_password(
    client, engine, account_factory, monkeypatch
) -> None:
    account_factory("member", "correct horse battery")
    csrf = login(client, "member", "correct horse battery")
    old_token = client.cookies.get("impostr_session")
    fail_commit(monkeypatch, number=2)  # Rate bucket, then credential change.

    result = client.post(
        "/api/auth/password",
        json={"current_password": "correct horse battery", "new_password": "new passphrase here"},
        headers=headers(csrf),
    )
    assert_unavailable(result)
    assert client.cookies.get("impostr_session") == old_token
    with Session(engine) as db:
        user = db.scalar(select(User).where(User.username == "member"))
        assert user is not None and verify_password(user.password_hash, "correct horse battery")
        session = db.get(WebSession, token_hash(old_token))
        assert session is not None and session.revoked_at is None
        changed_audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "auth.password_changed")
        )
        assert changed_audit is None


@pytest.mark.parametrize("operation", ["create", "reset", "deactivate"])
def test_failed_admin_commit_rolls_back_account_and_audit(
    client, engine, account_factory, monkeypatch, operation
) -> None:
    account_factory("admin", "correct horse battery", role="admin")
    target_id = account_factory("member", "member passphrase")
    csrf = login(client, "admin", "correct horse battery")
    if operation == "create":
        path = "/api/admin/users"
        payload = {"username": "new-member", "password": "temporary passphrase"}
    elif operation == "reset":
        path = f"/api/admin/users/{target_id}/reset-password"
        payload = {"password": "new passphrase here"}
    else:
        path = f"/api/admin/users/{target_id}/deactivate"
        payload = None

    fail_commit(monkeypatch, number=1 if operation == "deactivate" else 2)
    result = client.post(path, json=payload, headers=headers(csrf))
    assert_unavailable(result)
    with Session(engine) as db:
        member = db.get(User, target_id)
        assert member is not None and member.is_active
        assert verify_password(member.password_hash, "member passphrase")
        assert db.scalar(select(User).where(User.username == "new-member")) is None
        action = {
            "create": "admin.user_created",
            "reset": "admin.password_reset",
            "deactivate": "admin.user_deactivated",
        }[operation]
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == action)) is None
        assert db.scalar(select(AuditEvent).where(AuditEvent.target_user_id == target_id)) is None


def test_failed_logout_commit_does_not_clear_live_cookie(
    client, engine, account_factory, monkeypatch
) -> None:
    account_factory("member", "correct horse battery")
    csrf = login(client, "member", "correct horse battery")
    old_token = client.cookies.get("impostr_session")
    fail_commit(monkeypatch)
    assert_unavailable(client.post("/api/auth/logout", headers=headers(csrf)))
    assert client.cookies.get("impostr_session") == old_token
    with Session(engine) as db:
        session = db.get(WebSession, token_hash(old_token))
        assert session is not None and session.revoked_at is None
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.logout")) is None


def test_failed_csrf_rotation_does_not_issue_unusable_token(
    client, engine, account_factory, monkeypatch
) -> None:
    account_factory("member", "correct horse battery")
    login(client, "member", "correct horse battery")
    token = client.cookies.get("impostr_session")
    with Session(engine) as db:
        original_hash = db.get(WebSession, token_hash(token)).csrf_token_hash
    client.cookies.delete("impostr_csrf")
    fail_commit(monkeypatch)
    assert_unavailable(client.get("/api/auth/csrf"))
    assert client.cookies.get("impostr_csrf") is None
    with Session(engine) as db:
        assert db.get(WebSession, token_hash(token)).csrf_token_hash == original_hash


@pytest.mark.parametrize("path", ["/api/admin/users", "/api/projects", "/api/projects/{id}"])
def test_failed_privileged_read_audit_never_returns_private_data(
    client, engine, account_factory, project_factory, monkeypatch, path
) -> None:
    account_factory("admin", "correct horse battery", role="admin")
    owner_id = account_factory("member", "member passphrase")
    project_id = project_factory(owner_id, "Secret")
    login(client, "admin", "correct horse battery")
    fail_commit(monkeypatch)
    result = client.get(path.format(id=project_id))
    assert_unavailable(result)
    assert "Secret" not in result.text
    with Session(engine) as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action.like("admin.%.read"))) is None
