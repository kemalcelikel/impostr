from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import project_documents as project_documents_module
from app import projects as projects_module
from app.config import AppSettings
from app.main import create_app
from app.models import (
    AuditEvent,
    DocumentConflictProposal,
    ProjectDocument,
    ProjectDocumentRevision,
)
from app.project_names import project_name_key
from app.project_templates import default_template_root
from app.rate_limit import RateLimitDecision, consume_rate_bucket
from app.workspaces import MAX_CACHED_PROJECTS

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
    workspace_root: Path,
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

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as bob_client:
        _login(bob_client, "bob", "correct horse battery")
        bob_listing = bob_client.get("/api/projects")
        denied = bob_client.get(f"/api/projects/{alice_project_id}")
        assert [project["id"] for project in bob_listing.json()] == [str(bob_project_id)]
        assert denied.status_code == 404
        assert denied.json() == {"detail": "Project not found"}

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as admin_client:
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


def test_project_creation_seeds_hashed_root_templates_and_private_workspace(
    client: TestClient,
    settings: AppSettings,
    account_factory,
    workspace_root: Path,
) -> None:
    alice_id = account_factory("alice", "correct horse battery")
    bob_id = account_factory("bob", "correct horse battery")
    _login(client, "alice", "correct horse battery")

    for invalid_name in ("", "   ", "..", "../escape", "folder/name", r"folder\name", "x" * 121):
        response = client.post(
            "/api/projects",
            json={"name": invalid_name},
            headers={
                "Origin": PUBLIC_ORIGIN,
                "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
            },
        )
        assert response.status_code == 422

    created = client.post(
        "/api/projects",
        json={"name": "  A Useful Plan  "},
        headers={
            "Origin": PUBLIC_ORIGIN,
            "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
        },
    )
    assert created.status_code == 201
    project = created.json()
    project_id = uuid.UUID(project["id"])
    assert project["name"] == "A Useful Plan"
    assert project["owner_user_id"] == str(alice_id)
    assert uuid.UUID(project["id"]).version == 4
    created_at = datetime.fromisoformat(project["created_at"].replace("Z", "+00:00"))
    assert created_at.tzinfo is not None and created_at.utcoffset() == UTC.utcoffset(created_at)

    documents = client.get(f"/api/projects/{project_id}/documents")
    assert documents.status_code == 200
    by_kind = {document["kind"]: document for document in documents.json()}
    expected = {
        "project": "PROJECT.md.example",
        "agents": "AGENTS.md.example",
        "backlog": "BACKLOG.md.example",
    }
    repository_root = default_template_root()
    assert set(by_kind) == set(expected)
    for kind, source in expected.items():
        source_bytes = (repository_root / source).read_bytes()
        digest = hashlib.sha256(source_bytes).hexdigest()
        document = by_kind[kind]
        assert document["revision_number"] == 1
        assert document["origin"] == "template"
        assert document["template_source"] == source
        assert document["template_sha256"] == digest
        assert document["content_sha256"] == digest
        assert document["content"].encode("utf-8") == source_bytes
        assert document["author_user_id"] is None
        assert (
            workspace_root / str(project_id) / document["filename"]
        ).read_bytes() == source_bytes

    duplicate = client.post(
        "/api/projects",
        json={"name": "a useful plan"},
        headers={
            "Origin": PUBLIC_ORIGIN,
            "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "detail": "A project with this name already exists in your workspace."
    }

    with TestClient(
        create_app(
            client.app.state.database_engine,
            settings,
            workspace_root=workspace_root,
        )
    ) as bob_client:
        _login(bob_client, "bob", "correct horse battery")
        bob_project = bob_client.post(
            "/api/projects",
            json={"name": "A Useful Plan"},
            headers={
                "Origin": PUBLIC_ORIGIN,
                "X-CSRF-Token": bob_client.cookies.get("impostr_csrf", ""),
            },
        )
        assert bob_project.status_code == 201
        assert bob_project.json()["owner_user_id"] == str(bob_id)
        assert bob_project.json()["id"] != str(project_id)

    assert sorted(path.name for path in (workspace_root / str(project_id)).iterdir()) == [
        "AGENTS.md",
        "BACKLOG.md",
        "PROJECT.md",
    ]
    assert not (workspace_root.parent / "escape").exists()


def test_expanding_unicode_project_names_have_bounded_collision_keys(
    client: TestClient, account_factory, engine
) -> None:
    account_factory("alice", "correct horse battery")
    _login(client, "alice", "correct horse battery")
    headers = {
        "Origin": PUBLIC_ORIGIN,
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }
    # U+FDFA compatibility decomposition is much longer than one codepoint.
    name = "ﷺ" * 120
    assert len(name) == 120
    assert len(project_name_key(name)) == 64
    created = client.post("/api/projects", json={"name": name}, headers=headers)
    assert created.status_code == 201
    with Session(engine) as db:
        stored = db.get(projects_module.Project, uuid.UUID(created.json()["id"]))
        assert stored is not None and stored.name_key == project_name_key(name)
    duplicate = client.post("/api/projects", json={"name": name}, headers=headers)
    assert duplicate.status_code == 409
    folded = client.post("/api/projects", json={"name": "ß" * 60}, headers=headers)
    assert folded.status_code == 201
    equivalent = client.post("/api/projects", json={"name": "SS" * 60}, headers=headers)
    assert equivalent.status_code == 409


def test_startup_lazily_mirrors_only_the_authorized_project(
    engine,
    settings: AppSettings,
    account_factory,
    project_factory,
    workspace_root: Path,
) -> None:
    owner_id = account_factory("alice", "correct horse battery")
    project_ids = [
        project_factory(owner_id, f"Legacy plan {index}")
        for index in range(MAX_CACHED_PROJECTS + 1)
    ]

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as lazy_client:
        # Even more legacy projects than the bounded cache can hold do not get
        # eagerly copied to tmpfs during app startup.
        assert not workspace_root.exists()
        _login(lazy_client, "alice", "correct horse battery")
        documents = lazy_client.get(f"/api/projects/{project_ids[0]}/documents")

        assert documents.status_code == 200
        assert {document["kind"] for document in documents.json()} == {
            "project",
            "agents",
            "backlog",
        }
        assert [path.name for path in workspace_root.iterdir()] == [str(project_ids[0])]
        assert sorted(path.name for path in (workspace_root / str(project_ids[0])).iterdir()) == [
            "AGENTS.md",
            "BACKLOG.md",
            "PROJECT.md",
        ]

        # A single-file GET also materializes a *complete* proposal surface.
        second = lazy_client.get(f"/api/projects/{project_ids[1]}/documents/project")
        assert second.status_code == 200
        assert sorted(path.name for path in (workspace_root / str(project_ids[1])).iterdir()) == [
            "AGENTS.md",
            "BACKLOG.md",
            "PROJECT.md",
        ]


def test_stale_document_edit_is_rejected_but_both_texts_survive_reload(
    client: TestClient,
    engine,
    settings: AppSettings,
    account_factory,
    workspace_root: Path,
) -> None:
    account_factory("alice", "correct horse battery")
    _login(client, "alice", "correct horse battery")
    headers = {
        "Origin": PUBLIC_ORIGIN,
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }
    created = client.post("/api/projects", json={"name": "Versioned plan"}, headers=headers)
    project_id = created.json()["id"]

    initial = client.get(f"/api/projects/{project_id}/documents/project").json()
    winner_text = "# Winning revision\n\nSaved in tab one.\n"
    winner = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": initial["revision_number"], "content": winner_text},
        headers=headers,
    )
    assert winner.status_code == 200
    assert winner.json()["revision_number"] == 2
    assert winner.json()["origin"] == "human"

    attempted_text = "# Attempted stale revision\n\nKeep this for review.\n"
    stale = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": initial["revision_number"], "content": attempted_text},
        headers=headers,
    )
    assert stale.status_code == 409
    assert "saved as a conflict proposal" in stale.json()["detail"]
    assert stale.json()["latest"] == winner.json()

    history_response = client.get(f"/api/projects/{project_id}/documents/project/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert [item["revision_number"] for item in history["revisions"]] == [2, 1]
    assert len(history["proposals"]) == 1
    proposal_id = history["proposals"][0]["id"]
    assert stale.json()["proposal_id"] == proposal_id
    revision_one = client.get(f"/api/projects/{project_id}/documents/project/revisions/1").json()
    revision_two = client.get(f"/api/projects/{project_id}/documents/project/revisions/2").json()
    proposal = client.get(
        f"/api/projects/{project_id}/documents/project/proposals/{proposal_id}"
    ).json()
    assert revision_one["content"] != winner_text
    assert revision_two["content"] == winner_text
    assert proposal["content"] == attempted_text
    assert proposal["expected_revision_number"] == 1
    assert proposal["observed_revision_number"] == 2

    workspace_file = workspace_root / project_id / "PROJECT.md"
    workspace_file.write_text("untrusted workspace contents", encoding="utf-8")
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as reloaded_client:
        _login(reloaded_client, "alice", "correct horse battery")
        latest = reloaded_client.get(f"/api/projects/{project_id}/documents/project").json()
        recovered_proposal = reloaded_client.get(
            f"/api/projects/{project_id}/documents/project/proposals/{proposal_id}"
        ).json()
        assert latest["content"] == winner_text
        assert recovered_proposal["content"] == attempted_text
    assert workspace_file.read_text(encoding="utf-8") == winner_text

    with Session(engine) as db:
        document = db.scalar(
            select(ProjectDocument).where(
                ProjectDocument.project_id == uuid.UUID(project_id),
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
        assert len(proposals) == 1


def test_conflict_history_cursor_survives_a_new_proposal_without_head_change(
    client: TestClient,
    engine,
    settings: AppSettings,
    account_factory,
    workspace_root: Path,
) -> None:
    account_factory("alice", "correct horse battery")
    _login(client, "alice", "correct horse battery")
    headers = {
        "Origin": PUBLIC_ORIGIN,
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }
    created = client.post("/api/projects", json={"name": "Proposal pagination"}, headers=headers)
    assert created.status_code == 201
    project_id = created.json()["id"]
    document_path = f"/api/projects/{project_id}/documents/project"
    history_path = f"{document_path}/history"

    initial = client.get(document_path).json()
    winner = client.put(
        document_path,
        json={"expected_revision": initial["revision_number"], "content": "# Stable head\n"},
        headers=headers,
    )
    assert winner.status_code == 200
    assert winner.json()["revision_number"] == 2

    original_proposal_ids: set[str] = set()
    for index in range(5):
        conflict = client.put(
            document_path,
            json={
                "expected_revision": 1,
                "content": f"# Previously stored proposal {index}\n",
            },
            headers=headers,
        )
        assert conflict.status_code == 409
        original_proposal_ids.add(conflict.json()["proposal_id"])

    first_page_response = client.get(history_path, params={"limit": 2})
    assert first_page_response.status_code == 200
    first_page = first_page_response.json()
    assert first_page["current_revision_number"] == 2
    assert len(first_page["proposals"]) == 2
    assert first_page["proposal_has_more"] is True
    cursor = first_page["proposal_next_cursor"]
    assert cursor == first_page["proposals"][-1]["id"]
    traversed_ids = [item["id"] for item in first_page["proposals"]]

    # Use an independent signed-in client to insert a proposal between page
    # requests, as another stale writer can do without advancing the head.
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as second_tab:
        _login(second_tab, "alice", "correct horse battery")
        concurrent_conflict = second_tab.put(
            document_path,
            json={"expected_revision": 1, "content": "# Arrived between pages\n"},
            headers={
                "Origin": PUBLIC_ORIGIN,
                "X-CSRF-Token": second_tab.cookies.get("impostr_csrf", ""),
            },
        )
    assert concurrent_conflict.status_code == 409
    concurrent_proposal_id = concurrent_conflict.json()["proposal_id"]

    page_count = 0
    while first_page["proposal_has_more"]:
        page_count += 1
        assert page_count <= 10, "proposal pagination did not advance its stable cursor"
        next_page_response = client.get(
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

    # A fresh history load starts at the new head of the proposal ordering.
    refreshed = client.get(history_path, params={"limit": 50})
    assert refreshed.status_code == 200
    refreshed_body = refreshed.json()
    assert refreshed_body["current_revision_number"] == 2
    assert concurrent_proposal_id in {item["id"] for item in refreshed_body["proposals"]}
    assert client.get(document_path).json()["revision_number"] == 2


def test_project_content_history_and_conflict_proposals_are_private_and_admin_reads_audited(
    client: TestClient,
    engine,
    settings: AppSettings,
    account_factory,
    workspace_root: Path,
) -> None:
    owner_id = account_factory("owner", "correct horse battery")
    admin_id = account_factory("admin", "correct horse battery", role="admin")
    account_factory("other", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    headers = {
        "Origin": PUBLIC_ORIGIN,
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }
    project_id = client.post(
        "/api/projects", json={"name": "Private drafts"}, headers=headers
    ).json()["id"]
    initial = client.get(f"/api/projects/{project_id}/documents/project").json()
    assert (
        client.put(
            f"/api/projects/{project_id}/documents/project",
            json={"expected_revision": initial["revision_number"], "content": "winning secret"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/projects/{project_id}/documents/project",
            json={"expected_revision": initial["revision_number"], "content": "rejected secret"},
            headers=headers,
        ).status_code
        == 409
    )
    history = client.get(f"/api/projects/{project_id}/documents/project/history").json()
    proposal_id = history["proposals"][0]["id"]

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as other_client:
        _login(other_client, "other", "correct horse battery")
        denied_requests = [
            other_client.get(f"/api/projects/{project_id}/documents"),
            other_client.get(f"/api/projects/{project_id}/documents/project"),
            other_client.get(f"/api/projects/{project_id}/documents/project/history"),
            other_client.get(
                f"/api/projects/{project_id}/documents/project/history"
                f"?proposal_cursor={proposal_id}"
            ),
            other_client.get(f"/api/projects/{project_id}/documents/project/revisions/2"),
            other_client.get(
                f"/api/projects/{project_id}/documents/project/proposals/{proposal_id}"
            ),
            other_client.put(
                f"/api/projects/{project_id}/documents/project",
                json={"expected_revision": 2, "content": "unauthorized"},
                headers={
                    "Origin": PUBLIC_ORIGIN,
                    "X-CSRF-Token": other_client.cookies.get("impostr_csrf", ""),
                },
            ),
        ]
    assert all(response.status_code == 404 for response in denied_requests)
    assert all("winning secret" not in response.text for response in denied_requests)
    assert all("rejected secret" not in response.text for response in denied_requests)

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as admin_client:
        _login(admin_client, "admin", "correct horse battery")
        assert admin_client.get(f"/api/projects/{project_id}/documents").status_code == 200
        assert (
            admin_client.get(f"/api/projects/{project_id}/documents/project/history").status_code
            == 200
        )
        assert (
            admin_client.get(f"/api/projects/{project_id}/documents/project/revisions/2").json()[
                "content"
            ]
            == "winning secret"
        )
        assert (
            admin_client.get(
                f"/api/projects/{project_id}/documents/project/proposals/{proposal_id}"
            ).json()["content"]
            == "rejected secret"
        )

    with Session(engine) as db:
        admin_reads = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.actor_user_id == admin_id,
                    AuditEvent.project_id == uuid.UUID(project_id),
                )
            ).all()
        )
    read_actions = {event.action for event in admin_reads}
    assert {
        "admin.project.documents.read",
        "admin.project.document_history.read",
        "admin.project.document_revision.read",
        "admin.project.document_proposal.read",
    }.issubset(read_actions)
    assert all(
        "winning secret" not in str(event.details) and "rejected secret" not in str(event.details)
        for event in admin_reads
    )
    assert owner_id != admin_id


def test_project_mutations_retain_origin_csrf_and_payload_boundaries(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("alice", "correct horse battery")
    _login(client, "alice", "correct horse battery")
    no_csrf = client.post(
        "/api/projects",
        json={"name": "No CSRF"},
        headers={"Origin": PUBLIC_ORIGIN},
    )
    assert no_csrf.status_code == 403
    no_origin = client.post(
        "/api/projects",
        json={"name": "No Origin"},
        headers={"X-CSRF-Token": client.cookies.get("impostr_csrf", "")},
    )
    assert no_origin.status_code == 403

    csrf = client.cookies.get("impostr_csrf", "")
    created = client.post(
        "/api/projects",
        json={"name": "Boundary test"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    project_id = created.json()["id"]
    bad_origin = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 1, "content": "never written"},
        headers={"Origin": "https://attacker.invalid", "X-CSRF-Token": csrf},
    )
    no_write_csrf = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 1, "content": "never written"},
        headers={"Origin": PUBLIC_ORIGIN},
    )
    forged_origin = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 1, "content": "not an agent", "origin": "agent"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    missing_expected_revision = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"content": "an expected revision is required"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    out_of_range_revision = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 2_147_483_648, "content": "not a database revision"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    too_large = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 1, "content": "x" * (128 * 1024 + 1)},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    invalid_revision_lookup = client.get(
        f"/api/projects/{project_id}/documents/project/revisions/2147483648"
    )
    assert bad_origin.status_code == no_write_csrf.status_code == 403
    assert all(
        response.status_code == 422
        for response in (
            forged_origin,
            missing_expected_revision,
            out_of_range_revision,
            invalid_revision_lookup,
        )
    )
    assert too_large.status_code == 422
    assert client.get("/api/agents").status_code == 404
    assert (
        client.get(f"/api/projects/{project_id}/documents/project").json()["revision_number"] == 1
    )


def test_project_creation_and_document_writes_are_rate_limited(
    client: TestClient,
    account_factory,
    monkeypatch,
) -> None:
    account_factory("alice", "correct horse battery")
    _login(client, "alice", "correct horse battery")
    headers = {
        "Origin": PUBLIC_ORIGIN,
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }

    def deny_rate_limit(*_args: object, **_kwargs: object) -> RateLimitDecision:
        return RateLimitDecision(allowed=False, retry_after_seconds=90)

    monkeypatch.setattr(projects_module, "consume_rate_bucket", deny_rate_limit)
    denied_creation = client.post(
        "/api/projects",
        json={"name": "Too many plans"},
        headers=headers,
    )
    assert denied_creation.status_code == 429
    assert denied_creation.headers["Retry-After"] == "90"
    assert client.get("/api/projects").json() == []

    monkeypatch.setattr(projects_module, "consume_rate_bucket", consume_rate_bucket)
    created = client.post(
        "/api/projects",
        json={"name": "Rate-limited drafts"},
        headers=headers,
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    monkeypatch.setattr(project_documents_module, "consume_rate_bucket", deny_rate_limit)
    denied_write = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 1, "content": "This must not become a proposal."},
        headers=headers,
    )
    assert denied_write.status_code == 429
    assert denied_write.headers["Retry-After"] == "90"
    assert (
        client.get(f"/api/projects/{project_id}/documents/project").json()["revision_number"] == 1
    )
    assert (
        client.get(f"/api/projects/{project_id}/documents/project/history").json()["proposals"]
        == []
    )
