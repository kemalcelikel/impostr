"""Atomic database-backed rate buckets shared across API process restarts."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.models import RateLimitBucket


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def rate_limit_key(settings: AppSettings, scope: str, subject: str) -> bytes:
    message = f"impostr\0{scope}\0{subject}".encode()
    return hmac.new(settings.rate_limit_key, message, hashlib.sha256).digest()


def consume_rate_bucket(
    db: Session,
    *,
    settings: AppSettings,
    scope: str,
    subject: str,
    limit: int,
    window_seconds: int,
) -> RateLimitDecision:
    """Count one request atomically and retain only a bounded set of stale rows."""
    now = utc_now()
    window = timedelta(seconds=window_seconds)
    key_hash = rate_limit_key(settings, scope, subject)
    expired_window = RateLimitBucket.window_started <= now - window
    insert = {
        "key_hash": key_hash,
        "window_started": now,
        "attempts": 1,
        "expires_at": now + window * 2,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement: Any = postgresql_insert(RateLimitBucket).values(**insert)
    elif dialect == "sqlite":
        statement = sqlite_insert(RateLimitBucket).values(**insert)
    else:
        raise RuntimeError("Rate limiting requires PostgreSQL or SQLite")

    statement = statement.on_conflict_do_update(
        index_elements=[RateLimitBucket.key_hash],
        set_={
            "window_started": case((expired_window, now), else_=RateLimitBucket.window_started),
            "attempts": case(
                (expired_window, 1),
                (RateLimitBucket.attempts < limit + 1, RateLimitBucket.attempts + 1),
                else_=RateLimitBucket.attempts,
            ),
            "expires_at": case(
                (expired_window, now + window * 2), else_=RateLimitBucket.expires_at
            ),
        },
    ).returning(RateLimitBucket.attempts, RateLimitBucket.window_started)

    attempts, window_started = cast(tuple[int, datetime], db.execute(statement).one())
    stale_keys = (
        select(RateLimitBucket.key_hash)
        .where(RateLimitBucket.expires_at <= now)
        .order_by(RateLimitBucket.expires_at)
        .limit(100)
    )
    db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(stale_keys)))

    if window_started.tzinfo is None:
        window_started = window_started.replace(tzinfo=UTC)
    retry_after = max(1, window_seconds - int((now - window_started).total_seconds()))
    return RateLimitDecision(allowed=attempts <= limit, retry_after_seconds=retry_after)
