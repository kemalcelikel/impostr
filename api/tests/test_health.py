from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.database import database_url_from_environment
from app.main import create_app


@pytest.fixture
def engine() -> Iterator[Engine]:
    database_engine = create_engine("sqlite+pysqlite:///:memory:")
    yield database_engine
    database_engine.dispose()


def test_health_executes_a_database_query_and_disables_caching(engine: Engine) -> None:
    with TestClient(create_app(engine)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_database_failure_returns_generic_service_unavailable(
    engine: Engine, monkeypatch: MonkeyPatch
) -> None:
    def unavailable_connect() -> None:
        raise SQLAlchemyError("test-only database diagnostic")

    monkeypatch.setattr(engine, "connect", unavailable_connect)

    with TestClient(create_app(engine)) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "test-only" not in response.text


def test_database_url_preserves_special_characters_in_password() -> None:
    password_marker = "test-marker:/@percent%"
    url = database_url_from_environment(
        {
            "DB_HOST": "db",
            "DB_NAME": "impostr",
            "DB_PASSWORD": password_marker,
            "DB_PORT": "5432",
            "DB_USER": "impostr_app",
        }
    )

    assert url.password == password_marker


def test_only_health_route_is_exposed(engine: Engine) -> None:
    with TestClient(create_app(engine)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/api/agents").status_code == 404
