from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.main import create_app
from app.models import AuditEvent, User, WebSession
from app.passwords import token_hash

PUBLIC_ORIGIN = "http://127.0.0.1:8080"


def _csrf(client: TestClient) -> str:
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _sign_in(client: TestClient, username: str, password: str) -> str:
    csrf = _csrf(client)
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _mutation_headers(csrf: str) -> dict[str, str]:
    return {"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf}


def test_admin_create_reset_and_deactivate_revoke_sessions_and_audit(
    client: TestClient,
    engine,
    settings: AppSettings,
    account_factory,
) -> None:
    admin_id = account_factory("admin", "correct horse battery", role="admin")
    admin_csrf = _sign_in(client, "admin", "correct horse battery")

    listing = client.get("/api/admin/users")
    assert listing.status_code == 200
    assert [entry["username"] for entry in listing.json()] == ["admin"]

    create = client.post(
        "/api/admin/users",
        json={
            "username": "new.member",
            "password": "temporary passphrase",
            "role": "user",
        },
        headers=_mutation_headers(admin_csrf),
    )
    assert create.status_code == 201
    created = create.json()
    assert created["username"] == "new.member"
    assert created["role"] == "user"
    assert "password" not in create.text and "password_hash" not in create.text

    with TestClient(create_app(engine, settings)) as new_user_client:
        user_csrf = _sign_in(new_user_client, "new.member", "temporary passphrase")
        original_token = new_user_client.cookies.get("impostr_session")
        assert new_user_client.get("/api/auth/session").status_code == 200

        reset = client.post(
            f"/api/admin/users/{created['id']}/reset-password",
            json={"password": "replacement passphrase"},
            headers=_mutation_headers(admin_csrf),
        )
        assert reset.status_code == 204
        assert new_user_client.get("/api/auth/session").status_code == 401
        with Session(engine) as db:
            session = db.get(WebSession, token_hash(original_token))
            assert session is not None and session.revoked_at is not None

        changed_password = new_user_client.post(
            "/api/auth/login",
            json={"username": "new.member", "password": "replacement passphrase"},
            headers={
                "Origin": PUBLIC_ORIGIN,
                "X-CSRF-Token": _csrf(new_user_client),
            },
        )
        assert changed_password.status_code == 200
        user_csrf = changed_password.json()["csrf_token"]

        deactivate = client.post(
            f"/api/admin/users/{created['id']}/deactivate",
            headers=_mutation_headers(admin_csrf),
        )
        assert deactivate.status_code == 204
        assert new_user_client.get("/api/auth/session").status_code == 401
        denied_login = new_user_client.post(
            "/api/auth/login",
            json={"username": "new.member", "password": "replacement passphrase"},
            headers={
                "Origin": PUBLIC_ORIGIN,
                "X-CSRF-Token": _csrf(new_user_client),
            },
        )
        assert denied_login.status_code == 401
        assert user_csrf != admin_csrf

    with Session(engine) as db:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action.in_(
                        (
                            "admin.users.read",
                            "admin.user_created",
                            "admin.password_reset",
                            "admin.user_deactivated",
                        )
                    )
                )
            ).all()
        )
        assert {event.action for event in events} == {
            "admin.users.read",
            "admin.user_created",
            "admin.password_reset",
            "admin.user_deactivated",
        }
        assert all(event.actor_user_id == admin_id for event in events)
        assert all(event.target_user_id in {None, uuid.UUID(created["id"])} for event in events)
        assert all("passphrase" not in str(event.details) for event in events)
        read_event = next(event for event in events if event.action == "admin.users.read")
        assert read_event.details is not None
        assert read_event.details["user_ids"] == [str(admin_id)]


def test_non_admin_cannot_list_or_provision_users(
    client: TestClient,
    engine,
    settings: AppSettings,
    account_factory,
) -> None:
    account_factory("ordinary-user", "correct horse battery")
    target_id = account_factory("target-user", "target passphrase")
    csrf = _sign_in(client, "ordinary-user", "correct horse battery")

    with TestClient(create_app(engine, settings)) as target_client:
        _sign_in(target_client, "target-user", "target passphrase")
        target_session = target_client.cookies.get("impostr_session")
        listing = client.get("/api/admin/users")
        create = client.post(
            "/api/admin/users",
            json={"username": "forbidden-user", "password": "temporary passphrase"},
            headers=_mutation_headers(csrf),
        )
        reset = client.post(
            f"/api/admin/users/{target_id}/reset-password",
            json={"password": "forbidden passphrase"},
            headers=_mutation_headers(csrf),
        )
        deactivate = client.post(
            f"/api/admin/users/{target_id}/deactivate",
            headers=_mutation_headers(csrf),
        )
        assert [r.status_code for r in (listing, create, reset, deactivate)] == [403] * 4
        assert target_client.get("/api/auth/session").status_code == 200
    with Session(engine) as db:
        assert db.scalar(select(User.id).where(User.username == "forbidden-user")) is None
        target = db.get(User, target_id)
        assert target is not None and target.is_active
        session = db.get(WebSession, token_hash(target_session))
        assert session is not None and session.revoked_at is None
        assert db.scalar(select(AuditEvent).where(AuditEvent.target_user_id == target_id)) is None


def test_admin_cannot_remove_the_only_active_admin(
    client: TestClient,
    account_factory,
) -> None:
    admin_id = account_factory("only-admin", "correct horse battery", role="admin")
    csrf = _sign_in(client, "only-admin", "correct horse battery")

    response = client.post(
        f"/api/admin/users/{admin_id}/deactivate",
        headers=_mutation_headers(csrf),
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "At least one active administrator must remain"}
    assert client.get("/api/auth/session").status_code == 200
