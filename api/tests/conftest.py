from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import AppSettings
from app.db import Base
from app.main import create_app
from app.models import BootstrapState, Project, User
from app.passwords import hash_password, normalize_username

PUBLIC_ORIGIN = "http://127.0.0.1:8080"


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings(
        public_origin=PUBLIC_ORIGIN,
        rate_limit_key=b"test-only-rate-limit-key-that-is-not-a-secret",
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    database_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database_engine)
    with Session(database_engine) as db, db.begin():
        db.add(BootstrapState(id=1, completed=False))
    yield database_engine
    database_engine.dispose()


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    return tmp_path / "private-workspaces"


@pytest.fixture
def client(
    engine: Engine,
    settings: AppSettings,
    workspace_root: Path,
) -> Iterator[TestClient]:
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as test_client:
        yield test_client


@pytest.fixture
def account_factory(engine: Engine) -> Callable[..., uuid.UUID]:
    def create_account(
        username: str,
        password: str,
        *,
        role: str = "user",
        active: bool = True,
    ) -> uuid.UUID:
        now = datetime.now(UTC)
        user = User(
            id=uuid.uuid4(),
            username=normalize_username(username),
            password_hash=hash_password(password),
            role=role,
            is_active=active,
            created_at=now,
            password_changed_at=now,
        )
        user_id = user.id
        with Session(engine) as db, db.begin():
            db.add(user)
            db.flush()
        return user_id

    return create_account


@pytest.fixture
def project_factory(engine: Engine) -> Callable[..., uuid.UUID]:
    def create_project(owner_user_id: uuid.UUID, name: str) -> uuid.UUID:
        project = Project(id=uuid.uuid4(), name=name, owner_user_id=owner_user_id)
        project_id = project.id
        with Session(engine) as db, db.begin():
            db.add(project)
            db.flush()
        return project_id

    return create_project
