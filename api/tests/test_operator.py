from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, User, WebSession
from app.operator import bootstrap_admin, recover_admin
from app.passwords import new_opaque_token, token_hash, verify_password


def test_offline_bootstrap_is_one_time_and_recovery_revokes_sessions(
    client: TestClient,
    engine,
) -> None:
    admin_id = bootstrap_admin(engine, "First.Admin", "initial secret phrase")
    with Session(engine) as db:
        admin = db.get(User, admin_id)
        assert admin is not None
        original_hash = admin.password_hash
        assert admin.username == "first.admin"
        assert admin.role == "admin" and admin.is_active
        assert original_hash != "initial secret phrase"
        assert verify_password(original_hash, "initial secret phrase")
        first_audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "operator.admin_bootstrap")
        )
        assert first_audit is not None
        assert first_audit.actor_kind == "operator" and first_audit.actor_user_id is None

    with pytest.raises(ValueError, match="already been completed"):
        bootstrap_admin(engine, "another-admin", "another secret phrase")

    raw_session = new_opaque_token()
    raw_csrf = new_opaque_token()
    session_token_hash = token_hash(raw_session)
    csrf_token_hash = token_hash(raw_csrf)
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
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )

    recovered_id = recover_admin(engine, "first.admin", "recovered secret phrase")
    assert recovered_id == admin_id
    with Session(engine) as db:
        recovered = db.get(User, admin_id)
        session = db.get(WebSession, session_token_hash)
        assert recovered is not None and recovered.is_active
        assert recovered.password_hash != original_hash
        assert verify_password(recovered.password_hash, "recovered secret phrase")
        assert session is not None and session.revoked_at is not None
        recovery_audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "operator.admin_recovery")
        )
        assert recovery_audit is not None
        assert recovery_audit.actor_kind == "operator"
        assert recovery_audit.actor_user_id is None
        assert "secret phrase" not in str(recovery_audit.details)

    assert client.get("/api/auth/bootstrap").status_code == 404
