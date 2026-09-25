"""Login, session lifecycle, and account-owned password change endpoints."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.config import AppSettings
from app.dependencies import (
    CurrentActor,
    DbSession,
    SettingsDependency,
    load_active_actor,
)
from app.models import User, WebSession
from app.passwords import (
    PasswordHashCapacityError,
    csrf_hash_matches,
    dummy_password_hash,
    hash_password,
    new_opaque_token,
    normalize_username,
    token_hash,
    validate_new_password,
    verify_password,
)
from app.rate_limit import consume_rate_bucket, utc_now
from app.security import (
    CSRF_COOKIE_NAME,
    PREAUTH_CSRF_TTL_SECONDS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class UserView(BaseModel):
    id: uuid.UUID
    username: str
    role: Literal["admin", "user"]
    is_active: bool
    created_at: datetime


class CsrfPayload(BaseModel):
    csrf_token: str


class SessionPayload(BaseModel):
    user: UserView


class SessionTokenPayload(SessionPayload):
    csrf_token: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=127)
    password: SecretStr

    @field_validator("username", mode="before")
    @classmethod
    def normalize_login_name(cls, value: object) -> object:
        return normalize_username(value) if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def bound_login_password(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw or len(raw) > 256 or len(raw.encode("utf-8")) > 1024:
            raise ValueError("Password is invalid")
        return value


class PasswordChangeRequest(BaseModel):
    current_password: SecretStr
    new_password: SecretStr

    @field_validator("current_password")
    @classmethod
    def bound_current_password(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw or len(raw) > 256 or len(raw.encode("utf-8")) > 1024:
            raise ValueError("Password is invalid")
        return value

    @field_validator("new_password")
    @classmethod
    def validate_new_password_field(cls, value: SecretStr) -> SecretStr:
        validate_new_password(value.get_secret_value())
        return value


def user_view(user: User) -> UserView:
    created_at = user.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return UserView(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        created_at=created_at,
    )


def set_session_cookies(
    response: Response,
    *,
    settings: AppSettings,
    session_token: str,
    csrf_token: str,
) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        path="/",
        secure=settings.secure_cookies,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=False,
        path="/",
        secure=settings.secure_cookies,
        samesite="strict",
    )


def clear_session_cookies(response: Response, settings: AppSettings) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        httponly=True,
        path="/",
        secure=settings.secure_cookies,
        samesite="strict",
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        httponly=False,
        path="/",
        secure=settings.secure_cookies,
        samesite="strict",
    )


def _set_csrf_cookie(
    response: Response,
    *,
    token: str,
    settings: AppSettings,
    max_age: int,
) -> None:
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=False,
        path="/",
        secure=settings.secure_cookies,
        samesite="strict",
    )


def _active_session_for_cookie(db: Session, request: Request) -> WebSession | None:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    hashed_token = token_hash(raw_token)
    if hashed_token is None:
        return None
    return db.scalar(
        select(WebSession)
        .join(User, User.id == WebSession.user_id)
        .where(
            WebSession.token_hash == hashed_token,
            WebSession.revoked_at.is_(None),
            WebSession.expires_at > utc_now(),
            User.is_active.is_(True),
        )
    )


@router.get("/csrf", response_model=CsrfPayload)
def issue_csrf_token(
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDependency,
) -> CsrfPayload:
    """Issue pre-login CSRF or restore the token bound to the current session."""
    session = _active_session_for_cookie(db, request)
    if session is not None:
        csrf_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        if not csrf_hash_matches(csrf_token, session.csrf_token_hash):
            csrf_token = new_opaque_token()
            csrf_token_hash = token_hash(csrf_token)
            if csrf_token_hash is None:
                raise RuntimeError("Could not create CSRF token")
            session.csrf_token_hash = csrf_token_hash
            db.commit()
        _set_csrf_cookie(
            response,
            token=csrf_token,
            settings=settings,
            max_age=SESSION_TTL_SECONDS,
        )
        return CsrfPayload(csrf_token=csrf_token)

    if request.cookies.get(SESSION_COOKIE_NAME):
        response.delete_cookie(
            SESSION_COOKIE_NAME,
            httponly=True,
            path="/",
            secure=settings.secure_cookies,
            samesite="strict",
        )
    csrf_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    if token_hash(csrf_token) is None:
        csrf_token = new_opaque_token()
    _set_csrf_cookie(
        response,
        token=csrf_token,
        settings=settings,
        max_age=PREAUTH_CSRF_TTL_SECONDS,
    )
    return CsrfPayload(csrf_token=csrf_token)


def _consume_login_rate_limits(
    db: Session,
    *,
    settings: AppSettings,
    username: str,
    request: Request,
) -> int | None:
    client_ip = request.client.host if request.client is not None else "unknown"
    decisions = (
        consume_rate_bucket(
            db,
            settings=settings,
            scope="login-ip",
            subject=client_ip,
            limit=50,
            window_seconds=15 * 60,
        ),
        consume_rate_bucket(
            db,
            settings=settings,
            scope="login-username",
            subject=username,
            limit=10,
            window_seconds=15 * 60,
        ),
    )
    db.commit()
    blocked = [decision.retry_after_seconds for decision in decisions if not decision.allowed]
    return max(blocked) if blocked else None


def _rate_limit_exception(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


def _hash_capacity_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Password service is temporarily busy",
        headers={"Retry-After": "1"},
    )


@router.post("/login", response_model=SessionTokenPayload)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDependency,
) -> SessionTokenPayload:
    normalized_username = normalize_username(payload.username)
    retry_after = _consume_login_rate_limits(
        db,
        settings=settings,
        username=normalized_username,
        request=request,
    )
    if retry_after is not None:
        raise _rate_limit_exception(retry_after)

    user = db.scalar(select(User).where(User.username == normalized_username))
    password = payload.password.get_secret_value()
    try:
        verified_password_hash = (
            user.password_hash if user is not None and user.is_active else dummy_password_hash()
        )
        password_matches = verify_password(verified_password_hash, password)
    except PasswordHashCapacityError as exc:
        raise _hash_capacity_exception() from exc

    if user is None or not user.is_active or not password_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    verified_user_id = user.id
    user = db.scalar(
        select(User)
        .where(User.id == verified_user_id)
        .execution_options(populate_existing=True)
        .with_for_update(of=User)
    )
    if (
        user is None
        or not user.is_active
        or not hmac.compare_digest(user.password_hash, verified_password_hash)
    ):
        # Credential changes lock this same row. Recheck after taking the lock so
        # a password verified before a reset/change cannot create a fresh session.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    old_token_hash = token_hash(request.cookies.get(SESSION_COOKIE_NAME, ""))
    if old_token_hash is not None:
        old_session = db.get(WebSession, old_token_hash)
        if old_session is not None and old_session.revoked_at is None:
            old_session.revoked_at = utc_now()

    session_token = new_opaque_token()
    csrf_token = new_opaque_token()
    hashed_session_token = token_hash(session_token)
    hashed_csrf_token = token_hash(csrf_token)
    if hashed_session_token is None or hashed_csrf_token is None:
        raise RuntimeError("Could not create session tokens")

    now = utc_now()
    db.add(
        WebSession(
            token_hash=hashed_session_token,
            csrf_token_hash=hashed_csrf_token,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
        )
    )
    record_audit(db, action="auth.login", actor_user_id=user.id)
    db.commit()
    set_session_cookies(
        response,
        settings=settings,
        session_token=session_token,
        csrf_token=csrf_token,
    )
    return SessionTokenPayload(user=user_view(user), csrf_token=csrf_token)


@router.get("/session", response_model=SessionPayload)
def current_session(db: DbSession, actor: CurrentActor) -> SessionPayload:
    user = load_active_actor(db, actor)
    return SessionPayload(user=user_view(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: DbSession,
    actor: CurrentActor,
    settings: SettingsDependency,
) -> Response:
    session = db.get(WebSession, actor.session_token_hash)
    if session is not None and session.revoked_at is None:
        session.revoked_at = utc_now()
        record_audit(db, action="auth.logout", actor_user_id=actor.id)
        db.commit()
    clear_session_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/password", response_model=SessionTokenPayload)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    db: DbSession,
    actor: CurrentActor,
    settings: SettingsDependency,
) -> SessionTokenPayload:
    client_ip = request.client.host if request.client is not None else "unknown"
    decision = consume_rate_bucket(
        db,
        settings=settings,
        scope="password-change",
        subject=f"{actor.id}:{client_ip}",
        limit=10,
        window_seconds=15 * 60,
    )
    db.commit()
    if not decision.allowed:
        raise _rate_limit_exception(decision.retry_after_seconds)

    user = load_active_actor(db, actor)
    verified_password_hash = user.password_hash
    current_password = payload.current_password.get_secret_value()
    if current_password != payload.new_password.get_secret_value():
        try:
            password_matches = verify_password(verified_password_hash, current_password)
        except PasswordHashCapacityError as exc:
            raise _hash_capacity_exception() from exc
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a new password different from the current password",
        )

    if not password_matches:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect",
        )

    try:
        new_hash = hash_password(payload.new_password.get_secret_value())
    except PasswordHashCapacityError as exc:
        raise _hash_capacity_exception() from exc

    user = load_active_actor(db, actor, for_update=True)
    # An admin reset racing this request must not be silently overwritten.
    if not hmac.compare_digest(user.password_hash, verified_password_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account credentials changed; sign in again",
        )

    now = utc_now()
    user.password_hash = new_hash
    user.password_changed_at = now
    db.execute(
        update(WebSession)
        .where(WebSession.user_id == user.id, WebSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    session_token = new_opaque_token()
    csrf_token = new_opaque_token()
    hashed_session_token = token_hash(session_token)
    hashed_csrf_token = token_hash(csrf_token)
    if hashed_session_token is None or hashed_csrf_token is None:
        raise RuntimeError("Could not create session tokens")
    db.add(
        WebSession(
            token_hash=hashed_session_token,
            csrf_token_hash=hashed_csrf_token,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
        )
    )
    record_audit(db, action="auth.password_changed", actor_user_id=user.id)
    db.commit()
    set_session_cookies(
        response,
        settings=settings,
        session_token=session_token,
        csrf_token=csrf_token,
    )
    return SessionTokenPayload(user=user_view(user), csrf_token=csrf_token)
