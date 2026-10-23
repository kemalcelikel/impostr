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
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, create_engine, delete, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import AppSettings
from app.database import database_url_from_environment
from app.main import create_app
from app.models import (
    AuditEvent,
    BootstrapState,
    DocumentConflictProposal,
    Project,
    ProjectDocument,
    ProjectDocumentRevision,
    RateLimitBucket,
    User,
    WebSession,
)
from app.operator import bootstrap_admin, recover_admin
from app.passwords import hash_password, new_opaque_token, token_hash, verify_password
from app.project_names import project_name_key
from app.rate_limit import consume_rate_bucket, rate_limit_key

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


def _login(client: TestClient, username: str, password: str) -> None:
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    public_origin = AppSettings.from_environment().public_origin
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={
            "Origin": public_origin,
            "X-CSRF-Token": csrf,
        },
    )
    assert response.status_code == 200


def test_postgres_migrated_auth_private_access_and_atomic_limits() -> None:
    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:16]
    admin_name = f"it-admin-{suffix}"
    alice_name = f"it-alice-{suffix}"
    bob_name = f"it-bob-{suffix}"
    password = "integration-only passphrase"
    now = datetime.now(UTC)
    admin = User(
        id=uuid.uuid4(),
        username=admin_name,
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    alice = User(
        id=uuid.uuid4(),
        username=alice_name,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    bob = User(
        id=uuid.uuid4(),
        username=bob_name,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    alice_project = Project(id=uuid.uuid4(), name="Integration private A", owner_user_id=alice.id)
    bob_project = Project(id=uuid.uuid4(), name="Integration private B", owner_user_id=bob.id)
    user_ids = [admin.id, alice.id, bob.id]
    project_ids = [alice_project.id, bob_project.id]
    admin_id, _, _ = user_ids
    alice_project_id, bob_project_id = project_ids
    workspace_parent = TemporaryDirectory(prefix="impostr-pg-migration-")
    workspace_root = Path(workspace_parent.name) / "workspaces"

    try:
        with Session(engine) as db, db.begin():
            db.add_all([admin, alice, bob])
            db.flush()
            db.add_all([alice_project, bob_project])

        app = create_app(engine, settings, workspace_root=workspace_root)
        with TestClient(app) as alice_client:
            with Session(engine) as db:
                assert db.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "20260930_0006"
                )
                assert (
                    len(
                        list(
                            db.scalars(
                                select(ProjectDocument).where(
                                    ProjectDocument.project_id.in_(project_ids)
                                )
                            ).all()
                        )
                    )
                    == 6
                )
            _login(alice_client, alice_name, password)
            assert len(alice_client.get("/api/projects").json()) == 1
            foreign = alice_client.get(f"/api/projects/{bob_project_id}")
            missing = alice_client.get(f"/api/projects/{uuid.uuid4()}")
            assert foreign.status_code == missing.status_code == 404
            assert foreign.json() == missing.json()

        with TestClient(
            create_app(engine, settings, workspace_root=workspace_root)
        ) as admin_client:
            _login(admin_client, admin_name, password)
            assert len(admin_client.get("/api/projects").json()) == 2
            assert admin_client.get(f"/api/projects/{bob_project_id}").status_code == 200

        # Distinct connections contend for the same PostgreSQL key; exactly the
        # configured number of requests may pass the atomic upsert.
        def attempt() -> bool:
            with Session(engine) as db:
                decision = consume_rate_bucket(
                    db,
                    settings=settings,
                    scope=f"integration-concurrency-{suffix}",
                    subject="shared-bucket",
                    limit=7,
                    window_seconds=60,
                )
                db.commit()
                return decision.allowed

        with ThreadPoolExecutor(max_workers=16) as pool:
            outcomes = list(pool.map(lambda _index: attempt(), range(24)))
        assert sum(outcomes) == 7

        with Session(engine) as db:
            admin_events = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.actor_user_id == admin_id,
                        AuditEvent.action.in_(("admin.projects.read", "admin.project.read")),
                    )
                ).all()
            )
            assert {event.action for event in admin_events} == {
                "admin.projects.read",
                "admin.project.read",
            }
            project_list_event = next(
                event for event in admin_events if event.action == "admin.projects.read"
            )
            assert project_list_event.details is not None
            assert set(project_list_event.details["project_ids"]) == {
                str(alice_project_id),
                str(bob_project_id),
            }
    finally:
        login_keys = [
            rate_limit_key(settings, "login-username", name)
            for name in (admin_name, alice_name, bob_name)
        ]
        login_keys.append(rate_limit_key(settings, "login-ip", "testclient"))
        login_keys.append(
            rate_limit_key(settings, f"integration-concurrency-{suffix}", "shared-bucket")
        )
        with Session(engine) as db, db.begin():
            db.execute(
                delete(AuditEvent).where(
                    AuditEvent.actor_user_id.in_(user_ids)
                    | AuditEvent.target_user_id.in_(user_ids)
                    | AuditEvent.project_id.in_(project_ids)
                )
            )
            db.execute(delete(Project).where(Project.id.in_(project_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(login_keys)))
        workspace_parent.cleanup()
        engine.dispose()


def test_postgres_stale_document_writes_preserve_winner_and_conflict_text(monkeypatch) -> None:
    """Separate PostgreSQL connections serialize on the document-head row."""
    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:16]
    username = f"it-revision-{suffix}"
    password = "document race integration passphrase"
    now = datetime.now(UTC)
    owner = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    project_id: uuid.UUID | None = None
    project_ids: list[uuid.UUID] = []
    user_ids = [owner.id]
    login_keys = [
        rate_limit_key(settings, "login-username", username),
        rate_limit_key(settings, "login-ip", "testclient"),
        rate_limit_key(settings, "project-create", str(owner.id)),
        rate_limit_key(settings, "project-document-write", str(owner.id)),
    ]
    workspace_parent = TemporaryDirectory(prefix="impostr-pg-revision-")
    workspace_root = Path(workspace_parent.name) / "workspaces"

    try:
        with Session(engine) as db, db.begin():
            db.add(owner)

        first_app = create_app(engine, settings, workspace_root=workspace_root)
        second_app = create_app(engine, settings, workspace_root=workspace_root)
        with TestClient(first_app) as first_tab, TestClient(second_app) as second_tab:
            _login(first_tab, username, password)
            _login(second_tab, username, password)
            creation = first_tab.post(
                "/api/projects",
                json={"name": f"Concurrent plan {suffix}"},
                headers={
                    "Origin": settings.public_origin,
                    "X-CSRF-Token": first_tab.cookies.get("impostr_csrf", ""),
                },
            )
            assert creation.status_code == 201
            project_id = uuid.UUID(creation.json()["id"])
            project_ids.append(project_id)
            initial = first_tab.get(f"/api/projects/{project_id}/documents/project").json()
            assert initial["revision_number"] == 1

            start_together = Barrier(2)

            def save_from_tab(tab: TestClient, text: str):
                start_together.wait(timeout=10)
                return tab.put(
                    f"/api/projects/{project_id}/documents/project",
                    json={"expected_revision": 1, "content": text},
                    headers={
                        "Origin": settings.public_origin,
                        "X-CSRF-Token": tab.cookies.get("impostr_csrf", ""),
                    },
                )

            candidates = {
                "# Concurrent winner from A\n": first_tab,
                "# Concurrent winner from B\n": second_tab,
            }
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(save_from_tab, tab, text) for text, tab in candidates.items()
                ]
                outcomes = [future.result(timeout=20) for future in futures]

            assert sorted(response.status_code for response in outcomes) == [200, 409]
            conflict = next(response for response in outcomes if response.status_code == 409)
            assert conflict.json()["latest"]["revision_number"] == 2
            assert conflict.json()["latest"]["content"] in candidates
            current = first_tab.get(f"/api/projects/{project_id}/documents/project")
            assert current.status_code == 200
            winner_text = current.json()["content"]
            assert winner_text in candidates
            history = first_tab.get(f"/api/projects/{project_id}/documents/project/history")
            assert history.status_code == 200
            assert [item["revision_number"] for item in history.json()["revisions"]] == [2, 1]
            assert len(history.json()["proposals"]) == 1
            proposal_id = history.json()["proposals"][0]["id"]
            assert conflict.json()["proposal_id"] == proposal_id
            proposal = first_tab.get(
                f"/api/projects/{project_id}/documents/project/proposals/{proposal_id}"
            )
            assert proposal.status_code == 200
            losing_text = next(text for text in candidates if text != winner_text)
            assert proposal.json()["content"] == losing_text
            assert proposal.json()["expected_revision_number"] == 1
            assert proposal.json()["observed_revision_number"] == 2

        workspace_file = workspace_root / str(project_id) / "PROJECT.md"
        workspace_file.write_text("stale temporary workspace data", encoding="utf-8")
        with TestClient(
            create_app(engine, settings, workspace_root=workspace_root)
        ) as restarted_client:
            _login(restarted_client, username, password)
            restored = restarted_client.get(f"/api/projects/{project_id}/documents/project")
            recovered_proposal = restarted_client.get(
                f"/api/projects/{project_id}/documents/project/proposals/{proposal_id}"
            )
            assert restored.status_code == recovered_proposal.status_code == 200
            assert restored.json()["content"] == winner_text
            assert recovered_proposal.json()["content"] == losing_text
        assert workspace_file.read_text(encoding="utf-8") == winner_text

        with Session(engine) as db:
            document = db.scalar(
                select(ProjectDocument).where(
                    ProjectDocument.project_id == project_id,
                    ProjectDocument.kind == "project",
                )
            )
            assert document is not None and document.head_revision_number == 2
            revisions = list(
                db.scalars(
                    select(ProjectDocumentRevision).where(
                        ProjectDocumentRevision.document_id == document.id
                    )
                ).all()
            )
            proposals = list(
                db.scalars(
                    select(DocumentConflictProposal).where(
                        DocumentConflictProposal.document_id == document.id
                    )
                ).all()
            )
            assert len(revisions) == 2
            assert {
                revision.content for revision in revisions if revision.revision_number == 2
            } == {winner_text}
            assert len(proposals) == 1 and proposals[0].content == losing_text

        # Pause a save after its commit, before it obtains the mirror locks. A
        # second save can commit and mirror first; the delayed save must reread
        # the newer DB heads rather than writing its own stale submitted text.
        from app import project_documents as document_module

        original_mirror = document_module._mirror_locked_views
        first_committed = Event()
        release_first = Event()

        def delay_first_mirror(db, store, identifier):
            if not first_committed.is_set():
                first_committed.set()
                if not release_first.wait(timeout=20):
                    raise TimeoutError("Timed out waiting for concurrent mirror")
            return original_mirror(db, store, identifier)

        monkeypatch.setattr(document_module, "_mirror_locked_views", delay_first_mirror)
        with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as first_tab:
            with TestClient(
                create_app(engine, settings, workspace_root=workspace_root)
            ) as second_tab:
                _login(first_tab, username, password)
                _login(second_tab, username, password)

                def put(tab: TestClient, expected: int, content: str):
                    return tab.put(
                        f"/api/projects/{project_id}/documents/project",
                        json={"expected_revision": expected, "content": content},
                        headers={
                            "Origin": settings.public_origin,
                            "X-CSRF-Token": tab.cookies.get("impostr_csrf", ""),
                        },
                    )

                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="delayed-mirror") as pool:
                    try:
                        delayed = pool.submit(put, first_tab, 2, "# Delayed mirror text\n")
                        assert first_committed.wait(timeout=10)
                        latest_text = "# Later committed mirror text\n"
                        newer = put(second_tab, 3, latest_text)
                        assert newer.status_code == 200
                    finally:
                        release_first.set()
                    assert delayed.result(timeout=20).status_code == 200
                assert (workspace_root / str(project_id) / "PROJECT.md").read_text() == latest_text
                assert (
                    first_tab.get(f"/api/projects/{project_id}/documents/project").json()["content"]
                    == latest_text
                )

                # A GET that selected revision 4 before a PUT cannot publish
                # that old head after revision 5 commits, even across stores.
                original_write = document_module._mirror_project_documents
                original_load_document = document_module._load_document
                read_at_mirror = Event()
                release_read = Event()
                save_at_lock = Event()

                def pause_read_mirror(store, identifier, documents):
                    if not read_at_mirror.is_set():
                        read_at_mirror.set()
                        if not release_read.wait(timeout=20):
                            raise TimeoutError("Timed out waiting for the concurrent save")
                    return original_write(store, identifier, documents)

                def signal_save_lock(db, identifier, kind, *, for_update=False):
                    if for_update:
                        save_at_lock.set()
                    return original_load_document(db, identifier, kind, for_update=for_update)

                monkeypatch.setattr(document_module, "_mirror_project_documents", pause_read_mirror)
                monkeypatch.setattr(document_module, "_load_document", signal_save_lock)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    try:
                        old_read = pool.submit(
                            first_tab.get, f"/api/projects/{project_id}/documents/project"
                        )
                        assert read_at_mirror.wait(timeout=10)
                        newer_save = pool.submit(put, second_tab, 4, "# Newest DB head\n")
                        assert save_at_lock.wait(timeout=10)
                        assert not newer_save.done()
                    finally:
                        release_read.set()
                    assert old_read.result(timeout=20).status_code == 200
                    assert newer_save.result(timeout=20).status_code == 200
                assert (workspace_root / str(project_id) / "PROJECT.md").read_text() == (
                    "# Newest DB head\n"
                )
    finally:
        with Session(engine) as db, db.begin():
            audit_filter = AuditEvent.actor_user_id.in_(user_ids)
            if project_ids:
                audit_filter = audit_filter | AuditEvent.project_id.in_(project_ids)
            db.execute(delete(AuditEvent).where(audit_filter))
            if project_ids:
                db.execute(delete(Project).where(Project.id.in_(project_ids)))
            db.execute(delete(WebSession).where(WebSession.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(login_keys)))
        workspace_parent.cleanup()
        engine.dispose()


def test_postgres_proposal_cursor_survives_concurrent_insert_without_head_change() -> None:
    """Proposal pages stay stable when a stale writer inserts between requests."""
    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:16]
    username = f"it-proposals-{suffix}"
    password = "proposal pagination integration passphrase"
    owner_id = uuid.uuid4()
    now = datetime.now(UTC)
    owner = User(
        id=owner_id,
        username=username,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    project_ids: list[uuid.UUID] = []
    user_ids = [owner_id]
    login_keys = [
        rate_limit_key(settings, "login-username", username),
        rate_limit_key(settings, "login-ip", "testclient"),
        rate_limit_key(settings, "project-create", str(owner_id)),
        rate_limit_key(settings, "project-document-write", str(owner_id)),
    ]
    workspace_parent = TemporaryDirectory(prefix="impostr-pg-proposal-pages-")
    workspace_root = Path(workspace_parent.name) / "workspaces"

    try:
        with Session(engine) as db, db.begin():
            db.add(owner)

        app = create_app(engine, settings, workspace_root=workspace_root)
        with TestClient(app) as first_tab:
            with TestClient(
                create_app(engine, settings, workspace_root=workspace_root)
            ) as second_tab:
                _login(first_tab, username, password)
                _login(second_tab, username, password)
                creation = first_tab.post(
                    "/api/projects",
                    json={"name": f"Proposal pagination {suffix}"},
                    headers={
                        "Origin": settings.public_origin,
                        "X-CSRF-Token": first_tab.cookies.get("impostr_csrf", ""),
                    },
                )
                assert creation.status_code == 201
                project_id = uuid.UUID(creation.json()["id"])
                project_ids.append(project_id)
                document_path = f"/api/projects/{project_id}/documents/project"
                history_path = f"{document_path}/history"

                initial = first_tab.get(document_path)
                assert initial.status_code == 200
                saved = first_tab.put(
                    document_path,
                    json={"expected_revision": 1, "content": "# Stable PostgreSQL head\n"},
                    headers={
                        "Origin": settings.public_origin,
                        "X-CSRF-Token": first_tab.cookies.get("impostr_csrf", ""),
                    },
                )
                assert saved.status_code == 200
                assert saved.json()["revision_number"] == 2

                original_proposal_ids: set[str] = set()
                for index in range(5):
                    conflict = first_tab.put(
                        document_path,
                        json={
                            "expected_revision": 1,
                            "content": f"# Original PostgreSQL proposal {index}\n",
                        },
                        headers={
                            "Origin": settings.public_origin,
                            "X-CSRF-Token": first_tab.cookies.get("impostr_csrf", ""),
                        },
                    )
                    assert conflict.status_code == 409
                    original_proposal_ids.add(conflict.json()["proposal_id"])

                first_page_response = first_tab.get(history_path, params={"limit": 2})
                assert first_page_response.status_code == 200
                first_page = first_page_response.json()
                assert first_page["current_revision_number"] == 2
                assert len(first_page["proposals"]) == 2
                assert first_page["proposal_has_more"] is True
                cursor = first_page["proposal_next_cursor"]
                assert cursor == first_page["proposals"][-1]["id"]
                traversed_ids = [item["id"] for item in first_page["proposals"]]

                # A distinct PostgreSQL connection commits a new stale proposal
                # between pages, but must not shift any already visible row.
                concurrent_conflict = second_tab.put(
                    document_path,
                    json={"expected_revision": 1, "content": "# Concurrent proposal\n"},
                    headers={
                        "Origin": settings.public_origin,
                        "X-CSRF-Token": second_tab.cookies.get("impostr_csrf", ""),
                    },
                )
                assert concurrent_conflict.status_code == 409
                concurrent_proposal_id = concurrent_conflict.json()["proposal_id"]

                page_count = 0
                while first_page["proposal_has_more"]:
                    page_count += 1
                    assert page_count <= 10
                    next_page_response = first_tab.get(
                        history_path,
                        params={"limit": 2, "proposal_cursor": cursor},
                    )
                    assert next_page_response.status_code == 200
                    first_page = next_page_response.json()
                    assert first_page["current_revision_number"] == 2
                    traversed_ids.extend(item["id"] for item in first_page["proposals"])
                    cursor = first_page["proposal_next_cursor"]

                assert len(traversed_ids) == len(set(traversed_ids))
                assert original_proposal_ids.issubset(set(traversed_ids))
                assert set(traversed_ids).issubset(original_proposal_ids | {concurrent_proposal_id})

                refreshed = first_tab.get(history_path, params={"limit": 50})
                assert refreshed.status_code == 200
                refreshed_body = refreshed.json()
                assert refreshed_body["current_revision_number"] == 2
                assert concurrent_proposal_id in {
                    item["id"] for item in refreshed_body["proposals"]
                }

        with Session(engine) as db:
            document = db.scalar(
                select(ProjectDocument).where(
                    ProjectDocument.project_id == project_ids[0],
                    ProjectDocument.kind == "project",
                )
            )
            assert document is not None and document.head_revision_number == 2
            proposals = list(
                db.scalars(
                    select(DocumentConflictProposal).where(
                        DocumentConflictProposal.document_id == document.id
                    )
                ).all()
            )
            assert len(proposals) == len(original_proposal_ids) + 1
    finally:
        with Session(engine) as db, db.begin():
            audit_filter = AuditEvent.actor_user_id.in_(user_ids)
            if project_ids:
                audit_filter = audit_filter | AuditEvent.project_id.in_(project_ids)
            db.execute(delete(AuditEvent).where(audit_filter))
            if project_ids:
                db.execute(delete(Project).where(Project.id.in_(project_ids)))
            db.execute(delete(WebSession).where(WebSession.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(login_keys)))
        workspace_parent.cleanup()
        engine.dispose()


@pytest.mark.parametrize("operation", ["create", "save"])
def test_postgres_deactivation_after_limit_commit_rejects_write(monkeypatch, operation) -> None:
    from app import project_documents as document_module
    from app import projects as project_module

    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:16]
    admin_name, owner_name = f"it-admin-{suffix}", f"it-owner-{suffix}"
    password = "deactivation race passphrase"
    now = datetime.now(UTC)
    admin = User(
        id=uuid.uuid4(),
        username=admin_name,
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    owner = User(
        id=uuid.uuid4(),
        username=owner_name,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    owner_id = owner.id
    project_id = uuid.uuid4()
    project = Project(id=project_id, name="Existing race project", owner_user_id=owner_id)
    user_ids = [admin.id, owner.id]
    workspace_parent = TemporaryDirectory(prefix="impostr-pg-revocation-")
    paused = Event()
    release = Event()
    module = project_module if operation == "create" else document_module
    original_load = module.load_active_actor

    def pause_recheck(db, actor, *, for_update=False, **kwargs):
        if for_update and actor.id == owner_id:
            paused.set()
            if not release.wait(timeout=20):
                raise TimeoutError("Timed out waiting for account deactivation")
        return original_load(db, actor, for_update=for_update, **kwargs)

    try:
        with Session(engine) as db, db.begin():
            db.add_all([admin, owner])
            db.flush()
            db.add(project)
        monkeypatch.setattr(module, "load_active_actor", pause_recheck)
        with TestClient(
            create_app(engine, settings, workspace_root=Path(workspace_parent.name) / "ws")
        ) as owner_tab:
            with TestClient(create_app(engine, settings)) as admin_tab:
                _login(owner_tab, owner_name, password)
                _login(admin_tab, admin_name, password)
                if operation == "save":
                    original = owner_tab.get(f"/api/projects/{project_id}/documents/project").json()
                else:
                    original = None

                def attempt_write():
                    path = (
                        "/api/projects"
                        if operation == "create"
                        else f"/api/projects/{project_id}/documents/project"
                    )
                    body = (
                        {"name": f"Revoked project {suffix}"}
                        if operation == "create"
                        else {"expected_revision": 1, "content": "# Revoked edit\n"}
                    )
                    return (
                        owner_tab.post(
                            path,
                            json=body,
                            headers={
                                "Origin": settings.public_origin,
                                "X-CSRF-Token": owner_tab.cookies.get("impostr_csrf", ""),
                            },
                        )
                        if operation == "create"
                        else owner_tab.put(
                            path,
                            json=body,
                            headers={
                                "Origin": settings.public_origin,
                                "X-CSRF-Token": owner_tab.cookies.get("impostr_csrf", ""),
                            },
                        )
                    )

                with ThreadPoolExecutor(max_workers=1) as pool:
                    try:
                        pending = pool.submit(attempt_write)
                        assert paused.wait(timeout=10)
                        deactivated = admin_tab.post(
                            f"/api/admin/users/{owner_id}/deactivate",
                            headers={
                                "Origin": settings.public_origin,
                                "X-CSRF-Token": admin_tab.cookies.get("impostr_csrf", ""),
                            },
                        )
                        assert deactivated.status_code == 204
                    finally:
                        release.set()
                    assert pending.result(timeout=20).status_code == 401

        with Session(engine) as db:
            assert (
                db.scalar(select(Project.id).where(Project.name == f"Revoked project {suffix}"))
                is None
            )
            if original is not None:
                document = db.scalar(
                    select(ProjectDocument).where(
                        ProjectDocument.project_id == project_id,
                        ProjectDocument.kind == "project",
                    )
                )
                assert document is not None and document.head_revision_number == 1
    finally:
        release.set()
        keys = [
            rate_limit_key(settings, "login-username", name) for name in (admin_name, owner_name)
        ] + [
            rate_limit_key(settings, "login-ip", "testclient"),
            rate_limit_key(settings, "project-create", str(owner_id)),
            rate_limit_key(settings, "project-document-write", str(owner_id)),
        ]
        with Session(engine) as db, db.begin():
            db.execute(
                delete(AuditEvent).where(
                    AuditEvent.actor_user_id.in_(user_ids)
                    | AuditEvent.target_user_id.in_(user_ids)
                    | (AuditEvent.project_id == project_id)
                )
            )
            db.execute(delete(Project).where(Project.owner_user_id == owner_id))
            db.execute(delete(WebSession).where(WebSession.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(keys)))
        workspace_parent.cleanup()
        engine.dispose()


def test_postgres_history_head_and_revisions_stay_consistent_during_save(monkeypatch) -> None:
    from app import project_documents as document_module

    engine = _engine()
    settings = AppSettings.from_environment()
    username = f"it-history-{uuid.uuid4().hex[:16]}"
    password = "history race passphrase"
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    now = datetime.now(UTC)
    paused = Event()
    release = Event()
    save_at_lock = Event()
    original_load = document_module._load_document

    def pause_history(db, identifier, kind, *, for_update=False):
        if paused.is_set():
            save_at_lock.set()
        document = original_load(db, identifier, kind, for_update=for_update)
        if not paused.is_set():
            assert for_update
            paused.set()
            if not release.wait(timeout=20):
                raise TimeoutError("History lock was not released")
        return document

    try:
        with Session(engine) as db, db.begin():
            db.add(
                User(
                    id=user_id,
                    username=username,
                    password_hash=hash_password(password),
                    role="user",
                    is_active=True,
                    created_at=now,
                    password_changed_at=now,
                )
            )
            db.flush()
            db.add(Project(id=project_id, name="History race", owner_user_id=user_id))
        with TemporaryDirectory(prefix="impostr-pg-history-") as directory:
            app = create_app(engine, settings, workspace_root=Path(directory) / "ws")
            with TestClient(app) as first:
                with TestClient(app) as second:
                    _login(first, username, password)
                    _login(second, username, password)
                    monkeypatch.setattr(document_module, "_load_document", pause_history)

                    def save():
                        return second.put(
                            f"/api/projects/{project_id}/documents/project",
                            json={"expected_revision": 1, "content": "# New head\n"},
                            headers={
                                "Origin": settings.public_origin,
                                "X-CSRF-Token": second.cookies.get("impostr_csrf", ""),
                            },
                        )

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        try:
                            history = pool.submit(
                                first.get, f"/api/projects/{project_id}/documents/project/history"
                            )
                            assert paused.wait(timeout=10)
                            saved = pool.submit(save)
                            assert save_at_lock.wait(timeout=10)
                            # The history transaction must hold the head row until
                            # its revision queries have completed, not merely read it.
                            with pytest.raises(FutureTimeoutError):
                                saved.result(timeout=0.5)
                        finally:
                            release.set()
                        result = history.result(timeout=20)
                        assert result.status_code == 200
                        assert saved.result(timeout=20).status_code == 200
                    body = result.json()
                    assert body["current_revision_number"] >= max(
                        item["revision_number"] for item in body["revisions"]
                    )
    finally:
        release.set()
        with Session(engine) as db, db.begin():
            db.execute(delete(Project).where(Project.id == project_id))
            db.execute(delete(WebSession).where(WebSession.user_id == user_id))
            db.execute(delete(User).where(User.id == user_id))
            db.execute(
                delete(RateLimitBucket).where(
                    RateLimitBucket.key_hash.in_(
                        [
                            rate_limit_key(settings, "login-username", username),
                            rate_limit_key(settings, "login-ip", "testclient"),
                            rate_limit_key(settings, "project-document-write", str(user_id)),
                        ]
                    )
                )
            )
        engine.dispose()


def test_postgres_operator_bootstrap_and_recovery() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:16]
    username = f"it-bootstrap-{suffix}"
    initial_password = "initial integration passphrase"
    recovery_password = "recovered integration passphrase"
    admin_id: uuid.UUID | None = None
    initial_bootstrap_state: bool | None = None

    try:
        with Session(engine) as db:
            state = db.get(BootstrapState, 1)
            assert state is not None
            initial_bootstrap_state = state.completed
            assert not state.completed
            assert db.scalar(select(User.id).limit(1)) is None

        admin_id = bootstrap_admin(engine, username, initial_password)
        with Session(engine) as db:
            admin = db.get(User, admin_id)
            assert admin is not None and admin.is_active and admin.role == "admin"
            assert verify_password(admin.password_hash, initial_password)
            assert (
                db.scalar(
                    select(AuditEvent.id).where(AuditEvent.action == "operator.admin_bootstrap")
                )
                is not None
            )

        with pytest.raises(ValueError, match="already been completed"):
            bootstrap_admin(engine, f"another-{suffix}", "another integration passphrase")

        session_token_hash = token_hash(new_opaque_token())
        csrf_token_hash = token_hash(new_opaque_token())
        assert session_token_hash is not None and csrf_token_hash is not None
        with Session(engine) as db, db.begin():
            admin = db.get(User, admin_id)
            assert admin is not None
            admin.is_active = False
            db.add(
                WebSession(
                    token_hash=session_token_hash,
                    csrf_token_hash=csrf_token_hash,
                    user_id=admin_id,
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC),
                )
            )

        assert recover_admin(engine, username, recovery_password) == admin_id
        with Session(engine) as db:
            admin = db.get(User, admin_id)
            session = db.get(WebSession, session_token_hash)
            assert admin is not None and admin.is_active
            assert verify_password(admin.password_hash, recovery_password)
            assert session is not None and session.revoked_at is not None
            assert (
                db.scalar(
                    select(AuditEvent.id).where(AuditEvent.action == "operator.admin_recovery")
                )
                is not None
            )
    finally:
        if admin_id is not None:
            with Session(engine) as db, db.begin():
                db.execute(
                    delete(AuditEvent).where(
                        (AuditEvent.actor_user_id == admin_id)
                        | (AuditEvent.target_user_id == admin_id)
                    )
                )
                db.execute(delete(WebSession).where(WebSession.user_id == admin_id))
                db.execute(delete(User).where(User.id == admin_id))
                state = db.get(BootstrapState, 1)
                if state is not None and initial_bootstrap_state is not None:
                    state.completed = initial_bootstrap_state
                    state.completed_at = None
        engine.dispose()


def test_postgres_login_rechecks_password_after_waiting_for_user_lock(monkeypatch) -> None:
    """A login verified before an admin reset must not issue an old-password session."""
    from app import auth as auth_module

    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:16]
    admin_name = f"it-reset-admin-{suffix}"
    target_name = f"it-reset-user-{suffix}"
    admin_password = "admin race passphrase"
    old_password = "old race passphrase"
    new_password = "new race passphrase"
    now = datetime.now(UTC)
    admin = User(
        id=uuid.uuid4(),
        username=admin_name,
        password_hash=hash_password(admin_password),
        role="admin",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    target = User(
        id=uuid.uuid4(),
        username=target_name,
        password_hash=hash_password(old_password),
        role="user",
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    admin_id = admin.id
    target_id = target.id
    user_ids = [admin_id, target_id]
    verified_old_password = Event()
    release_login = Event()
    original_verify_password = auth_module.verify_password

    def pause_after_old_password_verification(password_hash: str, password: str) -> bool:
        matches = original_verify_password(password_hash, password)
        if password == old_password and matches:
            verified_old_password.set()
            if not release_login.wait(timeout=20):
                raise TimeoutError("Timed out waiting to resume the concurrent login")
        return matches

    try:
        with Session(engine) as db, db.begin():
            db.add_all([admin, target])

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            admin_client = TestClient(create_app(engine, settings))
            with admin_client:
                _login(admin_client, admin_name, admin_password)
                admin_csrf = admin_client.cookies.get("impostr_csrf")
                assert admin_csrf is not None

                monkeypatch.setattr(
                    auth_module,
                    "verify_password",
                    pause_after_old_password_verification,
                )

                def attempt_old_password_login() -> tuple[int, str | None]:
                    with TestClient(create_app(engine, settings)) as login_client:
                        csrf_response = login_client.get("/api/auth/csrf")
                        response = login_client.post(
                            "/api/auth/login",
                            json={"username": target_name, "password": old_password},
                            headers={
                                "Origin": settings.public_origin,
                                "X-CSRF-Token": csrf_response.json()["csrf_token"],
                            },
                        )
                        return response.status_code, login_client.cookies.get("impostr_session")

                login_future = pool.submit(attempt_old_password_login)
                assert verified_old_password.wait(timeout=10), "login did not reach password verify"
                reset = admin_client.post(
                    f"/api/admin/users/{target_id}/reset-password",
                    json={"password": new_password},
                    headers={
                        "Origin": settings.public_origin,
                        "X-CSRF-Token": admin_csrf,
                    },
                )
                assert reset.status_code == 204
                release_login.set()
                login_status, session_cookie = login_future.result(timeout=20)

            assert login_status == 401
            assert session_cookie is None
        finally:
            release_login.set()
            pool.shutdown(wait=True, cancel_futures=True)

        with Session(engine) as db:
            account = db.get(User, target_id)
            assert account is not None and verify_password(account.password_hash, new_password)
            assert (
                db.scalar(select(WebSession.token_hash).where(WebSession.user_id == target_id))
                is None
            )

        with TestClient(create_app(engine, settings)) as fresh_client:
            csrf_response = fresh_client.get("/api/auth/csrf")
            old_login = fresh_client.post(
                "/api/auth/login",
                json={"username": target_name, "password": old_password},
                headers={
                    "Origin": settings.public_origin,
                    "X-CSRF-Token": csrf_response.json()["csrf_token"],
                },
            )
            assert old_login.status_code == 401

            csrf_response = fresh_client.get("/api/auth/csrf")
            new_login = fresh_client.post(
                "/api/auth/login",
                json={"username": target_name, "password": new_password},
                headers={
                    "Origin": settings.public_origin,
                    "X-CSRF-Token": csrf_response.json()["csrf_token"],
                },
            )
            assert new_login.status_code == 200
    finally:
        release_login.set()
        login_keys = [
            rate_limit_key(settings, "login-username", admin_name),
            rate_limit_key(settings, "login-username", target_name),
            rate_limit_key(settings, "login-ip", "testclient"),
            rate_limit_key(settings, "admin-credential-change", f"{admin_id}:testclient"),
        ]
        with Session(engine) as db, db.begin():
            db.execute(
                delete(AuditEvent).where(
                    (AuditEvent.actor_user_id.in_(user_ids))
                    | (AuditEvent.target_user_id.in_(user_ids))
                )
            )
            db.execute(delete(WebSession).where(WebSession.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
            db.execute(delete(RateLimitBucket).where(RateLimitBucket.key_hash.in_(login_keys)))
        engine.dispose()


def test_postgres_document_migration_preserves_metadata_only_projects(tmp_path: Path) -> None:
    """Upgrade the real PostgreSQL schema with duplicate legacy names intact."""
    engine = _engine()
    settings = AppSettings.from_environment()
    suffix = uuid.uuid4().hex[:12]
    user_id = uuid.uuid4()
    project_ids = [uuid.uuid4() for _ in range(4)]
    owner_name = f"it-legacy-{suffix}"
    now = datetime.now(UTC)
    workspace_root = tmp_path / "postgres-legacy-workspaces"
    api_directory = Path(__file__).resolve().parents[1]
    migration_config = Config(str(api_directory / "alembic.ini"))
    migration_config.set_main_option("script_location", str(api_directory / "migrations"))
    schema_is_head = True

    try:
        with engine.begin() as connection:
            migration_config.attributes["connection"] = connection
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260930_0006"
            )
            assert connection.scalar(select(User.id).limit(1)) is None
            assert connection.scalar(select(Project.id).limit(1)) is None
            command.downgrade(migration_config, "20260925_0002")
            schema_is_head = False

        with engine.begin() as connection:
            metadata = MetaData()
            users = Table("users", metadata, autoload_with=connection)
            projects = Table("projects", metadata, autoload_with=connection)
            connection.execute(
                users.insert(),
                {
                    "id": user_id,
                    "username": owner_name,
                    "password_hash": "migration-test-only-hash",
                    "role": "user",
                    "is_active": True,
                    "created_at": now,
                    "password_changed_at": now,
                },
            )
            connection.execute(
                projects.insert(),
                [
                    {
                        "id": project_id,
                        "name": name,
                        "owner_user_id": user_id,
                        "created_at": now,
                    }
                    for project_id, name in zip(
                        project_ids,
                        (f"Legacy plan {suffix}", f"legacy PLAN {suffix}", "ﷺ" * 120, "ß" * 120),
                        strict=True,
                    )
                ],
            )

        with engine.begin() as connection:
            migration_config.attributes["connection"] = connection
            command.upgrade(migration_config, "20260925_0003")
            # Simulate a pre-repair v0003 installation with an expanded raw key.
            connection.execute(
                text("UPDATE projects SET name_key = :key WHERE id = :id"),
                {"key": "ss" * 120, "id": project_ids[3]},
            )
            command.upgrade(migration_config, "head")
            schema_is_head = True
            columns = {
                column["name"]: column for column in inspect(connection).get_columns("projects")
            }
            assert columns["name_key"]["nullable"] is False
            migrated = connection.execute(
                select(Project.id, Project.name, Project.name_key).order_by(Project.id)
            ).all()
            assert {row.id for row in migrated} == set(project_ids)
            assert {row.name for row in migrated} == {
                f"Legacy plan {suffix}",
                f"legacy PLAN {suffix}",
                "ﷺ" * 120,
                "ß" * 120,
            }
            assert len({row.name_key for row in migrated}) == 4
            assert all(len(row.name_key) == 64 for row in migrated)
            assert any(row.name_key == project_name_key("ﷺ" * 120) for row in migrated)
            assert any(
                row.name_key == project_name_key(f"Legacy plan {suffix}") for row in migrated
            )

        with TestClient(create_app(engine, settings, workspace_root=workspace_root)):
            with Session(engine) as db:
                legacy_projects = list(
                    db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
                )
                assert {project.id for project in legacy_projects} == set(project_ids)
                assert all(project.owner_user_id == user_id for project in legacy_projects)
                assert (
                    len(
                        list(
                            db.scalars(
                                select(ProjectDocument).where(
                                    ProjectDocument.project_id.in_(project_ids)
                                )
                            ).all()
                        )
                    )
                    == 12
                )
                assert (
                    len(
                        list(
                            db.scalars(
                                select(ProjectDocumentRevision)
                                .join(
                                    ProjectDocument,
                                    ProjectDocumentRevision.document_id == ProjectDocument.id,
                                )
                                .where(ProjectDocument.project_id.in_(project_ids))
                            ).all()
                        )
                    )
                    == 12
                )
            assert not workspace_root.exists()
    finally:
        if not schema_is_head:
            with engine.begin() as connection:
                migration_config.attributes["connection"] = connection
                command.upgrade(migration_config, "head")
        with Session(engine) as db, db.begin():
            db.execute(delete(AuditEvent).where(AuditEvent.project_id.in_(project_ids)))
            db.execute(delete(Project).where(Project.id.in_(project_ids)))
            db.execute(delete(User).where(User.id == user_id))
        engine.dispose()
