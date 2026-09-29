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
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app import document_pair_approvals as approval_module
from app import project_documents as document_module
from app.config import AppSettings
from app.database import database_url_from_environment
from app.main import create_app
from app.models import (
    AuditEvent,
    Project,
    ProjectDocumentPairApproval,
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


def valid_project(detail: str) -> str:
    return (
        f"# Project: {detail}\n"
        "## 1. Purpose and users — required\n"
        f"- Summary: {detail} supports owner planning.\n"
        "- Problem: Drafts need an owner.\n- Primary users: The owner.\n"
        "- Usage context: A local planning browser.\n"
        "- Product outcomes: Reviewable private drafts.\n"
        "## 2. Scope — required\n### In scope\n- Review drafts.\n"
        "### Out of scope\n- Public deployment.\n"
        "## 3. Behavior and domain rules — required\nA stale write returns a conflict.\n"
        "## 4. Technology and environment — required\nPython 3.12; PostgreSQL 17.\n"
        "## 5. Architecture and repository map — required\nThe API owns revisions.\n"
        "## 9. Decisions, risks, and open questions — required\nHuman approval is explicit.\n"
        "## 10. Definition of done — required\nConflicts preserve both drafts.\n"
    )


def valid_agents(detail: str) -> str:
    return (
        f"# Repository Agent Rules: {detail}\n"
        "## Sources of truth and scope\nPROJECT.md defines the product.\n"
        "## Setup and verification commands\nRun `python3 -m pytest` from api/.\n"
        "## Security and hardening workflow\nKeep credentials outside Git.\n"
        "## Git and task-state ownership\nThe owner decides task state.\n"
    )


PUBLIC_PROJECT = valid_project("Project pair race sentinel; saved project specification")
PUBLIC_AGENTS = valid_agents("Agent pair race sentinel; saved agent rules")


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
    assert response.status_code == 200


def _headers(client: TestClient, settings: AppSettings) -> dict[str, str]:
    return {
        "Origin": settings.public_origin,
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }


def _save(
    client: TestClient,
    project_id: uuid.UUID,
    kind: str,
    expected_revision: int,
    content: str,
    settings: AppSettings,
):
    return client.put(
        f"/api/projects/{project_id}/documents/{kind}",
        json={"expected_revision": expected_revision, "content": content},
        headers=_headers(client, settings),
    )


def _approve(
    client: TestClient,
    project_id: uuid.UUID,
    project_revision: int,
    agents_revision: int,
    settings: AppSettings,
):
    return client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json={
            "expected_project_revision": project_revision,
            "expected_agents_revision": agents_revision,
        },
        headers=_headers(client, settings),
    )


def test_postgres_pair_approval_serializes_duplicate_actions_and_save_races(
    monkeypatch,
) -> None:
    """Distinct PostgreSQL connections keep approval tuples atomic and current."""
    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:12]
    owner_name = f"it-pair-owner-{suffix}"
    admin_name = f"it-pair-admin-{suffix}"
    password = "pair approval integration passphrase"
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
    user_ids = [owner.id, admin.id]
    project_ids: list[uuid.UUID] = []
    login_keys = [
        rate_limit_key(settings, "login-username", owner_name),
        rate_limit_key(settings, "login-username", admin_name),
        rate_limit_key(settings, "login-ip", "testclient"),
        rate_limit_key(settings, "project-create", str(owner.id)),
        rate_limit_key(settings, "project-document-write", str(owner.id)),
        rate_limit_key(settings, "project-document-pair-approval", str(owner.id)),
        rate_limit_key(settings, "project-document-pair-approval", str(admin.id)),
    ]
    workspace_parent = TemporaryDirectory(prefix="impostr-pg-pair-approval-")
    workspace_root = Path(workspace_parent.name) / "workspaces"
    pair_locked = Event()
    release_approval = Event()
    save_waiting_for_head = Event()

    try:
        with Session(engine) as db, db.begin():
            db.add_all([owner, admin])

        app = create_app(engine, settings, workspace_root=workspace_root)
        with TestClient(app) as owner_tab, TestClient(app) as admin_tab:
            _login(owner_tab, owner_name, password, settings)
            _login(admin_tab, admin_name, password, settings)
            created = owner_tab.post(
                "/api/projects",
                json={"name": f"Pair race {suffix}"},
                headers=_headers(owner_tab, settings),
            )
            assert created.status_code == 201
            project_id = uuid.UUID(created.json()["id"])
            project_ids.append(project_id)
            for kind, content in (("project", PUBLIC_PROJECT), ("agents", PUBLIC_AGENTS)):
                saved = _save(owner_tab, project_id, kind, 1, content, settings)
                assert saved.status_code == 200 and saved.json()["revision_number"] == 2

            start_together = Barrier(2)

            def approve_from(tab: TestClient):
                start_together.wait(timeout=10)
                return _approve(tab, project_id, 2, 2, settings)

            with ThreadPoolExecutor(max_workers=2) as pool:
                duplicate_requests = [
                    pool.submit(approve_from, owner_tab),
                    pool.submit(approve_from, admin_tab),
                ]
                duplicate_results = [future.result(timeout=20) for future in duplicate_requests]
            assert [result.status_code for result in duplicate_results] == [200, 200]
            assert duplicate_results[0].json()["id"] == duplicate_results[1].json()["id"]

            with Session(engine) as db:
                approvals = list(
                    db.scalars(
                        select(ProjectDocumentPairApproval).where(
                            ProjectDocumentPairApproval.project_id == project_id
                        )
                    ).all()
                )
                events = list(
                    db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == "project.document_pair.approved",
                            AuditEvent.project_id == project_id,
                        )
                    ).all()
                )
            assert len(approvals) == len(events) == 1
            assert approvals[0].project_revision_id == uuid.UUID(
                duplicate_results[0].json()["project_revision_id"]
            )
            assert approvals[0].agents_revision_id == uuid.UUID(
                duplicate_results[0].json()["agents_revision_id"]
            )
            assert all(PUBLIC_PROJECT not in str(event.details) for event in events)
            assert all(PUBLIC_AGENTS not in str(event.details) for event in events)

            # Move to a new valid pair, then hold both ordered head locks while a
            # different account attempts a save on one member of that pair.
            for kind, content in (
                (
                    "project",
                    valid_project("Pair race revision three; ready for serialized approval"),
                ),
                ("agents", valid_agents("Agent rules revision three; saved pair is current")),
            ):
                saved = _save(owner_tab, project_id, kind, 2, content, settings)
                assert saved.status_code == 200 and saved.json()["revision_number"] == 3

            original_lock_pair = approval_module._lock_pair_heads
            original_load_document = document_module._load_document

            def pause_after_pair_lock(db, identifier):
                documents, revisions = original_lock_pair(db, identifier)
                if not pair_locked.is_set():
                    pair_locked.set()
                    if not release_approval.wait(timeout=20):
                        raise TimeoutError("Timed out waiting to release approval row locks")
                return documents, revisions

            def signal_save_lock(db, identifier, kind, *, for_update=False):
                if identifier == project_id and kind == "project" and for_update:
                    save_waiting_for_head.set()
                return original_load_document(db, identifier, kind, for_update=for_update)

            monkeypatch.setattr(approval_module, "_lock_pair_heads", pause_after_pair_lock)
            monkeypatch.setattr(document_module, "_load_document", signal_save_lock)
            with ThreadPoolExecutor(max_workers=2) as pool:
                try:
                    approving = pool.submit(_approve, admin_tab, project_id, 3, 3, settings)
                    assert pair_locked.wait(timeout=10)
                    saving = pool.submit(
                        _save,
                        owner_tab,
                        project_id,
                        "project",
                        3,
                        valid_project("Pair race revision four; later save invalidates approval"),
                        settings,
                    )
                    assert save_waiting_for_head.wait(timeout=10)
                    with pytest.raises(FutureTimeoutError):
                        saving.result(timeout=0.5)
                finally:
                    release_approval.set()
                approved = approving.result(timeout=20)
                saved = saving.result(timeout=20)

            assert approved.status_code == 200
            assert approved.json()["project_revision_number"] == 3
            assert approved.json()["agents_revision_number"] == 3
            assert saved.status_code == 200
            assert saved.json()["revision_number"] == 4

            monkeypatch.setattr(approval_module, "_lock_pair_heads", original_lock_pair)
            monkeypatch.setattr(document_module, "_load_document", original_load_document)
            status_response = admin_tab.get(f"/api/projects/{project_id}/document-pair-approval")
            assert status_response.status_code == 200
            state = status_response.json()
            assert state["approved"] is False
            assert state["current_project_revision"]["revision_number"] == 4
            assert state["current_agents_revision"]["revision_number"] == 3
            assert state["latest_approval"]["project_revision_number"] == 3
            assert state["latest_approval"]["agents_revision_number"] == 3

            stale = _approve(admin_tab, project_id, 3, 3, settings)
            assert stale.status_code == 409
            assert stale.json()["latest"]["project"]["revision_number"] == 4
            assert stale.json()["latest"]["agents"]["revision_number"] == 3
            assert stale.json()["latest"]["project"]["content"].startswith(
                "# Project: Pair race revision four"
            )

            # Save-first ordering: the approval request has passed authentication
            # but must resolve the live pair only after the other tab's save.
            before_pair_read = Event()
            release_pair_read = Event()

            def wait_before_pair_read(db, identifier):
                before_pair_read.set()
                if not release_pair_read.wait(timeout=20):
                    raise TimeoutError("Timed out before approval pair read")
                return original_lock_pair(db, identifier)

            monkeypatch.setattr(approval_module, "_lock_pair_heads", wait_before_pair_read)
            with ThreadPoolExecutor(max_workers=2) as pool:
                try:
                    pending_approval = pool.submit(_approve, admin_tab, project_id, 4, 3, settings)
                    assert before_pair_read.wait(timeout=10)
                    changed_agents = valid_agents("Saved first; new agent rules revision four")
                    saved_first = pool.submit(
                        _save, owner_tab, project_id, "agents", 3, changed_agents, settings
                    ).result(timeout=20)
                    assert saved_first.status_code == 200
                finally:
                    release_pair_read.set()
                rejected_approval = pending_approval.result(timeout=20)
            assert rejected_approval.status_code == 409
            assert rejected_approval.json()["latest"]["agents"]["content"] == changed_agents

            monkeypatch.setattr(approval_module, "_lock_pair_heads", original_lock_pair)
            fourth_pair = _approve(admin_tab, project_id, 4, 4, settings)
            assert fourth_pair.status_code == 200
            same_text = _save(owner_tab, project_id, "agents", 4, changed_agents, settings)
            assert same_text.status_code == 200
            assert same_text.json()["revision_number"] == 5
            assert same_text.json()["content_sha256"] == saved_first.json()["content_sha256"]
            same_text_status = admin_tab.get(f"/api/projects/{project_id}/document-pair-approval")
            assert same_text_status.status_code == 200
            assert same_text_status.json()["approved"] is False
            assert same_text_status.json()["current_agents_revision"]["revision_number"] == 5
            assert same_text_status.json()["latest_approval"]["id"] == fourth_pair.json()["id"]
            assert _approve(admin_tab, project_id, 4, 4, settings).status_code == 409

            history_path = f"/api/projects/{project_id}/document-pair-approval"
            first_page = admin_tab.get(history_path, params={"limit": 1})
            assert first_page.status_code == 200
            assert [row["id"] for row in first_page.json()["approvals"]] == [
                fourth_pair.json()["id"]
            ]
            cursor = first_page.json()["approval_next_cursor"]
            assert cursor
            inserted = _approve(admin_tab, project_id, 4, 5, settings)
            assert inserted.status_code == 200
            older_page = admin_tab.get(history_path, params={"limit": 1, "cursor": cursor})
            assert older_page.status_code == 200
            assert older_page.json()["approved"] is True
            assert older_page.json()["latest_approval"]["id"] == inserted.json()["id"]
            assert older_page.json()["approvals"][0]["id"] != fourth_pair.json()["id"]
            assert older_page.json()["approvals"][0]["id"] != inserted.json()["id"]

        with Session(engine) as db:
            final_approvals = list(
                db.scalars(
                    select(ProjectDocumentPairApproval).where(
                        ProjectDocumentPairApproval.project_id == project_id
                    )
                ).all()
            )
            approval_events = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "project.document_pair.approved",
                        AuditEvent.project_id == project_id,
                    )
                ).all()
            )
        assert len(final_approvals) == len(approval_events) == 4
        assert all(PUBLIC_PROJECT not in str(event.details) for event in approval_events)
        assert all(PUBLIC_AGENTS not in str(event.details) for event in approval_events)
    finally:
        release_approval.set()
        with Session(engine) as db, db.begin():
            if project_ids:
                db.execute(delete(AuditEvent).where(AuditEvent.project_id.in_(project_ids)))
                db.execute(delete(Project).where(Project.id.in_(project_ids)))
            db.execute(delete(WebSession).where(WebSession.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(login_keys)))
        workspace_parent.cleanup()
        engine.dispose()
