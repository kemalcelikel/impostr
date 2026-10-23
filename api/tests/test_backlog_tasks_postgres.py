from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import AppSettings
from app.database import database_url_from_environment
from app.main import create_app
from app.models import AuditEvent, Project, RateLimitBucket, User
from app.passwords import hash_password
from app.project_templates import ProjectTemplate
from app.rate_limit import rate_limit_key

pytestmark = pytest.mark.skipif(
    os.environ.get("IMPOSTR_TEST_POSTGRES") != "1",
    reason="requires the disposable PostgreSQL integration profile",
)


def _engine() -> Engine:
    return create_engine(
        database_url_from_environment(),
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
        poolclass=NullPool,
    )


def _login(client: TestClient, username: str, password: str, origin: str) -> None:
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": origin, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200


def test_postgres_concurrent_backlog_task_saves_preserve_a_conflict_proposal() -> None:
    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:16]
    username = f"it-backlog-{suffix}"
    password = "integration-only passphrase"
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username=username,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        created_at=datetime.now(UTC),
        password_changed_at=datetime.now(UTC),
    )
    project_id: uuid.UUID | None = None
    workspace_parent = TemporaryDirectory(prefix="impostr-pg-backlog-")
    workspace_root = Path(workspace_parent.name) / "workspaces"

    try:
        with Session(engine) as db, db.begin():
            db.add(user)

        app = create_app(engine, settings, workspace_root=workspace_root)
        second_app = create_app(engine, settings, workspace_root=workspace_root)
        backlog_content = (
            "# Concurrent backlog\n\n"
            "## [ ] TASK-001 — Foundation\n"
            "**Depends on:** None\n"
            "- Original foundation.\n\n"
            "## Context notes\n"
            "**Branch:** retained\n"
            "This section remains outside the task editor body.\n\n"
            "## [ ] TASK-002 — Follow-up\n"
            "**Depends on:** TASK-001\n"
            "- Original follow-up.\n"
        )
        with TestClient(app) as first_tab, TestClient(second_app) as second_tab:
            for target_app in (app, second_app):
                template = target_app.state.project_templates["backlog"]
                target_app.state.project_templates["backlog"] = ProjectTemplate(
                    kind="backlog",
                    source=template.source,
                    content=backlog_content,
                    sha256=hashlib.sha256(backlog_content.encode("utf-8")).hexdigest(),
                )
            _login(first_tab, username, password, settings.public_origin)
            _login(second_tab, username, password, settings.public_origin)
            created = first_tab.post(
                "/api/projects",
                json={"name": f"Concurrent backlog {suffix}"},
                headers={
                    "Origin": settings.public_origin,
                    "X-CSRF-Token": first_tab.cookies.get("impostr_csrf", ""),
                },
            )
            assert created.status_code == 201, created.text
            project_id = uuid.UUID(created.json()["id"])
            task_path = f"/api/projects/{project_id}/backlog/tasks"
            initial = first_tab.get(task_path)
            assert initial.status_code == 200
            initial_view = initial.json()
            tasks = {task["id"]: task for task in initial_view["tasks"]}
            assert {"TASK-001", "TASK-002"}.issubset(tasks)

            barrier = Barrier(2)

            def save(tab: TestClient, task_id: str, title: str) -> object:
                task = tasks[task_id]
                barrier.wait(timeout=10)
                return tab.put(
                    f"{task_path}/{task_id}",
                    json={
                        "expected_revision": initial_view["revision_number"],
                        "status": " ",
                        "title": title,
                        "body": task["body"],
                    },
                    headers={
                        "Origin": settings.public_origin,
                        "X-CSRF-Token": tab.cookies.get("impostr_csrf", ""),
                    },
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(save, first_tab, "TASK-001", "Concurrent foundation")
                second = pool.submit(save, second_tab, "TASK-002", "Concurrent follow-up")
                responses = [first.result(timeout=30), second.result(timeout=30)]

            assert sorted(response.status_code for response in responses) == [200, 409]
            conflict = next(response for response in responses if response.status_code == 409)
            winner = next(response for response in responses if response.status_code == 200)
            winning_tasks = winner.json()["tasks"]
            assert winner.json()["revision_number"] == 2
            assert conflict.json()["latest"]["revision_number"] == 2

            current = first_tab.get(task_path)
            assert current.status_code == 200
            current_view = current.json()
            assert current_view["revision_number"] == 2
            assert "## Context notes\n**Branch:** retained" in current_view["content"]
            current_titles = {task["title"] for task in current_view["tasks"]}
            assert (
                "Concurrent foundation" in current_titles
                or "Concurrent follow-up" in current_titles
            )

            history = first_tab.get(f"/api/projects/{project_id}/documents/backlog/history")
            assert history.status_code == 200
            assert [row["revision_number"] for row in history.json()["revisions"]] == [2, 1]
            assert len(history.json()["proposals"]) == 1
            proposal_id = history.json()["proposals"][0]["id"]
            proposal = first_tab.get(
                f"/api/projects/{project_id}/documents/backlog/proposals/{proposal_id}"
            )
            assert proposal.status_code == 200
            losing_title = (
                "Concurrent follow-up"
                if "Concurrent foundation" in current_titles
                else "Concurrent foundation"
            )
            assert losing_title in proposal.json()["content"]
            assert proposal.json()["expected_revision_number"] == 1
            assert proposal.json()["observed_revision_number"] == 2
            assert any("Concurrent" in task["title"] for task in winning_tasks)
    finally:
        rate_limit_keys = [
            rate_limit_key(settings, "login-username", username),
            rate_limit_key(settings, "login-ip", "testclient"),
            rate_limit_key(settings, "project-create", str(user_id)),
            rate_limit_key(settings, "project-document-write", str(user_id)),
        ]
        with Session(engine) as db, db.begin():
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(rate_limit_keys)))
            audit_scope = [AuditEvent.actor_user_id == user_id]
            if project_id is not None:
                audit_scope.append(AuditEvent.project_id == project_id)
            db.execute(delete(AuditEvent).where(or_(*audit_scope)))
            if project_id is not None:
                db.execute(delete(Project).where(Project.id == project_id))
            db.execute(delete(User).where(User.id == user_id))
        workspace_parent.cleanup()
        engine.dispose()
