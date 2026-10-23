"""Offline operator-only initial administrator bootstrap and recovery actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.models import BootstrapState, User, WebSession
from app.passwords import hash_password, normalize_username, validate_new_password
from app.rate_limit import utc_now


def _bootstrap_state(db: Session, *, for_update: bool) -> BootstrapState:
    statement = select(BootstrapState).where(BootstrapState.id == 1)
    if for_update:
        statement = statement.with_for_update()
    state = db.scalar(statement)
    if state is None:
        raise ValueError("Bootstrap state is missing; apply database migrations first")
    return state


def bootstrap_admin(engine: Engine, username: str, password: str) -> uuid.UUID:
    """Create the first and only operator-bootstrapped admin, once per database."""
    normalized_username = normalize_username(username)
    validate_new_password(password)
    with Session(engine, expire_on_commit=False) as db, db.begin():
        state = _bootstrap_state(db, for_update=True)
        if state.completed:
            raise ValueError("Administrator bootstrap has already been completed")
        user_count = db.scalar(select(func.count()).select_from(User))
        if user_count:
            raise ValueError("Bootstrap requires an empty users table")

        now = utc_now()
        user = User(
            id=uuid.uuid4(),
            username=normalized_username,
            password_hash=hash_password(password),
            role="admin",
            is_active=True,
            created_at=now,
            password_changed_at=now,
        )
        db.add(user)
        db.flush()
        state.completed = True
        state.completed_at = now
        record_audit(
            db,
            action="operator.admin_bootstrap",
            actor_kind="operator",
            actor_user_id=None,
            target_user_id=user.id,
        )
        db.flush()
        return user.id


def recover_admin(engine: Engine, username: str, password: str) -> uuid.UUID:
    """Reset and re-enable an existing admin without exposing a network route."""
    normalized_username = normalize_username(username)
    validate_new_password(password)
    with Session(engine, expire_on_commit=False) as db, db.begin():
        state = _bootstrap_state(db, for_update=True)
        if not state.completed:
            raise ValueError("Administrator bootstrap has not been completed")
        user = db.scalar(
            select(User)
            .where(User.username == normalized_username, User.role == "admin")
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if user is None:
            raise ValueError("No administrator account matches that username")

        now: datetime = datetime.now(UTC)
        user.password_hash = hash_password(password)
        user.password_changed_at = now
        user.is_active = True
        db.execute(
            update(WebSession)
            .where(WebSession.user_id == user.id, WebSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        record_audit(
            db,
            action="operator.admin_recovery",
            actor_kind="operator",
            actor_user_id=None,
            target_user_id=user.id,
        )
        db.flush()
        return user.id
