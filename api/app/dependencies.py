"""Trusted request dependencies for database, CSRF, and session authorization."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.database import get_database_engine
from app.models import User, WebSession
from app.passwords import csrf_hash_matches, token_hash
from app.rate_limit import utc_now
from app.security import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME


def get_settings(request: Request) -> AppSettings:
    settings = cast(AppSettings | None, request.app.state.settings)
    if settings is None:
        raise RuntimeError("Application security settings were not initialized")
    return settings


def get_db(request: Request) -> Iterator[Session]:
    engine = request.app.state.database_engine or get_database_engine()
    db = Session(engine, expire_on_commit=False)
    try:
        yield db
    finally:
        # FastAPI tears down yield dependencies after response headers can be sent.
        # Endpoints must commit before returning data/cookies; never commit here.
        try:
            db.rollback()
        finally:
            db.close()


DbSession = Annotated[Session, Depends(get_db)]
SettingsDependency = Annotated[AppSettings, Depends(get_settings)]


def require_browser_mutation(request: Request, settings: SettingsDependency) -> None:
    """Enforce exact Origin and double-submit CSRF on every unsafe API method."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return

    if request.headers.get("origin") != settings.public_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed",
        )

    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
    csrf_header = request.headers.get("x-csrf-token", "")
    if (
        not csrf_cookie
        or not csrf_header
        or len(csrf_header) > 128
        or not csrf_hash_matches(csrf_header, csrf_hash(csrf_cookie))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )


def csrf_hash(token: str) -> bytes:
    candidate_hash = token_hash(token)
    return candidate_hash if candidate_hash is not None else b""


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    id: uuid.UUID
    username: str
    role: str
    created_at: datetime
    session_token_hash: bytes
    csrf_token_hash: bytes


def _authenticated_user_statement(
    actor: AuthenticatedActor,
    *,
    now: datetime,
) -> Select[User]:
    return (
        select(User)
        .join(WebSession, WebSession.user_id == User.id)
        .where(
            User.id == actor.id,
            User.is_active.is_(True),
            WebSession.token_hash == actor.session_token_hash,
            WebSession.revoked_at.is_(None),
            WebSession.expires_at > now,
        )
        .execution_options(populate_existing=True)
    )


def get_current_actor(request: Request, db: DbSession) -> AuthenticatedActor:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    hashed_token = token_hash(raw_token)
    if hashed_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    row = db.execute(
        select(User, WebSession.csrf_token_hash)
        .join(WebSession, WebSession.user_id == User.id)
        .where(
            WebSession.token_hash == hashed_token,
            WebSession.revoked_at.is_(None),
            WebSession.expires_at > utc_now(),
            User.is_active.is_(True),
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user, csrf_token_hash = row
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied_csrf = request.headers.get("x-csrf-token", "")
        if not csrf_hash_matches(supplied_csrf, csrf_token_hash):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token",
            )

    return AuthenticatedActor(
        id=user.id,
        username=user.username,
        role=user.role,
        created_at=user.created_at,
        session_token_hash=hashed_token,
        csrf_token_hash=csrf_token_hash,
    )


CurrentActor = Annotated[AuthenticatedActor, Depends(get_current_actor)]


def require_admin(actor: CurrentActor) -> AuthenticatedActor:
    if actor.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return actor


AdminActor = Annotated[AuthenticatedActor, Depends(require_admin)]


def load_active_actor(
    db: Session,
    actor: AuthenticatedActor,
    *,
    now: datetime | None = None,
    for_update: bool = False,
) -> User:
    current_time = now or datetime.now(UTC)
    statement = _authenticated_user_statement(actor, now=current_time)
    if for_update:
        statement = statement.with_for_update(of=User)
    user = db.scalar(statement)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def lock_active_admins(db: Session) -> list[User]:
    """Serialize admin mutations and last-admin checks in a stable lock order."""
    return list(
        db.scalars(
            select(User)
            .where(User.role == "admin", User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        ).all()
    )
