from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import AppSettings
from app.database import database_url_from_environment
from app.main import create_app


def test_health_executes_a_database_query_and_disables_caching(
    engine: Engine, settings: AppSettings
) -> None:
    with TestClient(create_app(engine, settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_database_failure_returns_generic_service_unavailable(
    engine: Engine, settings: AppSettings, monkeypatch: MonkeyPatch
) -> None:
    def unavailable_connect() -> None:
        raise SQLAlchemyError("test-only database diagnostic")

    monkeypatch.setattr(engine, "connect", unavailable_connect)

    with TestClient(create_app(engine, settings)) as client:
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


def test_docs_signup_and_unimplemented_agent_routes_are_not_exposed(
    engine: Engine, settings: AppSettings
) -> None:
    with TestClient(create_app(engine, settings)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/api/agents").status_code == 404
        assert client.post("/api/auth/register").status_code == 404
