"""Administrator-only account provisioning and credential controls."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.auth import UserView, user_view
from app.dependencies import (
    AdminActor,
    DbSession,
    SettingsDependency,
    load_active_actor,
    lock_active_admins,
)
from app.models import User, WebSession
from app.passwords import (
    PasswordHashCapacityError,
    hash_password,
    normalize_username,
    validate_new_password,
)
from app.rate_limit import consume_rate_bucket, utc_now

router = APIRouter(prefix="/admin", tags=["admin"])


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=127)
    password: SecretStr
    role: Literal["admin", "user"] = "user"

    @field_validator("username", mode="before")
    @classmethod
    def normalize_account_name(cls, value: object) -> object:
        return normalize_username(value) if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_account_password(cls, value: SecretStr) -> SecretStr:
        validate_new_password(value.get_secret_value())
        return value


class PasswordResetRequest(BaseModel):
    password: SecretStr

    @field_validator("password")
    @classmethod
    def validate_reset_password(cls, value: SecretStr) -> SecretStr:
        validate_new_password(value.get_secret_value())
        return value


def _admin_rate_limit(
    db: Session,
    *,
    settings: SettingsDependency,
    actor: AdminActor,
    request: Request,
) -> None:
    client_ip = request.client.host if request.client is not None else "unknown"
    decision = consume_rate_bucket(
        db,
        settings=settings,
        scope="admin-credential-change",
        subject=f"{actor.id}:{client_ip}",
        limit=15,
        window_seconds=10 * 60,
    )
    db.commit()
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many credential changes. Try again later.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def _password_hash(password: str) -> str:
    try:
        return hash_password(password)
    except PasswordHashCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password service is temporarily busy",
            headers={"Retry-After": "1"},
        ) from exc


def _locked_admin_actor(db: Session, actor: AdminActor) -> User:
    lock_active_admins(db)
    current_actor = load_active_actor(db, actor)
    if current_actor.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return current_actor


@router.get("/users", response_model=list[UserView])
def list_users(
    db: DbSession,
    actor: AdminActor,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> list[UserView]:
    current_actor = load_active_actor(db, actor)
    if current_actor.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    users = list(db.scalars(select(User).order_by(User.username).offset(offset).limit(limit)).all())
    record_audit(
        db,
        action="admin.users.read",
        actor_user_id=current_actor.id,
        details={
            "limit": limit,
            "offset": offset,
            "returned": len(users),
            "user_ids": [str(user.id) for user in users],
        },
    )
    db.commit()
    return [user_view(user) for user in users]


@router.post("/users", response_model=UserView, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    db: DbSession,
    settings: SettingsDependency,
    actor: AdminActor,
) -> UserView:
    _admin_rate_limit(db, settings=settings, actor=actor, request=request)
    if db.scalar(select(User.id).where(User.username == payload.username)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that username already exists",
        )

    password_hash = _password_hash(payload.password.get_secret_value())
    current_actor = _locked_admin_actor(db, actor)
    user = User(
        id=uuid.uuid4(),
        username=payload.username,
        password_hash=password_hash,
        role=payload.role,
        is_active=True,
        created_at=utc_now(),
        password_changed_at=utc_now(),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that username already exists",
        ) from exc

    record_audit(
        db,
        action="admin.user_created",
        actor_user_id=current_actor.id,
        target_user_id=user.id,
        details={"role": payload.role},
    )
    db.commit()
    return user_view(user)


@router.post("/users/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(
    user_id: uuid.UUID,
    db: DbSession,
    actor: AdminActor,
) -> Response:
    active_admins = lock_active_admins(db)
    current_actor = load_active_actor(db, actor)
    if current_actor.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    target = db.scalar(
        select(User)
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )
    if not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account is already inactive",
        )
    if target.role == "admin" and len(active_admins) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="At least one active administrator must remain",
        )
    if user_id == current_actor.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot deactivate your own account",
        )

    now = utc_now()
    target.is_active = False
    db.execute(
        update(WebSession)
        .where(WebSession.user_id == target.id, WebSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    record_audit(
        db,
        action="admin.user_deactivated",
        actor_user_id=current_actor.id,
        target_user_id=target.id,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: uuid.UUID,
    payload: PasswordResetRequest,
    request: Request,
    db: DbSession,
    settings: SettingsDependency,
    actor: AdminActor,
) -> Response:
    _admin_rate_limit(db, settings=settings, actor=actor, request=request)
    if db.scalar(select(User.id).where(User.id == user_id)) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )
    password_hash = _password_hash(payload.password.get_secret_value())

    current_actor = _locked_admin_actor(db, actor)
    target = db.scalar(
        select(User)
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    now: datetime = datetime.now(UTC)
    target.password_hash = password_hash
    target.password_changed_at = now
    db.execute(
        update(WebSession)
        .where(WebSession.user_id == target.id, WebSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    record_audit(
        db,
        action="admin.password_reset",
        actor_user_id=current_actor.id,
        target_user_id=target.id,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
