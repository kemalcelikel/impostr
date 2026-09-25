from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import AppSettings
from app.database import database_url_from_environment
from app.main import create_app
from app.models import AuditEvent, BootstrapState, Project, RateLimitBucket, User, WebSession
from app.operator import bootstrap_admin, recover_admin
from app.passwords import hash_password, new_opaque_token, token_hash, verify_password
from app.rate_limit import consume_rate_bucket, rate_limit_key

pytestmark = pytest.mark.skipif(
    os.environ.get("IMPOSTR_TEST_POSTGRES") != "1",
    reason="requires the disposable PostgreSQL integration profile",
)


def _engine() -> Engine:
    return create_engine(
        database_url_from_environment(),
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
        poolclass=NullPool,
    )


def _login(client: TestClient, username: str, password: str) -> None:
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    public_origin = AppSettings.from_environment().public_origin
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={
            "Origin": public_origin,
            "X-CSRF-Token": csrf,
        },
    )
    assert response.status_code == 200


def test_postgres_migrated_auth_private_access_and_atomic_limits() -> None:
    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:16]
    admin_name = f"it-admin-{suffix}"
    alice_name = f"it-alice-{suffix}"
    bob_name = f"it-bob-{suffix}"
    password = "integration-only passphrase"
    now = datetime.now(UTC)
    admin = User(
        id=uuid.uuid4(),
        username=admin_name,
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    alice = User(
        id=uuid.uuid4(),
        username=alice_name,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    bob = User(
        id=uuid.uuid4(),
        username=bob_name,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    alice_project = Project(id=uuid.uuid4(), name="Integration private A", owner_user_id=alice.id)
    bob_project = Project(id=uuid.uuid4(), name="Integration private B", owner_user_id=bob.id)
    user_ids = [admin.id, alice.id, bob.id]
    project_ids = [alice_project.id, bob_project.id]
    admin_id, _, _ = user_ids
    alice_project_id, bob_project_id = project_ids

    try:
        with Session(engine) as db, db.begin():
            db.add_all([admin, alice, bob])
            db.flush()
            db.add_all([alice_project, bob_project])

        app = create_app(engine, settings)
        with TestClient(app) as alice_client:
            _login(alice_client, alice_name, password)
            assert len(alice_client.get("/api/projects").json()) == 1
            foreign = alice_client.get(f"/api/projects/{bob_project_id}")
            missing = alice_client.get(f"/api/projects/{uuid.uuid4()}")
            assert foreign.status_code == missing.status_code == 404
            assert foreign.json() == missing.json()

        with TestClient(create_app(engine, settings)) as admin_client:
            _login(admin_client, admin_name, password)
            assert len(admin_client.get("/api/projects").json()) == 2
            assert admin_client.get(f"/api/projects/{bob_project_id}").status_code == 200

        # Distinct connections contend for the same PostgreSQL key; exactly the
        # configured number of requests may pass the atomic upsert.
        def attempt() -> bool:
            with Session(engine) as db:
                decision = consume_rate_bucket(
                    db,
                    settings=settings,
                    scope=f"integration-concurrency-{suffix}",
                    subject="shared-bucket",
                    limit=7,
                    window_seconds=60,
                )
                db.commit()
                return decision.allowed

        with ThreadPoolExecutor(max_workers=16) as pool:
            outcomes = list(pool.map(lambda _index: attempt(), range(24)))
        assert sum(outcomes) == 7

        with Session(engine) as db:
            admin_events = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.actor_user_id == admin_id,
                        AuditEvent.action.in_(("admin.projects.read", "admin.project.read")),
                    )
                ).all()
            )
            assert {event.action for event in admin_events} == {
                "admin.projects.read",
                "admin.project.read",
            }
            project_list_event = next(
                event for event in admin_events if event.action == "admin.projects.read"
            )
            assert project_list_event.details is not None
            assert set(project_list_event.details["project_ids"]) == {
                str(alice_project_id),
                str(bob_project_id),
            }
    finally:
        login_keys = [
            rate_limit_key(settings, "login-username", name)
            for name in (admin_name, alice_name, bob_name)
        ]
        login_keys.append(rate_limit_key(settings, "login-ip", "testclient"))
        login_keys.append(
            rate_limit_key(settings, f"integration-concurrency-{suffix}", "shared-bucket")
        )
        with Session(engine) as db, db.begin():
            db.execute(
                delete(AuditEvent).where(
                    AuditEvent.actor_user_id.in_(user_ids)
                    | AuditEvent.target_user_id.in_(user_ids)
                    | AuditEvent.project_id.in_(project_ids)
                )
            )
            db.execute(delete(Project).where(Project.id.in_(project_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(login_keys)))
        engine.dispose()


def test_postgres_operator_bootstrap_and_recovery() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:16]
    username = f"it-bootstrap-{suffix}"
    initial_password = "initial integration passphrase"
    recovery_password = "recovered integration passphrase"
    admin_id: uuid.UUID | None = None
    initial_bootstrap_state: bool | None = None

    try:
        with Session(engine) as db:
            state = db.get(BootstrapState, 1)
            assert state is not None
            initial_bootstrap_state = state.completed
            assert not state.completed
            assert db.scalar(select(User.id).limit(1)) is None

        admin_id = bootstrap_admin(engine, username, initial_password)
        with Session(engine) as db:
            admin = db.get(User, admin_id)
            assert admin is not None and admin.is_active and admin.role == "admin"
            assert verify_password(admin.password_hash, initial_password)
            assert (
                db.scalar(
                    select(AuditEvent.id).where(AuditEvent.action == "operator.admin_bootstrap")
                )
                is not None
            )

        with pytest.raises(ValueError, match="already been completed"):
            bootstrap_admin(engine, f"another-{suffix}", "another integration passphrase")

        session_token_hash = token_hash(new_opaque_token())
        csrf_token_hash = token_hash(new_opaque_token())
        assert session_token_hash is not None and csrf_token_hash is not None
        with Session(engine) as db, db.begin():
            admin = db.get(User, admin_id)
            assert admin is not None
            admin.is_active = False
            db.add(
                WebSession(
                    token_hash=session_token_hash,
                    csrf_token_hash=csrf_token_hash,
                    user_id=admin_id,
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC),
                )
            )

        assert recover_admin(engine, username, recovery_password) == admin_id
        with Session(engine) as db:
            admin = db.get(User, admin_id)
            session = db.get(WebSession, session_token_hash)
            assert admin is not None and admin.is_active
            assert verify_password(admin.password_hash, recovery_password)
            assert session is not None and session.revoked_at is not None
            assert (
                db.scalar(
                    select(AuditEvent.id).where(AuditEvent.action == "operator.admin_recovery")
                )
                is not None
            )
    finally:
        if admin_id is not None:
            with Session(engine) as db, db.begin():
                db.execute(
                    delete(AuditEvent).where(
                        (AuditEvent.actor_user_id == admin_id)
                        | (AuditEvent.target_user_id == admin_id)
                    )
                )
                db.execute(delete(WebSession).where(WebSession.user_id == admin_id))
                db.execute(delete(User).where(User.id == admin_id))
                state = db.get(BootstrapState, 1)
                if state is not None and initial_bootstrap_state is not None:
                    state.completed = initial_bootstrap_state
                    state.completed_at = None
        engine.dispose()


def test_postgres_login_rechecks_password_after_waiting_for_user_lock(monkeypatch) -> None:
    """A login verified before an admin reset must not issue an old-password session."""
    from app import auth as auth_module

    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:16]
    admin_name = f"it-reset-admin-{suffix}"
    target_name = f"it-reset-user-{suffix}"
    admin_password = "admin race passphrase"
    old_password = "old race passphrase"
    new_password = "new race passphrase"
    now = datetime.now(UTC)
    admin = User(
        id=uuid.uuid4(),
        username=admin_name,
        password_hash=hash_password(admin_password),
        role="admin",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    target = User(
        id=uuid.uuid4(),
        username=target_name,
        password_hash=hash_password(old_password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    admin_id = admin.id
    target_id = target.id
    user_ids = [admin_id, target_id]
    verified_old_password = Event()
    release_login = Event()
    original_verify_password = auth_module.verify_password

    def pause_after_old_password_verification(password_hash: str, password: str) -> bool:
        matches = original_verify_password(password_hash, password)
        if password == old_password and matches:
            verified_old_password.set()
            if not release_login.wait(timeout=20):
                raise TimeoutError("Timed out waiting to resume the concurrent login")
        return matches

    try:
        with Session(engine) as db, db.begin():
            db.add_all([admin, target])

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            admin_client = TestClient(create_app(engine, settings))
            with admin_client:
                _login(admin_client, admin_name, admin_password)
                admin_csrf = admin_client.cookies.get("impostr_csrf")
                assert admin_csrf is not None

                monkeypatch.setattr(
                    auth_module,
                    "verify_password",
                    pause_after_old_password_verification,
                )

                def attempt_old_password_login() -> tuple[int, str | None]:
                    with TestClient(create_app(engine, settings)) as login_client:
                        csrf_response = login_client.get("/api/auth/csrf")
                        response = login_client.post(
                            "/api/auth/login",
                            json={"username": target_name, "password": old_password},
                            headers={
                                "Origin": settings.public_origin,
                                "X-CSRF-Token": csrf_response.json()["csrf_token"],
                            },
                        )
                        return response.status_code, login_client.cookies.get("impostr_session")

                login_future = pool.submit(attempt_old_password_login)
                assert verified_old_password.wait(timeout=10), "login did not reach password verify"
                reset = admin_client.post(
                    f"/api/admin/users/{target_id}/reset-password",
                    json={"password": new_password},
                    headers={
                        "Origin": settings.public_origin,
                        "X-CSRF-Token": admin_csrf,
                    },
                )
                assert reset.status_code == 204
                release_login.set()
                login_status, session_cookie = login_future.result(timeout=20)

            assert login_status == 401
            assert session_cookie is None
        finally:
            release_login.set()
            pool.shutdown(wait=True, cancel_futures=True)

        with Session(engine) as db:
            account = db.get(User, target_id)
            assert account is not None and verify_password(account.password_hash, new_password)
            assert (
                db.scalar(select(WebSession.token_hash).where(WebSession.user_id == target_id))
                is None
            )

        with TestClient(create_app(engine, settings)) as fresh_client:
            csrf_response = fresh_client.get("/api/auth/csrf")
            old_login = fresh_client.post(
                "/api/auth/login",
                json={"username": target_name, "password": old_password},
                headers={
                    "Origin": settings.public_origin,
                    "X-CSRF-Token": csrf_response.json()["csrf_token"],
                },
            )
            assert old_login.status_code == 401

            csrf_response = fresh_client.get("/api/auth/csrf")
            new_login = fresh_client.post(
                "/api/auth/login",
                json={"username": target_name, "password": new_password},
                headers={
                    "Origin": settings.public_origin,
                    "X-CSRF-Token": csrf_response.json()["csrf_token"],
                },
            )
            assert new_login.status_code == 200
    finally:
        release_login.set()
        login_keys = [
            rate_limit_key(settings, "login-username", admin_name),
            rate_limit_key(settings, "login-username", target_name),
            rate_limit_key(settings, "login-ip", "testclient"),
            rate_limit_key(settings, "admin-credential-change", f"{admin_id}:testclient"),
        ]
        with Session(engine) as db, db.begin():
            db.execute(
                delete(AuditEvent).where(
                    (AuditEvent.actor_user_id.in_(user_ids))
                    | (AuditEvent.target_user_id.in_(user_ids))
                )
            )
            db.execute(delete(WebSession).where(WebSession.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(login_keys)))
        engine.dispose()
