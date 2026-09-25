from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.main import create_app
from app.models import AuditEvent

PUBLIC_ORIGIN = "http://127.0.0.1:8080"


def _login(client: TestClient, username: str, password: str) -> None:
    csrf_response = client.get("/api/auth/csrf")
    assert csrf_response.status_code == 200
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={
            "Origin": PUBLIC_ORIGIN,
            "X-CSRF-Token": csrf_response.json()["csrf_token"],
        },
    )
    assert response.status_code == 200


def test_creator_only_metadata_and_audited_admin_access(
    client: TestClient,
    engine,
    settings: AppSettings,
    account_factory,
    project_factory,
) -> None:
    alice_id = account_factory("alice", "correct horse battery")
    bob_id = account_factory("bob", "correct horse battery")
    admin_id = account_factory("admin", "correct horse battery", role="admin")
    alice_project_id = project_factory(alice_id, "Alice private plan")
    bob_project_id = project_factory(bob_id, "Bob confidential notes")
    unknown_project_id = uuid.uuid4()

    _login(client, "alice", "correct horse battery")
    alice_listing = client.get("/api/projects")
    assert alice_listing.status_code == 200
    assert [project["id"] for project in alice_listing.json()] == [str(alice_project_id)]
    assert alice_listing.json()[0]["name"] == "Alice private plan"
    own_project = client.get(f"/api/projects/{alice_project_id}")
    foreign_project = client.get(f"/api/projects/{bob_project_id}")
    unknown_project = client.get(f"/api/projects/{unknown_project_id}")
    assert own_project.status_code == 200
    assert foreign_project.status_code == unknown_project.status_code == 404
    assert foreign_project.json() == unknown_project.json() == {"detail": "Project not found"}
    assert "Bob confidential notes" not in foreign_project.text

    with TestClient(create_app(engine, settings)) as bob_client:
        _login(bob_client, "bob", "correct horse battery")
        bob_listing = bob_client.get("/api/projects")
        denied = bob_client.get(f"/api/projects/{alice_project_id}")
        assert [project["id"] for project in bob_listing.json()] == [str(bob_project_id)]
        assert denied.status_code == 404
        assert denied.json() == {"detail": "Project not found"}

    with TestClient(create_app(engine, settings)) as admin_client:
        _login(admin_client, "admin", "correct horse battery")
        all_projects = admin_client.get("/api/projects")
        assert all_projects.status_code == 200
        assert {project["id"] for project in all_projects.json()} == {
            str(alice_project_id),
            str(bob_project_id),
        }
        assert (
            admin_client.get(f"/api/projects/{bob_project_id}").json()["name"]
            == "Bob confidential notes"
        )
        csrf = admin_client.cookies.get("impostr_csrf")
        no_project_creation = admin_client.post(
            "/api/projects",
            json={"name": "out of scope"},
            headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf or ""},
        )
        assert no_project_creation.status_code == 405

    with Session(engine) as db:
        admin_events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.actor_user_id == admin_id,
                    AuditEvent.action.in_(("admin.projects.read", "admin.project.read")),
                )
            ).all()
        )
        assert sum(event.action == "admin.projects.read" for event in admin_events) == 1
        project_list_event = next(
            event for event in admin_events if event.action == "admin.projects.read"
        )
        assert project_list_event.details is not None
        assert set(project_list_event.details["project_ids"]) == {
            str(alice_project_id),
            str(bob_project_id),
        }
        detail_events = [event for event in admin_events if event.action == "admin.project.read"]
        assert len(detail_events) == 1
        assert detail_events[0].project_id == bob_project_id


def test_project_routes_require_a_live_authenticated_session(client: TestClient) -> None:
    assert client.get("/api/projects").status_code == 401
    assert client.get(f"/api/projects/{uuid.uuid4()}").status_code == 401
