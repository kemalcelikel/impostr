"""PostgreSQL connection configuration and engine creation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL


def database_url_from_environment(environ: Mapping[str, str] | None = None) -> URL:
    """Build a safely escaped PostgreSQL URL from server-side configuration."""
    settings = os.environ if environ is None else environ
    password = settings.get("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD must be configured")

    port = int(settings.get("DB_PORT", "5432"))
    if not 1 <= port <= 65535:
        raise RuntimeError("DB_PORT must be between 1 and 65535")

    return URL.create(
        drivername="postgresql+psycopg",
        username=settings.get("DB_USER", "impostr_app"),
        password=password,
        host=settings.get("DB_HOST", "db"),
        port=port,
        database=settings.get("DB_NAME", "impostr"),
    )


@lru_cache(maxsize=1)
def get_database_engine() -> Engine:
    """Return the process-wide bounded, health-checked database connection pool."""
    return create_engine(
        database_url_from_environment(),
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
        max_overflow=0,
        pool_pre_ping=True,
        pool_size=5,
        pool_timeout=5,
        pool_recycle=1800,
    )
