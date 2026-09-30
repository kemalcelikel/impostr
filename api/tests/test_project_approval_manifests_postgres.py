from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from legacy_templates import legacy_templates
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from test_template_profiles import AGENTS as SIMPLIFIED_AGENTS
from test_template_profiles import BACKLOG as SIMPLIFIED_BACKLOG
from test_template_profiles import PROJECT as SIMPLIFIED_PROJECT

from app import project_approval_manifests as manifest_module
from app import project_documents as document_module
from app.config import AppSettings
from app.database import database_url_from_environment
from app.main import create_app
from app.models import (
    AuditEvent,
    Project,
    ProjectApprovalManifest,
    RateLimitBucket,
    User,
    WebSession,
)
from app.passwords import hash_password
from app.rate_limit import rate_limit_key

pytestmark = pytest.mark.skipif(
    os.environ.get("IMPOSTR_TEST_POSTGRES") != "1",
    reason="requires the disposable PostgreSQL integration profile",
)

PUBLIC_ORIGIN = "http://127.0.0.1:8080"
STARTER_BACKLOG = """# Backlog: <PROJECT_NAME>

> STARTER TEMPLATE — replace placeholders before approval.

## [-] TASK-001 — <First planning outcome>

**Depends on:** None
"""
VALID_BACKLOG = """# Backlog: PostgreSQL approval race

## [-] TASK-001 — Define the initial planning slice
**Depends on:** None

## [-] TASK-002 — Review the saved slice
**Depends on:** TASK-001
"""
PROJECT_TEXT = """# Project: PostgreSQL manifest integration

## 1. Purpose and users — required
- Summary: PostgreSQL integration planning has an accountable owner.
- Problem: Saved project files need a stable final snapshot.
- Primary users: The project owner.
- Usage context: A local planning browser.
- Product outcomes: Reviewable private drafts.

## 2. Scope — required
### In scope
- Record the approved three-file snapshot.
### Out of scope
- Public deployment.

## 3. Behavior and domain rules — required
A later saved revision invalidates an earlier snapshot.

## 4. Technology and environment — required
Python 3.12 and PostgreSQL 17 store revisions.

## 5. Architecture and repository map — required
The API owns document revisions and export authorization.

## 9. Decisions, risks, and open questions — required
The owner reviews all three saved files.

## 10. Definition of done — required
A stale snapshot cannot be downloaded.
"""
AGENTS_TEXT = """# Repository Agent Rules: PostgreSQL integration

## Sources of truth and scope
PROJECT.md defines the project and owner decisions.

## Setup and verification commands
Run `python3 -m pytest` for the API checks.

## Security and hardening workflow
Keep credentials outside the repository and deny foreign project reads.

## Git and task-state ownership
The owner controls readiness and integration.
"""


def _engine() -> Engine:
    return create_engine(
        database_url_from_environment(),
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
        poolclass=NullPool,
    )


def _login(client: TestClient, username: str, password: str, settings: AppSettings) -> None:
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": settings.public_origin, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text


def _headers(client: TestClient, settings: AppSettings) -> dict[str, str]:
    return {
        "Origin": settings.public_origin,
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }


def _set_backlog_template(app) -> None:
    app.state.project_templates = legacy_templates()


def _save(
    client: TestClient,
    settings: AppSettings,
    project_id: uuid.UUID,
    kind: str,
    expected_revision: int,
    content: str,
):
    return client.put(
        f"/api/projects/{project_id}/documents/{kind}",
        json={"expected_revision": expected_revision, "content": content},
        headers=_headers(client, settings),
    )


def _approve_pair(
    client: TestClient,
    settings: AppSettings,
    project_id: uuid.UUID,
):
    return client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json={"expected_project_revision": 2, "expected_agents_revision": 2},
        headers=_headers(client, settings),
    )


def _approve_manifest(
    client: TestClient,
    settings: AppSettings,
    project_id: uuid.UUID,
    pair_approval_id: str,
    backlog_revision: int,
):
    return client.post(
        f"/api/projects/{project_id}/final-approval",
        json={
            "expected_pair_approval_id": pair_approval_id,
            "expected_backlog_revision": backlog_revision,
        },
        headers=_headers(client, settings),
    )


@pytest.mark.parametrize("profile", ["legacy", "simplified"])
def test_postgres_manifest_creation_is_idempotent_and_serializes_a_backlog_save_race(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    """Ordered head locks serialize duplicate approval and later same-byte saves."""
    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:12]
    owner_name = f"it-manifest-owner-{suffix}"
    admin_name = f"it-manifest-admin-{suffix}"
    password = "manifest integration passphrase"
    now = datetime.now(UTC)
    owner = User(
        id=uuid.uuid4(),
        username=owner_name,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    admin = User(
        id=uuid.uuid4(),
        username=admin_name,
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    owner_id = owner.id
    admin_id = admin.id
    project_ids: list[uuid.UUID] = []
    rate_limit_keys = [
        rate_limit_key(settings, "login-username", owner_name),
        rate_limit_key(settings, "login-username", admin_name),
        rate_limit_key(settings, "login-ip", "testclient"),
        rate_limit_key(settings, "project-create", str(owner_id)),
        rate_limit_key(settings, "project-document-write", str(owner_id)),
        rate_limit_key(settings, "project-document-pair-approval", str(owner_id)),
        rate_limit_key(settings, "project-approval-manifest", str(owner_id)),
        rate_limit_key(settings, "project-approval-manifest", str(admin_id)),
    ]
    workspace_parent = TemporaryDirectory(prefix="impostr-pg-manifest-")
    workspace_root = Path(workspace_parent.name) / "workspaces"
    manifest_heads_locked = Event()
    release_manifest = Event()
    save_waiting_for_head = Event()

    try:
        with Session(engine) as db, db.begin():
            db.add_all([owner, admin])

        app = create_app(engine, settings, workspace_root=workspace_root)
        with TestClient(app) as owner_tab, TestClient(app) as admin_tab:
            if profile == "legacy":
                _set_backlog_template(app)
            _login(owner_tab, owner_name, password, settings)
            _login(admin_tab, admin_name, password, settings)
            created = owner_tab.post(
                "/api/projects",
                json={"name": f"Manifest race {suffix}"},
                headers=_headers(owner_tab, settings),
            )
            assert created.status_code == 201, created.text
            project_id = uuid.UUID(created.json()["id"])
            project_ids.append(project_id)
            for kind, content in (
                ("project", PROJECT_TEXT if profile == "legacy" else SIMPLIFIED_PROJECT),
                ("agents", AGENTS_TEXT if profile == "legacy" else SIMPLIFIED_AGENTS),
                ("backlog", VALID_BACKLOG if profile == "legacy" else SIMPLIFIED_BACKLOG),
            ):
                saved = _save(owner_tab, settings, project_id, kind, 1, content)
                assert saved.status_code == 200 and saved.json()["revision_number"] == 2
            pair = _approve_pair(owner_tab, settings, project_id)
            assert pair.status_code == 200, pair.text
            pair_id = pair.json()["id"]

            start_together = Barrier(2)

            def approve_from(tab: TestClient):
                start_together.wait(timeout=10)
                return _approve_manifest(tab, settings, project_id, pair_id, 2)

            with ThreadPoolExecutor(max_workers=2) as pool:
                duplicate_requests = [
                    pool.submit(approve_from, owner_tab),
                    pool.submit(approve_from, admin_tab),
                ]
                duplicate_results = [future.result(timeout=30) for future in duplicate_requests]
            assert [result.status_code for result in duplicate_results] == [200, 200]
            assert duplicate_results[0].json()["id"] == duplicate_results[1].json()["id"]

            with Session(engine) as db:
                first_manifests = list(
                    db.scalars(
                        select(ProjectApprovalManifest).where(
                            ProjectApprovalManifest.project_id == project_id
                        )
                    ).all()
                )
                first_events = list(
                    db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == "project.approval_manifest.approved",
                            AuditEvent.project_id == project_id,
                        )
                    ).all()
                )
            assert len(first_manifests) == len(first_events) == 1
            assert first_manifests[0].actor_user_id in {owner_id, admin_id}
            assert first_events[0].actor_user_id == first_manifests[0].actor_user_id

            new_backlog = (
                VALID_BACKLOG.replace(
                    "# Backlog: PostgreSQL approval race", "# Backlog: PostgreSQL lock ordering"
                )
                if profile == "legacy"
                else SIMPLIFIED_BACKLOG.replace("Fieldnotes", "PostgreSQL lock ordering", 1)
            )
            changed = _save(owner_tab, settings, project_id, "backlog", 2, new_backlog)
            assert changed.status_code == 200 and changed.json()["revision_number"] == 3

            original_lock_heads = manifest_module._lock_manifest_heads
            original_load_document = document_module._load_document

            def pause_after_all_head_locks(db, identifier):
                documents, revisions = original_lock_heads(db, identifier)
                if not manifest_heads_locked.is_set():
                    manifest_heads_locked.set()
                    if not release_manifest.wait(timeout=20):
                        raise TimeoutError("Timed out waiting to release manifest head locks")
                return documents, revisions

            def signal_save_lock(db, identifier, kind, *, for_update=False):
                if identifier == project_id and kind == "backlog" and for_update:
                    save_waiting_for_head.set()
                return original_load_document(db, identifier, kind, for_update=for_update)

            monkeypatch.setattr(manifest_module, "_lock_manifest_heads", pause_after_all_head_locks)
            monkeypatch.setattr(document_module, "_load_document", signal_save_lock)
            with ThreadPoolExecutor(max_workers=2) as pool:
                try:
                    approving = pool.submit(
                        _approve_manifest,
                        admin_tab,
                        settings,
                        project_id,
                        pair_id,
                        3,
                    )
                    assert manifest_heads_locked.wait(timeout=10)
                    saving = pool.submit(
                        _save,
                        owner_tab,
                        settings,
                        project_id,
                        "backlog",
                        3,
                        new_backlog,
                    )
                    assert save_waiting_for_head.wait(timeout=10)
                    with pytest.raises(FutureTimeoutError):
                        saving.result(timeout=0.5)
                finally:
                    release_manifest.set()
                approved = approving.result(timeout=30)
                saved = saving.result(timeout=30)

            assert approved.status_code == 200, approved.text
            assert approved.json()["backlog"]["revision_number"] == 3
            assert saved.status_code == 200 and saved.json()["revision_number"] == 4
            assert saved.json()["content_sha256"] == approved.json()["backlog"]["content_sha256"]

            status_view = owner_tab.get(f"/api/projects/{project_id}/final-approval")
            assert status_view.status_code == 200
            assert status_view.json()["approved"] is False
            assert status_view.json()["latest_manifest"]["id"] == approved.json()["id"]
            assert (
                owner_tab.get(
                    f"/api/projects/{project_id}/final-approval/files/backlog"
                ).status_code
                == 409
            )

        with Session(engine) as db:
            manifests = list(
                db.scalars(
                    select(ProjectApprovalManifest).where(
                        ProjectApprovalManifest.project_id == project_id
                    )
                ).all()
            )
            events = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "project.approval_manifest.approved",
                        AuditEvent.project_id == project_id,
                    )
                ).all()
            )
        assert len(manifests) == len(events) == 2
    finally:
        release_manifest.set()
        with Session(engine) as db, db.begin():
            if project_ids:
                db.execute(delete(AuditEvent).where(AuditEvent.project_id.in_(project_ids)))
                db.execute(delete(Project).where(Project.id.in_(project_ids)))
            db.execute(delete(WebSession).where(WebSession.user_id.in_([owner_id, admin_id])))
            db.execute(delete(User).where(User.id.in_([owner_id, admin_id])))
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(rate_limit_keys)))
        workspace_parent.cleanup()
        engine.dispose()
