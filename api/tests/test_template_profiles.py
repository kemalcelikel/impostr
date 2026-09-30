from __future__ import annotations

import hashlib
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from legacy_templates import legacy_templates
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.document_contract import DOCUMENT_KINDS, TEMPLATE_SOURCES
from app.main import create_app
from app.models import ProjectApprovalManifest, ProjectDocument, ProjectDocumentRevision
from app.project_documents import seed_legacy_project_documents
from app.project_templates import TemplateBundleError, default_template_root, load_project_templates
from app.task_sections import extract_task_sections
from app.template_profiles import SUPPORTED_STARTERS, resolve_template_profile

ORIGIN = "http://127.0.0.1:8080"
PROJECT = """# Fieldnotes

## Purpose and scope
Fieldnotes lets researchers keep private observations on a local computer.
- In scope: Save and search observations.
- Later/out of scope: Shared public publishing.

## Important behavior
| Workflow | Expected result | Important rules/failures |
|---|---|---|
| Save observation | Saved text remains searchable | Empty text returns an error |
- Domain terms and examples: Observation means one dated note.
- Important data/access rules: Only the local owner reads observations.

## Stack and architecture
- Runtime/framework/package manager: Python 3.12 with locked pip dependencies.
- Storage/services: SQLite database, no external services.
- Structure/data flow: CLI passes validated text to storage.py.
- Existing implementation vs planned changes: New command-line application.

## Contracts and constraints
- Important API/schema/file-format contracts: UTF-8 text observations.
- Cross-service dependencies/compatibility: None.
- UI direction/components/devices: None; this is a CLI.
- Security/data/operating limits: Local owner data stays on disk.
- Migration/performance/deployment requirements: None.

## Decisions still needed
None.

## Completion
Saving and searching a note meets the task acceptance criteria.
"""
AGENTS = """# Agent guide: Fieldnotes

## Project context
- Product/architecture: PROJECT.md. Active tasks: BACKLOG.md.
- Important contract/design references: None.
- Coding conventions and protected/generated paths: PEP 8; do not edit generated schema files.
- Dependency/migration rules: Pin dependencies; version storage changes.
- Environment limits: Synthetic local observations only; no external network.

## Commands
| Purpose | Directory | Command | When to use |
|---|---|---|---|
| Setup | . | python -m venv .venv | Before development |
| Run app | . | python -m fieldnotes | Local development |
| Focused tests | . | python -m pytest tests/test_notes.py | Changed note behavior |
| Type/compile/lint | . | None | No separate checker selected |
- UI URL/login/representative viewport: None.
- Essential task-level gates: Save and search regression tests.
- CI/release-only checks: None.

## Testing and review
Check the main changed behavior and realistic failures that matter.

## Execution and Git
The owner chooses ready work; contributors leave commits to the coordinator.
- Git workflow: Work on the existing local branch; no push or merge.

## Completion and communication
Report changed paths and focused checks in one brief response.
"""
BACKLOG = """# Backlog: Fieldnotes

## [ ] TASK-001 — Save one observation
Depends on: None

Persist validated text in storage.py; exclude public publishing.

Acceptance:
- Saved observations can be searched after reopening.
- Empty text is rejected.

Verification: Run python -m pytest tests/test_notes.py.

## [-] TASK-002 — Review saved observations
Depends on: TASK-001

Review the stored notes with the owner.
Acceptance:
- The owner can inspect saved notes.
Verification: Inspect one synthetic observation.
"""


def login(client, name):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={"username": name, "password": "synthetic password only"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200


def headers(client):
    return {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("impostr_csrf", "")}


def prepare(client, account_factory):
    account_factory("profile-owner", "synthetic password only")
    login(client, "profile-owner")
    created = client.post("/api/projects", json={"name": "Fieldnotes"}, headers=headers(client))
    assert created.status_code == 201
    project_id = created.json()["id"]
    for kind, content in zip(DOCUMENT_KINDS, (PROJECT, AGENTS, BACKLOG), strict=True):
        saved = client.put(
            f"/api/projects/{project_id}/documents/{kind}",
            json={"expected_revision": 1, "content": content},
            headers=headers(client),
        )
        assert saved.status_code == 200, saved.text
    return project_id


def approve_pair(client, project_id):
    return client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json={"expected_project_revision": 2, "expected_agents_revision": 2},
        headers=headers(client),
    )


def approve_final(client, project_id, pair_id, revision=2):
    return client.post(
        f"/api/projects/{project_id}/final-approval",
        json={"expected_pair_approval_id": pair_id, "expected_backlog_revision": revision},
        headers=headers(client),
    )


def test_catalog_matches_frozen_legacy_and_actual_nested_bytes():
    old = legacy_templates()
    new = load_project_templates(default_template_root())
    for profile, templates in (("legacy", old), ("simplified", new)):
        assert (
            tuple((templates[k].source, templates[k].sha256) for k in DOCUMENT_KINDS)
            == SUPPORTED_STARTERS[profile]
        )
        for template in templates.values():
            assert hashlib.sha256(template.content.encode()).hexdigest() == template.sha256
    assert {template.source for template in new.values()} == set(TEMPLATE_SOURCES.values())


def test_compact_evidence_keeps_inline_markdown_and_rejects_hidden_scope_boundary():
    sections = extract_task_sections(
        "Depends on: None\n\nImplement notes.\nAcceptance:\n- Save notes.\n"
        "**Verification:** **Run** `python -m pytest`.\n",
        introductory_scope=True,
    )
    assert sections.scope == ("Implement notes.",)
    assert sections.verification == ("**Run** `python -m pytest`.",)
    sections = extract_task_sections(
        "Depends on: None\n<!-- gap -->\nTASK-005\nAcceptance:\n- Save notes.\n",
        introductory_scope=True,
    )
    assert sections.scope == ()


def test_discovery_rejects_missing_symlink_and_oversized_inputs(tmp_path):
    templates = load_project_templates(default_template_root())
    root = tmp_path / "bundle"
    (root / "overnight-agent").mkdir(parents=True)
    for template in templates.values():
        (root / template.source).write_text(template.content)
    path = root / TEMPLATE_SOURCES["project"]
    path.unlink()
    with pytest.raises(TemplateBundleError):
        load_project_templates(root)
    path.write_text(templates["project"].content + "\nAn unreviewed version.\n")
    with pytest.raises(TemplateBundleError, match="version is not supported"):
        load_project_templates(root)
    path.unlink()
    path.symlink_to(default_template_root() / TEMPLATE_SOURCES["project"])
    with pytest.raises(TemplateBundleError):
        load_project_templates(root)
    path.unlink()
    path.write_bytes(b"x" * (128 * 1024 + 1))
    with pytest.raises(TemplateBundleError):
        load_project_templates(root)


def test_simplified_approval_exact_download_restart_and_task_edit(
    client, engine, settings, workspace_root, account_factory
):
    project_id = prepare(client, account_factory)
    tasks = client.get(f"/api/projects/{project_id}/backlog/tasks").json()
    assert (
        tasks["tasks"][0]["acceptance"]
        == "- Saved observations can be searched after reopening.\n- Empty text is rejected."
    )
    assert tasks["tasks"][0]["verification"] == "Run python -m pytest tests/test_notes.py."
    pair = approve_pair(client, project_id)
    assert pair.status_code == 200, pair.text
    final = approve_final(client, project_id, pair.json()["id"])
    assert final.status_code == 200, final.text
    with Session(engine) as db:
        before = [
            (r.id, r.content, r.template_source, r.template_sha256)
            for r in db.scalars(select(ProjectDocumentRevision)).all()
        ]
        assert resolve_template_profile(db, uuid.UUID(project_id))[0] == "simplified"
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as restarted:
        login(restarted, "profile-owner")
        for kind, content in zip(DOCUMENT_KINDS, (PROJECT, AGENTS, BACKLOG), strict=True):
            download = restarted.get(f"/api/projects/{project_id}/final-approval/files/{kind}")
            assert download.status_code == 200
            assert download.content == content.encode()
        edited = restarted.put(
            f"/api/projects/{project_id}/backlog/tasks/TASK-001",
            json={
                "expected_revision": 2,
                "title": "Save a dated observation",
                "body": tasks["tasks"][0]["body"],
                "status": "-",
            },
            headers=headers(restarted),
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["content"] == BACKLOG.replace(
            "[ ] TASK-001 — Save one observation", "[-] TASK-001 — Save a dated observation"
        )
        stale = approve_final(restarted, project_id, pair.json()["id"], 2)
        assert stale.status_code == 409
        assert (
            restarted.get(f"/api/projects/{project_id}/final-approval/files/backlog").status_code
            == 409
        )
    with Session(engine) as db:
        after = {
            r.id: (r.content, r.template_source, r.template_sha256)
            for r in db.scalars(select(ProjectDocumentRevision)).all()
        }
        assert all(
            after[rid] == (content, source, digest) for rid, content, source, digest in before
        )
        assert db.scalar(select(ProjectApprovalManifest.id)) is not None


@pytest.mark.parametrize(
    "replacement",
    [
        "",
        "TBD",
        "SQLite database; TBD backup choice",
        "<span>SQLite database</span>",
        "<!-- SQLite database -->",
        "![SQLite database](notes.png)",
        "```\nSQLite database\n```",
    ],
)
def test_missing_or_hidden_simplified_required_decisions_fail_closed(
    client, engine, account_factory, replacement
):
    project_id = prepare(client, account_factory)
    bad = PROJECT.replace("SQLite database, no external services.", replacement)
    response = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 2, "content": bad},
        headers=headers(client),
    )
    assert response.status_code == 200
    result = client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json={"expected_project_revision": 3, "expected_agents_revision": 2},
        headers=headers(client),
    )
    assert result.status_code == 422, result.text
    assert set(result.json()["detail"]["files"]) == {"PROJECT.md"}
    assert "Storage/services" in result.text
    assert (
        client.get(f"/api/projects/{project_id}/document-pair-approval").json()["approved"] is False
    )
    assert client.get(f"/api/projects/{project_id}/final-approval/files/project").status_code == 409


@pytest.mark.parametrize(
    "bad_body",
    [
        "Depends on: None\n\nAcceptance:\n- Save one note.\nVerification: Run tests.\n",
        "Depends on: None\n\n<!-- Persist notes. -->\n\nAcceptance:\n"
        "- Save one note.\nVerification: Run tests.\n",
        "Depends on: None\n**Required capabilities:** Persist notes.\n\nAcceptance:\n"
        "- Save one note.\nVerification: Run tests.\n",
        "Depends on: None\n\nPersist notes.\n\nAcceptance:\n"
        "- [ ] Depends on: None\nVerification: Run tests.\n",
        "Depends on: None\n\nPersist notes.\n\nAcceptance:\n"
        "- Save one note.\nVerification: <div>Run tests.</div>\n",
    ],
)
def test_compact_task_missing_hidden_or_metadata_evidence_rejected(
    client, account_factory, bad_body
):
    project_id = prepare(client, account_factory)
    pair = approve_pair(client, project_id)
    assert pair.status_code == 200, pair.text
    response = client.put(
        f"/api/projects/{project_id}/documents/backlog",
        json={
            "expected_revision": 2,
            "content": "# Fieldnotes\n\n## [ ] TASK-001 — Save notes\n"
            + bad_body
            + "\n## [-] TASK-002 — Review notes\nDepends on: TASK-001\n",
        },
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    decision = approve_final(client, project_id, pair.json()["id"], 3)
    assert decision.status_code == 422, decision.text
    assert "BACKLOG.md" in decision.json()["detail"]["files"]


def test_mixed_unknown_or_partial_seed_not_repaired_or_approved(client, engine, account_factory):
    project_id = prepare(client, account_factory)
    pair = approve_pair(client, project_id)
    assert pair.status_code == 200
    assert approve_final(client, project_id, pair.json()["id"]).status_code == 200
    old = legacy_templates()["backlog"]
    with Session(engine) as db, db.begin():
        document = db.scalar(
            select(ProjectDocument).where(
                ProjectDocument.project_id == uuid.UUID(project_id),
                ProjectDocument.kind == "backlog",
            )
        )
        document_id = document.id
        db.execute(
            update(ProjectDocumentRevision)
            .where(
                ProjectDocumentRevision.document_id == document.id,
                ProjectDocumentRevision.revision_number == 1,
            )
            .values(
                content=old.content,
                template_source=old.source,
                template_sha256=old.sha256,
                content_sha256=old.sha256,
            )
        )
    assert approve_pair(client, project_id).status_code == 422
    assert (
        client.get(f"/api/projects/{project_id}/document-pair-approval").json()["approved"] is False
    )
    status = client.get(f"/api/projects/{project_id}/final-approval").json()
    assert status["approved"] is False and status["latest_manifest"] is not None
    assert client.get(f"/api/projects/{project_id}/final-approval/files/backlog").status_code == 409
    with Session(engine) as db, db.begin():
        seed = db.scalar(
            select(ProjectDocumentRevision).where(
                ProjectDocumentRevision.document_id == document_id,
                ProjectDocumentRevision.revision_number == 1,
            )
        )
        seed.template_source = "unrecognized/BACKLOG.md.example"
    assert approve_pair(client, project_id).status_code == 422


def test_partial_legacy_seed_remains_incomplete_on_startup(engine, account_factory):
    from app.models import Project
    from app.project_documents import add_template_documents

    owner = account_factory("partial-owner", "synthetic password only")
    with Session(engine) as db, db.begin():
        project = Project(name="Partial", owner_user_id=owner)
        db.add(project)
        db.flush()
        project_id = project.id
        seeds = add_template_documents(db, project.id, legacy_templates())
        # Simulate interrupted/corrupted historical initialization on synthetic storage.
        db.delete(seeds["backlog"])
        db.delete(db.get(ProjectDocument, seeds["backlog"].document_id))
    seed_legacy_project_documents(engine, load_project_templates(default_template_root()))
    with Session(engine) as db:
        assert len(db.scalars(select(ProjectDocument)).all()) == 2
        assert resolve_template_profile(db, project_id) is None
        assert {r.template_source for r in db.scalars(select(ProjectDocumentRevision)).all()} == {
            "PROJECT.md.example",
            "AGENTS.md.example",
        }


def test_profile_selection_ignores_installed_bundle_and_editable_headings(client, account_factory):
    project_id = prepare(client, account_factory)
    client.app.state.project_templates = legacy_templates()
    assert approve_pair(client, project_id).status_code == 200
    renamed = PROJECT.replace("## Stack and architecture", "## Technology and environment")
    saved = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 2, "content": renamed},
        headers=headers(client),
    )
    assert saved.status_code == 200
    decision = client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json={"expected_project_revision": 3, "expected_agents_revision": 2},
        headers=headers(client),
    )
    assert decision.status_code == 422
    assert "Stack and architecture" in decision.text


@pytest.mark.parametrize("kind", ["project", "agents"])
def test_filled_prompts_and_copied_instruction_only_sections_are_not_decisions(
    client, account_factory, kind
):
    project_id = prepare(client, account_factory)
    template = client.app.state.project_templates[kind].content
    bad = re.sub(r"<([^<>]+)>", lambda match: match[1].replace("_", " "), template)
    saved = client.put(
        f"/api/projects/{project_id}/documents/{kind}",
        json={"expected_revision": 2, "content": bad},
        headers=headers(client),
    )
    assert saved.status_code == 200
    revisions = {"expected_project_revision": 2, "expected_agents_revision": 2}
    revisions[f"expected_{kind}_revision"] = 3
    decision = client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json=revisions,
        headers=headers(client),
    )
    assert decision.status_code == 422
    assert "starter prompts" in decision.text


def test_rewrapped_completion_guidance_is_not_a_product_decision(client, account_factory):
    project_id = prepare(client, account_factory)
    guidance = (
        "Deliver explicit task acceptance with focused checks and useful documentation changes."
    )
    bad = PROJECT.replace(
        "Saving and searching a note meets the task acceptance criteria.",
        guidance.replace("focused checks", "focused\nchecks"),
    )
    saved = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 2, "content": bad},
        headers=headers(client),
    )
    assert saved.status_code == 200
    decision = client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json={"expected_project_revision": 3, "expected_agents_revision": 2},
        headers=headers(client),
    )
    assert decision.status_code == 422 and "decision under Completion" in decision.text


def test_copied_behavior_guidance_cannot_replace_actual_workflow(client, account_factory):
    project_id = prepare(client, account_factory)
    bad = PROJECT.replace(
        "| Workflow | Expected result | Important rules/failures |\n"
        "|---|---|---|\n"
        "| Save observation | Saved text remains searchable | Empty text returns an error |",
        "Describe realistic behavior, not every hypothetical edge case. Name actual standards\n"
        "or calculations if interoperability matters; link substantial specifications.",
    )
    saved = client.put(
        f"/api/projects/{project_id}/documents/project",
        json={"expected_revision": 2, "content": bad},
        headers=headers(client),
    )
    assert saved.status_code == 200
    decision = client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json={"expected_project_revision": 3, "expected_agents_revision": 2},
        headers=headers(client),
    )
    assert decision.status_code == 422 and "actual workflow" in decision.text


def test_simplified_project_denies_foreign_sessions_and_stale_task_edits(
    client, engine, settings, workspace_root, account_factory
):
    project_id = prepare(client, account_factory)
    account_factory("profile-other", "synthetic password only")
    tasks = client.get(f"/api/projects/{project_id}/backlog/tasks").json()
    payload = {
        "expected_revision": 1,
        "title": "Save notes",
        "body": tasks["tasks"][0]["body"],
        "status": "-",
    }
    stale = client.put(
        f"/api/projects/{project_id}/backlog/tasks/TASK-001", json=payload, headers=headers(client)
    )
    assert stale.status_code == 409
    assert client.get(f"/api/projects/{project_id}/backlog/tasks").json()["content"] == BACKLOG
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as outsider:
        login(outsider, "profile-other")
        assert approve_pair(outsider, project_id).status_code == 404
        assert outsider.get(f"/api/projects/{project_id}/final-approval").status_code == 404
        assert (
            outsider.get(f"/api/projects/{project_id}/final-approval/files/project").status_code
            == 404
        )
        denied = outsider.put(
            f"/api/projects/{project_id}/backlog/tasks/TASK-001",
            json=payload,
            headers=headers(outsider),
        )
        assert denied.status_code == 404


def test_frozen_legacy_approval_and_download_survive_new_bundle_restart(
    client, engine, settings, workspace_root, account_factory
):
    from test_document_pair_approvals import AGENTS_TEXT, PROJECT_TEXT

    account_factory("legacy-profile-owner", "synthetic password only")
    login(client, "legacy-profile-owner")
    client.app.state.project_templates = legacy_templates()
    created = client.post("/api/projects", json={"name": "Frozen legacy"}, headers=headers(client))
    assert created.status_code == 201
    project_id = created.json()["id"]
    for kind, content in zip(DOCUMENT_KINDS, (PROJECT_TEXT, AGENTS_TEXT, BACKLOG), strict=True):
        saved = client.put(
            f"/api/projects/{project_id}/documents/{kind}",
            json={"expected_revision": 1, "content": content},
            headers=headers(client),
        )
        assert saved.status_code == 200
    # Legacy profile still requires explicit Scope; compact fields do not opt it
    # into the simpler evidence contract merely by changing editable headings.
    pair = approve_pair(client, project_id)
    assert pair.status_code == 200
    assert approve_final(client, project_id, pair.json()["id"]).status_code == 422
    ready = BACKLOG.replace(
        "Persist validated text in storage.py; exclude public publishing.",
        "**Scope:** Persist validated text in storage.py; exclude public publishing.",
    )
    assert (
        client.put(
            f"/api/projects/{project_id}/documents/backlog",
            json={"expected_revision": 2, "content": ready},
            headers=headers(client),
        ).status_code
        == 200
    )
    approved = approve_final(client, project_id, pair.json()["id"], 3)
    assert approved.status_code == 200, approved.text
    with Session(engine) as db:
        before = [
            (r.id, r.content, r.template_source, r.template_sha256)
            for r in db.scalars(select(ProjectDocumentRevision)).all()
        ]
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as restarted:
        login(restarted, "legacy-profile-owner")
        assert (
            restarted.get(f"/api/projects/{project_id}/final-approval").json()["approved"] is True
        )
        assert (
            restarted.get(f"/api/projects/{project_id}/final-approval/files/backlog").content
            == ready.encode()
        )
    with Session(engine) as db:
        assert before == [
            (r.id, r.content, r.template_source, r.template_sha256)
            for r in db.scalars(select(ProjectDocumentRevision)).all()
        ]
