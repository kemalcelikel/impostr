from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import project_approval_manifests as manifest_module
from app.backlog_markdown import parse_backlog
from app.config import AppSettings
from app.main import create_app
from app.models import (
    AuditEvent,
    ProjectApprovalManifest,
    ProjectDocument,
    ProjectDocumentRevision,
    User,
)
from app.project_templates import ProjectTemplate
from app.rate_limit import RateLimitDecision

PUBLIC_ORIGIN = "http://127.0.0.1:8080"
STARTER_BACKLOG = """# Backlog: <PROJECT_NAME>

> STARTER TEMPLATE — replace placeholders before approval.

## [-] TASK-001 — <First planning outcome>

**Depends on:** None
"""
VALID_BACKLOG = """# Backlog: Northstar planning

## [-] TASK-001 — Define the first planning milestone

**Depends on:** None
### Done looks like
- The owner can review the milestone.
### Verification
- Review the saved draft.

## [-] TASK-002 — Review the saved milestone

**Depends on:** TASK-001
### Done looks like
- The dependent task remains a draft.
### Verification
- Confirm this backlog parses.
"""
READY_BACKLOG = """# Backlog: Ready Northstar planning

## [ ] TASK-001 — Approve one saved planning snapshot

**Depends on:** None
**Scope:** api/app/project_approval_manifests.py; no repository writes.
### Done looks like
- The manifest refers to the exact approved document revisions.
### Verification
- Run the focused manifest approval tests.
"""
EMPTY_SCOPE_BEFORE_VERIFICATION = READY_BACKLOG.replace(
    "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
    "**Scope:**",
).replace(
    "### Done looks like\n- The manifest refers to the exact approved document revisions.\n"
    "### Verification\n- Run the focused manifest approval tests.\n",
    "### Verification\n- Run the focused manifest approval tests.\n"
    "### Done looks like\n- The manifest refers to the exact approved document revisions.\n",
)
READY_MINIMAL_BACKLOG = """# Backlog: Incomplete ready task

## [ ] TASK-001 — Approve an underspecified task

**Depends on:** None
"""
READY_WAITING_BACKLOG = """# Backlog: Incomplete waiting task

## [-] TASK-001 — Keep a prerequisite in draft
**Depends on:** None

## [ ] TASK-002 — Prepare the dependent task
**Depends on:** TASK-001
"""
WAITING_STARTER_BACKLOG = """# Backlog: Waiting task starter

## [-] TASK-001 — Starter prerequisite
**Depends on:** None

## [-] TASK-002 — Starter dependent task
**Depends on:** TASK-001
"""


def _root_starter_backlog() -> str:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "BACKLOG.md.example"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    # The check image keeps the same pinned template under its runtime directory.
    return Path("/app/templates/BACKLOG.md.example").read_text(encoding="utf-8")


ROOT_STARTER_BACKLOG = _root_starter_backlog()


def _edited_root_starter_backlog() -> str:
    starter_note = (
        "> STARTER TEMPLATE — copy into an application repository as `BACKLOG.md`.\n"
        "> Replace placeholders and remove setup notes. Example entries are `[-]` so an\n"
        "> unattended runner cannot treat unfinished templates as approved ready work.\n"
    )
    without_note = ROOT_STARTER_BACKLOG.replace(starter_note, "")
    return re.sub(
        r"<([^<>\r\n]{1,200})>",
        lambda match: " ".join(match.group(1).split()),
        without_note,
    )


EDITED_ROOT_STARTER_BACKLOG = _edited_root_starter_backlog()


def valid_project(detail: str = "Northstar research platform") -> str:
    return (
        f"# Project: {detail}\n\n"
        "## 1. Purpose and users — required\n\n"
        f"- Summary: {detail} supports private planning.\n"
        "- Problem: Planning drafts need a human owner.\n"
        "- Primary users: The project owner.\n"
        "- Usage context: A private local planning browser.\n"
        "- Product outcomes: Reviewable private drafts.\n\n"
        "## 2. Scope — required\n\n"
        "### In scope\n- Versioned document review.\n\n"
        "### Out of scope\n- Public deployment.\n\n"
        "## 3. Behavior and domain rules — required\n\n"
        "A stale write reports a conflict; only saved versions can be approved.\n\n"
        "## 4. Technology and environment — required\n\n"
        "Python 3.12 and PostgreSQL 17 store revisions.\n\n"
        "## 5. Architecture and repository map — required\n\n"
        "The API owns persistence and the web editor calls it.\n\n"
        "## 9. Decisions, risks, and open questions — required\n\n"
        "The owner reviews the pair before approval.\n\n"
        "## 10. Definition of done — required\n\n"
        "A conflict leaves the editor intact.\n"
    )


def valid_agents(detail: str = "Repository working agreement") -> str:
    return (
        f"# Repository Agent Rules: {detail}\n\n"
        "## Sources of truth and scope\n\n"
        "PROJECT.md defines the product and the owner chooses approved work.\n\n"
        "## Setup and verification commands\n\n"
        "Run `python3 -m pytest` from api/ after installing locked dependencies.\n\n"
        "## Security and hardening workflow\n\n"
        "Keep secrets out of Git; deny cross-project access.\n\n"
        "## Git and task-state ownership\n\n"
        "The owner controls task state and integration.\n"
    )


PROJECT_TEXT = valid_project("Northstar café planning — owner review")
AGENTS_TEXT = valid_agents("Repository règles and approval checks")


def _login(
    client: TestClient,
    username: str,
    password: str = "correct horse battery",
) -> None:
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text


def _headers(client: TestClient, *, origin: str = PUBLIC_ORIGIN) -> dict[str, str]:
    return {
        "Origin": origin,
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }


def _set_backlog_template(client: TestClient, content: str) -> None:
    templates = dict(client.app.state.project_templates)
    templates["backlog"] = ProjectTemplate(
        kind="backlog",
        source="BACKLOG.md.example",
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    client.app.state.project_templates = templates


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"name": name}, headers=_headers(client))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _save(
    client: TestClient,
    project_id: str,
    kind: str,
    revision: int,
    content: str,
) -> dict[str, Any]:
    response = client.put(
        f"/api/projects/{project_id}/documents/{kind}",
        json={"expected_revision": revision, "content": content},
        headers=_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approve_pair(client: TestClient, project_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json={"expected_project_revision": 2, "expected_agents_revision": 2},
        headers=_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approve_manifest(
    client: TestClient,
    project_id: str,
    pair_approval_id: str,
    backlog_revision: int,
    *,
    headers: dict[str, str] | None = None,
    extras: dict[str, object] | None = None,
):
    payload: dict[str, object] = {
        "expected_pair_approval_id": pair_approval_id,
        "expected_backlog_revision": backlog_revision,
    }
    if extras:
        payload.update(extras)
    return client.post(
        f"/api/projects/{project_id}/final-approval",
        json=payload,
        headers=headers if headers is not None else _headers(client),
    )


def _prepare_project(
    client: TestClient,
    *,
    name: str,
    backlog_template: str = STARTER_BACKLOG,
    saved_backlog: str | None = VALID_BACKLOG,
) -> tuple[str, dict[str, Any], int]:
    _set_backlog_template(client, backlog_template)
    project_id = _create_project(client, name)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)
    if saved_backlog is not None:
        backlog_revision = _save(client, project_id, "backlog", 1, saved_backlog)
        backlog_revision_number = backlog_revision["revision_number"]
    else:
        backlog_revision_number = 1
    assert project_revision["revision_number"] == agents_revision["revision_number"] == 2
    pair_approval = _approve_pair(client, project_id)
    return project_id, pair_approval, backlog_revision_number


def test_manifest_is_idempotent_audited_and_downloads_exact_approved_utf8_bytes(
    client: TestClient,
    engine,
    account_factory,
) -> None:
    owner_id = account_factory("manifest-owner", "correct horse battery")
    _login(client, "manifest-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name="Three file export",
    )

    created = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert created.status_code == 200, created.text
    manifest = created.json()
    assert manifest["pair_approval_id"] == pair_approval["id"]
    assert manifest["project"]["revision_number"] == 2
    assert manifest["agents"]["revision_number"] == 2
    assert manifest["backlog"]["revision_number"] == 2
    assert (
        manifest["project"]["content_sha256"]
        == hashlib.sha256(PROJECT_TEXT.encode("utf-8")).hexdigest()
    )
    assert (
        manifest["backlog"]["content_sha256"]
        == hashlib.sha256(VALID_BACKLOG.encode("utf-8")).hexdigest()
    )
    created_at = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
    assert created_at.utcoffset() == timedelta(0)

    repeated = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert repeated.status_code == 200
    assert repeated.json() == manifest

    status_response = client.get(f"/api/projects/{project_id}/final-approval")
    assert status_response.status_code == 200, status_response.text
    status_view = status_response.json()
    assert status_view["pair_approved"] is True
    assert status_view["approved"] is True
    assert status_view["current_manifest"]["id"] == manifest["id"]
    assert status_view["latest_manifest"]["id"] == manifest["id"]
    # Approval records a saved snapshot; it does not claim that any task is ready
    # or dependency-eligible. Both tasks in this valid backlog remain drafts.
    assert "eligible_count" not in status_view
    assert all(
        task.startswith("## [-]") for task in VALID_BACKLOG.splitlines() if task.startswith("## [")
    )

    documents = {
        "project": ("PROJECT.md", PROJECT_TEXT),
        "agents": ("AGENTS.md", AGENTS_TEXT),
        "backlog": ("BACKLOG.md", VALID_BACKLOG),
    }
    for kind, (filename, content) in documents.items():
        response = client.get(
            f"/api/projects/{project_id}/final-approval/files/{kind}",
            params={"revision": 1},
        )
        assert response.status_code == 200, response.text
        assert response.content == content.encode("utf-8")
        assert response.headers["content-disposition"] == (f'attachment; filename="{filename}"')
        assert response.headers["content-type"] == "text/markdown; charset=utf-8"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        repeated_download = client.get(f"/api/projects/{project_id}/final-approval/files/{kind}")
        assert repeated_download.status_code == 200
        assert repeated_download.content == response.content

    # The download route accepts a document kind, never a caller-selected revision
    # or manifest ID; extra path components cannot turn it into a history fetch.
    assert (
        client.get(
            f"/api/projects/{project_id}/final-approval/files/project/revisions/1"
        ).status_code
        == 404
    )

    with Session(engine) as db:
        saved_manifests = list(
            db.scalars(
                select(ProjectApprovalManifest).where(
                    ProjectApprovalManifest.project_id == uuid.UUID(project_id)
                )
            ).all()
        )
        approval_events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "project.approval_manifest.approved",
                    AuditEvent.project_id == uuid.UUID(project_id),
                )
            ).all()
        )
        assert len(saved_manifests) == len(approval_events) == 1
        assert saved_manifests[0].actor_user_id == owner_id
        assert saved_manifests[0].pair_approval_id == uuid.UUID(pair_approval["id"])
        assert approval_events[0].actor_user_id == owner_id
        assert approval_events[0].details == {
            "manifest_id": manifest["id"],
            "pair_approval_id": pair_approval["id"],
            "project_revision_id": manifest["project"]["id"],
            "project_revision_number": 2,
            "agents_revision_id": manifest["agents"]["id"],
            "agents_revision_number": 2,
            "backlog_revision_id": manifest["backlog"]["id"],
            "backlog_revision_number": 2,
        }
        assert PROJECT_TEXT not in str(approval_events[0].details)
        assert AGENTS_TEXT not in str(approval_events[0].details)
        assert VALID_BACKLOG not in str(approval_events[0].details)


@pytest.mark.parametrize(
    ("backlog_template", "saved_backlog", "expected_error"),
    [
        (STARTER_BACKLOG, None, "unchanged from its saved starter"),
        (
            STARTER_BACKLOG,
            VALID_BACKLOG.replace(
                "TASK-001 — Define the first planning milestone",
                "TASK-001 — TODO: define the first planning milestone",
            ),
            "TODO/TBD placeholders",
        ),
        ("# Backlog: empty starter\n\nNotes remain but no tasks exist.\n", None, "at least one"),
        (
            "# Backlog: malformed starter\n\n## [?] TASK-001 — Invalid marker\n"
            "**Depends on:** None\n",
            None,
            "malformed task headings or dependencies",
        ),
        (
            "# Backlog: unknown dependency\n\n## [-] TASK-001 — Unknown dependency\n"
            "**Depends on:** TASK-999\n",
            None,
            "malformed task headings or dependencies",
        ),
        (
            ROOT_STARTER_BACKLOG,
            EDITED_ROOT_STARTER_BACKLOG,
            "retained starter guidance",
        ),
        (
            ROOT_STARTER_BACKLOG,
            EDITED_ROOT_STARTER_BACKLOG.replace("supplied helper", "local helper"),
            "retained starter guidance",
        ),
        (
            ROOT_STARTER_BACKLOG,
            "# Backlog: Northstar planning\n\n"
            "## Owner notes\n\n"
            + ROOT_STARTER_BACKLOG.split("## How to create and maintain this backlog\n\n", 1)[1]
            .split("2. Give each item", 1)[0]
            .replace("interactive `tech-lead`", "local planning lead")
            + "\n## [-] TASK-001 — Plan the next milestone\n\n**Depends on:** None\n"
            "\n## [-] TASK-002 — Review next milestone\n\n**Depends on:** TASK-001\n",
            "retained starter guidance",
        ),
        (STARTER_BACKLOG, READY_MINIMAL_BACKLOG, "substantive Scope"),
        (WAITING_STARTER_BACKLOG, READY_WAITING_BACKLOG, "substantive Scope"),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.\n",
                "",
            ),
            "substantive Scope",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
                "**Scope:** N/A",
            ),
            "substantive Scope",
        ),
        (
            STARTER_BACKLOG,
            EMPTY_SCOPE_BEFORE_VERIFICATION,
            "substantive Scope",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "### Done looks like\n"
                "- The manifest refers to the exact approved document revisions.\n",
                "### Done looks like\n",
            ),
            "substantive acceptance",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- Run the focused manifest approval tests.",
                "- N/A",
            ),
            "substantive verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
                "**Scope:** Decide later.",
            ),
            "substantive Scope",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace("**Depends on:** None\n", "", 1).replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
                "**Scope:**\n**Depends on:** None",
            ),
            "substantive Scope",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
                "**Scope:**\n**Required capabilities:** Versioned document access.",
            ),
            "substantive Scope",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
                "**Scope:** Pending: choose which approved revisions may be downloaded.",
            ),
            "substantive Scope",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.\n",
                "**Scope:** Implement the manifest.\n"
                "#### Pending: Tenant isolation\n"
                "- Decide later.\n",
            ),
            "substantive Scope",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- The manifest refers to the exact approved document revisions.",
                "- Decide later.",
            ),
            "substantive acceptance",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- Run the focused manifest approval tests.",
                "- Pending checks after implementation.",
            ),
            "substantive verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "### Verification\n",
                "### Verification\n"
                "#### Pending: PostgreSQL concurrency\n"
                "- The concurrency test is planned for later.\n",
            ),
            "substantive verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "### Verification\n",
                "### Verification\n#### PostgreSQL concurrency unresolved\n",
            ),
            "unresolved task notes",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "### Verification\n",
                "### Verification\n#### Pending: PostgreSQL concurrency\n",
            ),
            "unresolved task notes",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- Run the focused manifest approval tests.",
                "- Run the focused manifest approval tests.\n- Decide later.",
            ),
            "substantive verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- The manifest refers to the exact approved document revisions.",
                "- The manifest refers to the exact approved document revisions.\n"
                "- Pending review after implementation.",
            ),
            "substantive acceptance",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- The manifest refers to the exact approved document revisions.",
                "- <!-- The manifest refers to the exact approved document revisions. -->",
            ),
            "substantive acceptance",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- Run the focused manifest approval tests.",
                "```text\nRun the focused manifest approval tests.\n```",
            ),
            "substantive verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- Run the focused manifest approval tests.",
                "- [ ] Decide later.",
            ),
            "substantive verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- The manifest refers to the exact approved document revisions.",
                "| Outcome |\n| --- |",
            ),
            "substantive acceptance",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- Run the focused manifest approval tests.",
                "| Check |\n| --- |",
            ),
            "substantive verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- The manifest refers to the exact approved document revisions.",
                "| Outcome |",
            ),
            "substantive acceptance",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace("- Run the focused manifest approval tests.", "| Check |"),
            "substantive verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- Run the focused manifest approval tests.",
                "| Check | Evidence |\n| --- | --- |\n| Run tests | |",
            ),
            "substantive verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- The manifest refers to the exact approved document revisions.",
                "- The manifest refers to the exact approved document revisions.\n"
                "### Acceptance\n- Decide later.",
            ),
            "duplicate acceptance",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG.replace(
                "- Run the focused manifest approval tests.",
                "- Run the focused manifest approval tests.\n### Verification\n- Decide later.",
            ),
            "duplicate verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG + "\n## Additional task notes\n### Verification\n- Decide later.\n",
            "duplicate verification",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG + "\n## Additional task notes\n### Owner decision\n- Decide later.\n",
            "unresolved task notes",
        ),
        (
            STARTER_BACKLOG,
            READY_BACKLOG
            + "\n## Additional task notes\n"
            + "#### PostgreSQL concurrency unresolved\n"
            + "- The integration test serializes competing manifest approvals.\n",
            "unresolved task notes",
        ),
    ],
    ids=[
        "unchanged-template",
        "todo-placeholder",
        "empty",
        "malformed-marker",
        "unknown-dep",
        "root-template-guidance",
        "minimally-edited-root-guidance",
        "partial-minimally-edited-root-guidance",
        "ready-only-heading-and-dependency",
        "ready-waiting-on-dependency",
        "ready-missing-scope",
        "ready-placeholder-scope",
        "ready-empty-scope-before-verification",
        "ready-empty-acceptance",
        "ready-non-substantive-verification",
        "ready-deferred-scope",
        "ready-empty-scope-before-dependency-field",
        "ready-empty-scope-before-other-metadata-field",
        "ready-prefix-pending-scope",
        "ready-deferred-child-scope",
        "ready-deferred-acceptance",
        "ready-pending-verification",
        "ready-pending-child-verification-heading",
        "ready-unresolved-suffix-child-verification-heading",
        "ready-pending-prefix-child-verification-heading",
        "ready-mixed-verification",
        "ready-mixed-acceptance",
        "ready-comment-only-acceptance",
        "ready-fenced-verification",
        "ready-checkbox-deferred-verification",
        "ready-header-only-acceptance-table",
        "ready-header-only-verification-table",
        "ready-lone-acceptance-table-header",
        "ready-lone-verification-table-header",
        "ready-label-without-verification-data",
        "ready-deferred-duplicate-acceptance",
        "ready-deferred-duplicate-verification",
        "ready-deferred-duplicate-verification-after-h2",
        "ready-deferred-owner-notes-after-h2",
        "ready-unresolved-child-heading-after-h2",
    ],
)
def test_invalid_backlogs_cannot_create_an_approved_manifest(
    client: TestClient,
    engine,
    account_factory,
    backlog_template: str,
    saved_backlog: str | None,
    expected_error: str,
) -> None:
    account_factory("invalid-backlog-owner", "correct horse battery")
    _login(client, "invalid-backlog-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name="Invalid backlog sample",
        backlog_template=backlog_template,
        saved_backlog=saved_backlog,
    )

    rejected = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert rejected.status_code == 422, rejected.text
    errors = rejected.json()["detail"]["files"]["BACKLOG.md"]
    assert any(expected_error.lower() in error.lower() for error in errors), errors
    status_view = client.get(f"/api/projects/{project_id}/final-approval").json()
    assert status_view["approved"] is False
    assert status_view["current_manifest"] is None
    for kind in ("project", "agents", "backlog"):
        denied_download = client.get(f"/api/projects/{project_id}/final-approval/files/{kind}")
        assert denied_download.status_code == 409

    with Session(engine) as db:
        assert (
            db.scalar(
                select(ProjectApprovalManifest.id).where(
                    ProjectApprovalManifest.project_id == uuid.UUID(project_id)
                )
            )
            is None
        )
        assert (
            db.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.action == "project.approval_manifest.approved",
                    AuditEvent.project_id == uuid.UUID(project_id),
                )
            )
            is None
        )


def test_parser_keeps_ready_eligibility_separate_from_final_approval_detail() -> None:
    parsed = parse_backlog(READY_MINIMAL_BACKLOG)
    assert parsed.summary.eligible_count == 1
    assert parsed.tasks[0].ready is True
    assert parsed.tasks[0].eligible is True

    waiting = parse_backlog(READY_WAITING_BACKLOG)
    assert waiting.tasks[1].ready is True
    assert waiting.tasks[1].eligible is False


def test_approval_accepts_authored_guidance_and_underspecified_draft_tasks(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("authored-guidance-owner", "correct horse battery")
    _login(client, "authored-guidance-owner")
    authored_draft = """# Backlog: Owner-authored planning

## Owner guidance
The owner adds concrete scope and checks before moving a task to ready.

## [-] TASK-001 — Draft the first planning task

**Depends on:** None

## [-] TASK-002 — Draft the follow-up planning task

**Depends on:** TASK-001
"""
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name="Authored guidance with drafts",
        backlog_template=ROOT_STARTER_BACKLOG,
        saved_backlog=authored_draft,
    )

    approved = _approve_manifest(client, project_id, pair_approval["id"], backlog_revision)
    assert approved.status_code == 200, approved.text
    download = client.get(f"/api/projects/{project_id}/final-approval/files/backlog")
    assert download.status_code == 200
    assert download.content == authored_draft.encode("utf-8")


def test_approval_accepts_ready_tasks_with_substantive_scope_acceptance_and_verification(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("complete-ready-owner", "correct horse battery")
    _login(client, "complete-ready-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name="Complete ready task",
        saved_backlog=READY_BACKLOG,
    )

    approved = _approve_manifest(client, project_id, pair_approval["id"], backlog_revision)
    assert approved.status_code == 200, approved.text
    assert approved.json()["backlog"]["revision_number"] == backlog_revision


@pytest.mark.parametrize(
    "scope_field",
    [
        "Scope: api/app/project_approval_manifests.py; no repository writes.",
        "- Scope: api/app/project_approval_manifests.py; no repository writes.",
        "- **Scope:** api/app/project_approval_manifests.py; no repository writes.",
    ],
    ids=["plain", "bullet", "bold-bullet"],
)
def test_ready_task_scope_field_variants_remain_approved(
    client: TestClient,
    account_factory,
    scope_field: str,
) -> None:
    account_factory("scope-variant-owner", "correct horse battery")
    _login(client, "scope-variant-owner")
    backlog = READY_BACKLOG.replace(
        "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
        scope_field,
    )
    project_id, pair_approval, revision = _prepare_project(
        client, name="Ready task scope field variant", saved_backlog=backlog
    )
    approved = _approve_manifest(client, project_id, pair_approval["id"], revision)
    assert approved.status_code == 200, approved.text


def test_ready_task_multiline_scope_stops_at_metadata_and_downloads_snapshot(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("multiline-scope-owner", "correct horse battery")
    _login(client, "multiline-scope-owner")
    backlog = READY_BACKLOG.replace("**Depends on:** None\n", "", 1).replace(
        "**Scope:** api/app/project_approval_manifests.py; no repository writes.\n",
        "**Scope:**\n"
        "The API records all three immutable revisions in one project-bound manifest.\n"
        "Downloads use those recorded revisions instead of a caller-selected history ID.\n"
        "**Depends on:** None\n",
    )
    project_id, pair_approval, revision = _prepare_project(
        client,
        name="Ready task multiline scope",
        saved_backlog=backlog,
    )

    approved = _approve_manifest(client, project_id, pair_approval["id"], revision)
    assert approved.status_code == 200, approved.text
    assert approved.json()["backlog"]["revision_number"] == revision
    downloaded = client.get(f"/api/projects/{project_id}/final-approval/files/backlog")
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == backlog.encode("utf-8")


@pytest.mark.parametrize(
    ("backlog", "expected_status", "expected_error"),
    [
        pytest.param(
            READY_BACKLOG.replace(
                "### Verification\n",
                "### Verification\n"
                "- Database review:\n\n"
                "  #### PostgreSQL concurrency unresolved\n",
                1,
            ),
            422,
            "unresolved task notes",
            id="nested-list-unresolved-heading",
        ),
        pytest.param(
            READY_BACKLOG.replace("**Depends on:** None\n", "", 1).replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.\n",
                "**Scope:**\n**Depends on:** None\n",
                1,
            ),
            422,
            "substantive Scope",
            id="empty-scope-before-dependency-metadata",
        ),
        pytest.param(
            READY_BACKLOG.replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
                "**Scope:**\n**Required capabilities:** Versioned document access.",
                1,
            ),
            422,
            "substantive Scope",
            id="empty-scope-before-capability-metadata",
        ),
        pytest.param(
            READY_BACKLOG.replace(
                "### Verification\n",
                "### Verification\n#### Pending: PostgreSQL concurrency\n",
                1,
            ),
            422,
            "substantive verification",
            id="pending-prefix-heading",
        ),
        pytest.param(
            READY_BACKLOG
            + "\n## Additional task notes\n"
            + "#### PostgreSQL concurrency unresolved\n",
            422,
            "unresolved task notes",
            id="unresolved-heading-after-non-task-h2",
        ),
        pytest.param(
            READY_BACKLOG.replace(
                "**Scope:** api/app/project_approval_manifests.py; no repository writes.\n",
                "**Scope:**\n"
                "- API: Record all three immutable revisions in one project-bound manifest.\n"
                "- Export: Serve only the immutable bytes referenced by that manifest.\n",
                1,
            ),
            200,
            None,
            id="colon-labeled-scope-list-continuation",
        ),
        pytest.param(
            READY_BACKLOG.replace(
                "### Verification\n",
                "### Verification\n"
                "#### Reject unknown dependency IDs — verified\n"
                "- The API rejects references to unknown task IDs.\n",
                1,
            ),
            200,
            None,
            id="unknown-in-completed-heading",
        ),
        pytest.param(
            READY_BACKLOG.replace(
                "### Verification\n",
                "### Verification\n"
                "#### PostgreSQL concurrency — verified\n"
                "- The integration test serializes concurrent manifest approvals.\n",
                1,
            ),
            200,
            None,
            id="completed-child-heading",
        ),
        pytest.param(
            READY_BACKLOG.replace(
                "### Verification\n",
                "### Verification\n"
                "- Run the focused manifest approval tests before the examples.\n"
                "```markdown\n"
                "### Verification\n"
                "#### Pending: PostgreSQL concurrency\n"
                "- Decide later.\n"
                "```\n"
                "<!--\n"
                "### Verification\n"
                "#### PostgreSQL concurrency unresolved\n"
                "-->\n"
                "<div>\n"
                "### Verification\n"
                "#### Pending: another review\n"
                "</div>\n"
                "    ### Verification\n"
                "    #### PostgreSQL concurrency unresolved\n",
                1,
            ),
            200,
            None,
            id="fenced-html-and-indented-examples",
        ),
        pytest.param(
            READY_BACKLOG.replace(
                "### Done looks like\n",
                "```markdown\n"
                "### Done looks like\n- Decide later.\n"
                "#### Pending: acceptance example\n"
                "```\n"
                "<!--\n"
                "### Done looks like\n- Decide later.\n"
                "#### Done looks like unresolved\n"
                "-->\n"
                "<div>\n"
                "### Done looks like\n- Decide later.\n"
                "#### Pending: another example\n"
                "</div>\n"
                "    ### Done looks like\n"
                "    #### Pending: indented example\n"
                "### Done looks like\n",
                1,
            ).replace(
                "### Verification\n",
                "```markdown\n"
                "### Verification\n- Decide later.\n"
                "```\n"
                "<!--\n"
                "### Verification\n- Decide later.\n"
                "-->\n"
                "<div>\n"
                "### Verification\n- Decide later.\n"
                "</div>\n"
                "    ### Verification\n"
                "### Verification\n",
                1,
            ),
            200,
            None,
            id="examples-before-visible-ready-sections",
        ),
    ],
)
def test_ready_backlog_markdown_boundary_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    backlog: str,
    expected_status: int,
    expected_error: str | None,
) -> None:
    _assert_backlog_http_boundary(
        client, engine, account_factory, backlog, expected_status, expected_error
    )


def _assert_backlog_http_boundary(
    client: TestClient,
    engine,
    account_factory,
    backlog: str,
    expected_status: int,
    expected_error: str | None,
    *,
    backlog_template: str = STARTER_BACKLOG,
) -> None:
    account_factory("approval-matrix-owner", "correct horse battery")
    _login(client, "approval-matrix-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name="Approval Markdown boundary matrix",
        backlog_template=backlog_template,
        saved_backlog=backlog,
    )
    approval_path = f"/api/projects/{project_id}/final-approval"

    # A jointly approved pair is not sufficient: without a manifest every file
    # remains unavailable, regardless of whether this backlog will validate.
    pending = client.get(approval_path)
    assert pending.status_code == 200, pending.text
    assert pending.json()["approved"] is False
    assert pending.json()["current_manifest"] is None
    for kind in ("project", "agents", "backlog"):
        denied = client.get(f"{approval_path}/files/{kind}")
        assert denied.status_code == 409

    decision = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert decision.status_code == expected_status, decision.text

    if expected_error is not None:
        errors = decision.json()["detail"]["files"]["BACKLOG.md"]
        assert any(expected_error.casefold() in error.casefold() for error in errors), errors
        rejected_status = client.get(approval_path)
        assert rejected_status.status_code == 200
        assert rejected_status.json()["approved"] is False
        assert rejected_status.json()["current_manifest"] is None
        assert rejected_status.json()["validation_errors"]["BACKLOG.md"] == errors
        for kind in ("project", "agents", "backlog"):
            denied = client.get(f"{approval_path}/files/{kind}")
            assert denied.status_code == 409
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(ProjectApprovalManifest.id).where(
                        ProjectApprovalManifest.project_id == uuid.UUID(project_id)
                    )
                )
                is None
            )
        return

    manifest = decision.json()
    approved_status = client.get(approval_path)
    assert approved_status.status_code == 200
    assert approved_status.json()["approved"] is True
    assert approved_status.json()["current_manifest"]["id"] == manifest["id"]
    assert approved_status.json()["validation_errors"] == {}
    repeated = _approve_manifest(client, project_id, pair_approval["id"], backlog_revision)
    assert repeated.status_code == 200
    assert repeated.json() == manifest
    expected_contents = {
        "project": PROJECT_TEXT,
        "agents": AGENTS_TEXT,
        "backlog": backlog,
    }
    for kind, content in expected_contents.items():
        downloaded = client.get(f"{approval_path}/files/{kind}")
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.content == content.encode("utf-8")
        assert hashlib.sha256(downloaded.content).hexdigest() == manifest[kind]["content_sha256"]
        assert downloaded.headers["content-disposition"] == (
            f'attachment; filename="{kind.upper()}.md"'
        )
        repeated_download = client.get(f"{approval_path}/files/{kind}")
        assert repeated_download.status_code == 200
        assert repeated_download.content == downloaded.content


@pytest.mark.parametrize(
    "metadata_line",
    [
        pytest.param(form.format(field=field, value=value), id=f"{field}-{form_name}")
        for field, value in (
            ("Depends on", "None"),
            ("Scope", "Implement the approved revision export."),
            ("Required capabilities", "Versioned document access."),
            ("Type", "feature"),
            ("Branch", "feature/approved-export"),
            ("PR", "https://example.invalid/review/1"),
            ("Documentation impact", "Explain approved downloads in the user guide."),
            ("Open decisions", "None; export uses the saved manifest."),
        )
        for form_name, form in (
            ("plain", "{field}: {value}"),
            ("bold", "**{field}:** {value}"),
            ("bold-label", "**{field}**: {value}"),
            ("italic-label", "*{field}*: {value}"),
            ("code-label", "`{field}`: {value}"),
            ("list-bold", "- **{field}:** {value}"),
        )
        # Dependency syntax is fixed by the root helper; test only its supported
        # forms here so a parser error cannot conceal borrowed Scope evidence.
        if field != "Depends on" or form_name in {"plain", "bold"}
    ],
)
def test_empty_scope_cannot_borrow_canonical_metadata_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    metadata_line: str,
) -> None:
    backlog = READY_BACKLOG.replace("**Depends on:** None\n", "", 1).replace(
        "**Scope:** api/app/project_approval_manifests.py; no repository writes.\n",
        f"**Scope:**\n\n{metadata_line}\n",
        1,
    )
    if "Depends on" not in metadata_line:
        backlog = backlog.replace(
            "### Done looks like\n", "**Depends on:** None\n### Done looks like\n", 1
        )
    # Existing runner metadata may be preserved but never newly introduced by a
    # draft save. Seed it in the template to exercise approval, not that save guard.
    template = STARTER_BACKLOG
    if metadata_line.lstrip("-* ").startswith(("Branch:", "**Branch:**", "PR:", "**PR:**")):
        template += metadata_line + "\n"
    _assert_backlog_http_boundary(
        client,
        engine,
        account_factory,
        backlog,
        422,
        "substantive Scope",
        backlog_template=template,
    )


@pytest.mark.parametrize(
    "title",
    [
        pytest.param(f"PostgreSQL concurrency {status}{explanation}", id=f"{status}-{name}")
        for status in ("unknown", "undecided", "unresolved", "unspecified", "pending")
        for name, explanation in (
            ("dash", " — awaiting an integration fixture"),
            ("colon", ": awaiting an integration fixture"),
            ("parentheses", " (awaiting an integration fixture)"),
            ("comma", ", awaiting an integration fixture"),
        )
    ]
    + [
        pytest.param(
            "PostgreSQL concurrency **unresolved** — awaiting a fixture", id="bold-status"
        ),
        pytest.param("PostgreSQL concurrency _pending_ / awaiting a fixture", id="italic-slash"),
        pytest.param("PostgreSQL concurrency `undecided`; awaiting a fixture", id="code-semicolon"),
        pytest.param(
            "PostgreSQL concurrency [unknown](https://example.invalid) – awaiting a fixture",
            id="link-en-dash",
        ),
        pytest.param(
            "PostgreSQL concurrency UNSPECIFIED - awaiting a fixture", id="uppercase-hyphen"
        ),
    ],
)
def test_unfinished_heading_with_explanation_blocks_manifest_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    title: str,
) -> None:
    backlog = READY_BACKLOG.replace("### Verification\n", f"### Verification\n#### {title}\n", 1)
    _assert_backlog_http_boundary(
        client, engine, account_factory, backlog, 422, "unresolved task notes"
    )


@pytest.mark.parametrize(
    "placement",
    ["scope", "acceptance", "verification-list", "post-h2"],
)
def test_unfinished_heading_explanation_in_other_task_regions_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    placement: str,
) -> None:
    heading = "#### PostgreSQL concurrency unresolved — awaiting an integration fixture\n"
    if placement == "post-h2":
        backlog = READY_BACKLOG + "\n## Additional task notes\n" + heading
    elif placement == "verification-list":
        backlog = READY_BACKLOG.replace(
            "### Verification\n",
            "### Verification\n- Database review:\n\n  " + heading,
            1,
        )
    else:
        boundary = "### Done looks like\n" if placement == "scope" else "### Verification\n"
        backlog = READY_BACKLOG.replace(boundary, heading + boundary, 1)
    _assert_backlog_http_boundary(
        client, engine, account_factory, backlog, 422, "unresolved task notes"
    )


@pytest.mark.parametrize(
    "title",
    [
        "PostgreSQL concurrency — verified (integration fixture passed)",
        "PostgreSQL concurrency **verified**: integration fixture passed",
        "Reject unknown dependency IDs — verified",
        "Reject **unknown** dependency IDs — verified",
        "Track undecided owner questions — verified",
        "Detect unresolved dependency references: tests passed",
        "Reject unspecified export kinds (tests passed)",
        "Handle pending approval requests / verified",
    ],
)
def test_completed_and_subject_word_headings_remain_downloadable_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    title: str,
) -> None:
    backlog = READY_BACKLOG.replace("### Verification\n", f"### Verification\n#### {title}\n", 1)
    _assert_backlog_http_boundary(client, engine, account_factory, backlog, 200, None)


@pytest.mark.parametrize(
    "continuation",
    [
        "API: Record the three immutable revisions in a project-bound manifest.\n"
        "Export: Serve only the approved revision bytes.\n",
        "- API: Record the three immutable revisions in a project-bound manifest.\n"
        "- Export: Serve only the approved revision bytes.\n",
        "```markdown\n**Documentation impact:** Explain downloads.\n"
        "#### PostgreSQL concurrency unresolved — awaiting an integration fixture\n```\n"
        "API: Record the three immutable revisions in a project-bound manifest.\n",
        "<div>\n**Open decisions:** Choose export behavior.\n"
        "#### PostgreSQL concurrency unresolved — awaiting an integration fixture\n</div>\n"
        "API: Record the three immutable revisions in a project-bound manifest.\n",
        "    **Documentation impact:** Explain downloads.\n"
        "    #### PostgreSQL concurrency unresolved — awaiting an integration fixture\n"
        "API: Record the three immutable revisions in a project-bound manifest.\n",
    ],
    ids=["prose", "list", "fenced-example", "html-example", "indented-example"],
)
def test_scope_continuation_and_masked_metadata_remain_downloadable_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    continuation: str,
) -> None:
    backlog = READY_BACKLOG.replace(
        "**Scope:** api/app/project_approval_manifests.py; no repository writes.\n",
        "**Scope:**\n" + continuation + "**Documentation impact:** Explain approved downloads.\n",
        1,
    )
    _assert_backlog_http_boundary(client, engine, account_factory, backlog, 200, None)


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param(form.format(field=field), id=f"{field}-{name}")
        for field in ("Documentation impact", "Open decisions", "Required capabilities", "Type")
        for name, form in (
            ("code-colon", "`{field}:` Explain approved downloads."),
            ("whole-code", "`{field}: Explain approved downloads.`"),
            ("list-code-colon", "- `{field}:` Explain approved downloads."),
        )
    ],
)
def test_decoded_metadata_cannot_supply_empty_scope_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    metadata: str,
) -> None:
    backlog = READY_BACKLOG.replace(
        "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
        "**Scope:**\n" + metadata,
        1,
    )
    _assert_backlog_http_boundary(
        client, engine, account_factory, backlog, 422, "substantive Scope"
    )


@pytest.mark.parametrize("section", ["acceptance", "verification"])
@pytest.mark.parametrize(
    "continuation",
    ["", "\nExplain the saved snapshot in that guide."],
    ids=["metadata-only", "metadata-continuation"],
)
@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param(form.format(field=field, value=value), id=f"{field}-{name}")
        for field, value in (
            ("Documentation impact", "Explain approved downloads in the user guide."),
            ("Open decisions", "None; use the saved snapshot."),
            ("Required capabilities", "Versioned document access."),
            ("Type", "feature"),
        )
        for name, form in (
            ("bold", "**{field}:** {value}"),
            ("code-colon", "`{field}:` {value}"),
            ("list-bold", "- **{field}:** {value}"),
        )
    ],
)
def test_metadata_only_required_sections_cannot_approve_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    section: str,
    metadata: str,
    continuation: str,
) -> None:
    evidence = (
        "- The manifest refers to the exact approved document revisions."
        if section == "acceptance"
        else "- Run the focused manifest approval tests."
    )
    # Continuation belongs to the metadata field, not to the preceding section.
    backlog = READY_BACKLOG.replace(evidence, metadata + continuation, 1)
    _assert_backlog_http_boundary(
        client, engine, account_factory, backlog, 422, f"substantive {section}"
    )


@pytest.mark.parametrize("section", ["acceptance", "verification"])
@pytest.mark.parametrize(
    "metadata",
    [
        "**Documentation impact:** Explain approved downloads in the user guide.",
        "`Documentation impact:` Explain approved downloads in the user guide.",
        "**Open decisions:** None; use the saved snapshot.",
    ],
)
def test_real_required_section_evidence_before_metadata_remains_downloadable_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    section: str,
    metadata: str,
) -> None:
    evidence = (
        "- The manifest refers to the exact approved document revisions."
        if section == "acceptance"
        else "- Run the focused manifest approval tests."
    )
    backlog = READY_BACKLOG.replace(evidence, evidence + "\n" + metadata, 1)
    _assert_backlog_http_boundary(client, engine, account_factory, backlog, 200, None)


@pytest.mark.parametrize(
    "title",
    [
        "Verify pending-request cancellation — verified",
        "Verify unknown-dependency rejection — verified",
        "Verify unresolved-reference rejection — verified",
        "Verify undecided-question tracking — verified",
        "Verify unspecified-kind rejection — verified",
        "Verify request-pending cancellation — verified",
        "Verify **pending-request** cancellation — verified",
        "Verify `request-pending` cancellation — verified",
    ],
)
@pytest.mark.parametrize("nested", [False, True], ids=["heading", "list-heading"])
def test_compound_subject_headings_remain_downloadable_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    title: str,
    nested: bool,
) -> None:
    prefix = "- Cancellation review:\n\n  " if nested else ""
    backlog = READY_BACKLOG.replace(
        "### Verification\n", f"### Verification\n{prefix}#### {title}\n", 1
    )
    _assert_backlog_http_boundary(client, engine, account_factory, backlog, 200, None)


@pytest.mark.parametrize(
    "title",
    [
        "Concurrency pending — awaiting a fixture",
        "Concurrency **pending** — awaiting a fixture",
        "Verify pending-request cancellation unresolved — awaiting a fixture",
        "Verify request-pending cancellation — unresolved: awaiting a fixture",
        "Verify unknown-dependency rejection — decide later",
        "Verify TODO-request cancellation — verified",
    ],
)
def test_compound_subject_does_not_hide_separate_unfinished_heading_status_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    title: str,
) -> None:
    backlog = READY_BACKLOG.replace(
        "### Verification\n", f"### Verification\n- Database review:\n\n  #### {title}\n", 1
    )
    expected_error = "TODO/TBD placeholders" if "TODO" in title else "unresolved task notes"
    _assert_backlog_http_boundary(client, engine, account_factory, backlog, 422, expected_error)


@pytest.mark.parametrize("mask", ["fenced", "html", "indented"])
def test_decoded_metadata_and_unfinished_heading_examples_do_not_end_sections_http_matrix(
    client: TestClient,
    engine,
    account_factory,
    mask: str,
) -> None:
    example = (
        "`Documentation impact:` Explain approved downloads.\n"
        "#### Concurrency pending — awaiting a fixture\n"
    )
    masked = (
        "```markdown\n" + example + "```\n"
        if mask == "fenced"
        else "<div>\n" + example + "</div>\n"
        if mask == "html"
        else "".join("    " + line + "\n" for line in example.splitlines())
    )
    backlog = READY_BACKLOG.replace(
        "### Done looks like\n", "### Done looks like\n" + masked, 1
    ).replace("### Verification\n", "### Verification\n" + masked, 1)
    _assert_backlog_http_boundary(client, engine, account_factory, backlog, 200, None)


def test_ready_task_with_completed_scope_child_heading_is_approved(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("ready-scope-child-owner", "correct horse battery")
    _login(client, "ready-scope-child-owner")
    backlog = READY_BACKLOG.replace(
        "**Scope:** api/app/project_approval_manifests.py; no repository writes.\n",
        "**Scope:** Implement the manifest.\n"
        "#### Tenant isolation — enforced\n"
        "- Approval and download requests verify that the actor can access the project.\n",
    )
    project_id, pair_approval, revision = _prepare_project(
        client, name="Ready task completed scope child", saved_backlog=backlog
    )
    approved = _approve_manifest(client, project_id, pair_approval["id"], revision)
    assert approved.status_code == 200, approved.text


def test_ready_task_fenced_scope_heading_example_does_not_block_approval(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("ready-scope-example-owner", "correct horse battery")
    _login(client, "ready-scope-example-owner")
    backlog = READY_BACKLOG.replace(
        "### Done looks like\n",
        "```markdown\n#### Pending: Tenant isolation\n- Decide later.\n```\n### Done looks like\n",
    )
    project_id, pair_approval, revision = _prepare_project(
        client, name="Ready task fenced scope example", saved_backlog=backlog
    )
    approved = _approve_manifest(client, project_id, pair_approval["id"], revision)
    assert approved.status_code == 200, approved.text
    downloaded = client.get(f"/api/projects/{project_id}/final-approval/files/backlog")
    assert downloaded.status_code == 200
    assert downloaded.content == backlog.encode("utf-8")


def test_ready_task_fenced_heading_example_does_not_create_duplicate_section(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("ready-example-owner", "correct horse battery")
    _login(client, "ready-example-owner")
    backlog = READY_BACKLOG.replace(
        "### Verification\n",
        "```markdown\n"
        "#### Pending: PostgreSQL concurrency\n"
        "- Decide later.\n"
        "```\n"
        "### Verification\n",
    )
    project_id, pair_approval, revision = _prepare_project(
        client, name="Ready task with fenced example", saved_backlog=backlog
    )
    approved = _approve_manifest(client, project_id, pair_approval["id"], revision)
    assert approved.status_code == 200, approved.text


def test_ready_task_with_completed_child_heading_is_approved(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("ready-child-heading-owner", "correct horse battery")
    _login(client, "ready-child-heading-owner")
    backlog = READY_BACKLOG.replace(
        "### Verification\n",
        "### Verification\n"
        "#### PostgreSQL concurrency — verified\n"
        "- The integration test serialized concurrent approvals and verified one manifest.\n",
    )
    project_id, pair_approval, revision = _prepare_project(
        client, name="Ready task completed child heading", saved_backlog=backlog
    )
    approved = _approve_manifest(client, project_id, pair_approval["id"], revision)
    assert approved.status_code == 200, approved.text


@pytest.mark.parametrize(
    "notes",
    [
        "## Additional task notes\n### Owner decision\n"
        "- The owner selected a read-only download for each approved revision.\n",
        "## Additional task notes\n### Owner decision\n"
        "- The owner selected read-only approved downloads.\n"
        "```markdown\n### Pending: later example\n- Decide later.\n```\n",
    ],
    ids=["completed-notes", "fenced-example-in-completed-notes"],
)
def test_ready_task_with_completed_notes_after_non_task_h2_is_approved(
    client: TestClient,
    account_factory,
    notes: str,
) -> None:
    account_factory("ready-complete-notes-owner", "correct horse battery")
    _login(client, "ready-complete-notes-owner")
    backlog = READY_BACKLOG + "\n" + notes
    project_id, pair_approval, revision = _prepare_project(
        client, name="Ready task with completed notes", saved_backlog=backlog
    )
    approved = _approve_manifest(client, project_id, pair_approval["id"], revision)
    assert approved.status_code == 200, approved.text
    for kind in ("project", "agents", "backlog"):
        download = client.get(f"/api/projects/{project_id}/final-approval/files/{kind}")
        assert download.status_code == 200
    assert download.content == backlog.encode("utf-8")


def test_approval_accepts_ready_tasks_with_real_table_data_cells(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("table-evidence-owner", "correct horse battery")
    _login(client, "table-evidence-owner")
    backlog = READY_BACKLOG.replace(
        "- The manifest refers to the exact approved document revisions.",
        "| Outcome |\n| --- |\n| The manifest refers to the exact approved document revisions. |",
    ).replace(
        "- Run the focused manifest approval tests.",
        "| Check | Result |\n| :--- | ---: |\n"
        "| Focused approval tests | Run the tests and verify the manifest revision IDs. |",
    )
    project_id, pair_approval, revision = _prepare_project(
        client, name="Ready task table data", saved_backlog=backlog
    )
    approved = _approve_manifest(client, project_id, pair_approval["id"], revision)
    assert approved.status_code == 200, approved.text
    response = client.get(f"/api/projects/{project_id}/final-approval/files/backlog")
    assert response.status_code == 200
    assert response.content == backlog.encode("utf-8")


@pytest.mark.parametrize(
    "invalid",
    [
        READY_BACKLOG.replace(
            "### Verification\n",
            "### Verification\n#### Pending: PostgreSQL concurrency\n"
            "- The concurrency test is planned for later.\n",
        ),
        READY_BACKLOG + "\n## Additional task notes\n### Owner decision\n- Decide later.\n",
        EMPTY_SCOPE_BEFORE_VERIFICATION,
        READY_BACKLOG.replace(
            "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
            "**Scope:**\n**Documentation impact:** Explain approved downloads.",
        ),
        READY_BACKLOG.replace(
            "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
            "**Scope:**\n**Open decisions:** None; download only approved revisions.",
        ),
        READY_BACKLOG.replace(
            "### Verification\n",
            "### Verification\n"
            "#### PostgreSQL concurrency unresolved — awaiting an integration fixture\n",
        ),
        READY_BACKLOG.replace(
            "**Scope:** api/app/project_approval_manifests.py; no repository writes.",
            "**Scope:**\n`Documentation impact:` Explain approved downloads.",
        ),
        READY_BACKLOG.replace(
            "- Run the focused manifest approval tests.",
            "**Documentation impact:** Explain approved downloads in the user guide.",
        ),
        READY_BACKLOG.replace(
            "- The manifest refers to the exact approved document revisions.",
            "`Documentation impact:` Explain approved downloads in the user guide.",
        ),
    ],
    ids=[
        "pending-child-verification",
        "deferred-note-after-h2",
        "scope-before-verification",
        "scope-before-documentation-impact",
        "scope-before-open-decisions",
        "unfinished-heading-with-explanation",
        "scope-before-code-colon-metadata",
        "verification-metadata-only",
        "acceptance-metadata-only",
    ],
)
def test_existing_manifest_does_not_grandfather_an_invalid_backlog(
    client: TestClient,
    engine,
    account_factory,
    invalid: str,
) -> None:
    account_factory("invalidated-manifest-owner", "correct horse battery")
    _login(client, "invalidated-manifest-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client, name="Manifest invalidation on validation"
    )
    created = _approve_manifest(client, project_id, pair_approval["id"], backlog_revision)
    assert created.status_code == 200, created.text

    # Simulate detecting a previously approved, but invalid, immutable record.
    # In normal operation the API cannot modify that revision in place; status,
    # idempotent POST and every download must still re-evaluate it fail-closed.
    with Session(engine) as db:
        revision = db.get(ProjectDocumentRevision, uuid.UUID(created.json()["backlog"]["id"]))
        assert revision is not None
        revision.content = invalid
        revision.content_sha256 = hashlib.sha256(invalid.encode("utf-8")).hexdigest()
        db.commit()

    status_view = client.get(f"/api/projects/{project_id}/final-approval")
    assert status_view.status_code == 200
    assert status_view.json()["approved"] is False
    assert status_view.json()["current_manifest"] is None
    assert status_view.json()["latest_manifest"]["id"] == created.json()["id"]
    assert "BACKLOG.md" in status_view.json()["validation_errors"]
    for kind in ("project", "agents", "backlog"):
        download = client.get(f"/api/projects/{project_id}/final-approval/files/{kind}")
        assert download.status_code == 409
    rejected = _approve_manifest(client, project_id, pair_approval["id"], backlog_revision)
    assert rejected.status_code == 422


def test_preconditions_require_a_current_pair_and_exact_backlog_revision(
    client: TestClient,
    engine,
    account_factory,
) -> None:
    account_factory("precondition-owner", "correct horse battery")
    _login(client, "precondition-owner")
    _set_backlog_template(client, STARTER_BACKLOG)
    project_id = _create_project(client, "Precondition planning")
    _save(client, project_id, "project", 1, PROJECT_TEXT)
    _save(client, project_id, "agents", 1, AGENTS_TEXT)
    saved_backlog = _save(client, project_id, "backlog", 1, VALID_BACKLOG)

    missing_pair = _approve_manifest(
        client,
        project_id,
        str(uuid.uuid4()),
        saved_backlog["revision_number"],
    )
    assert missing_pair.status_code == 409

    pair_approval = _approve_pair(client, project_id)
    wrong_pair = _approve_manifest(
        client,
        project_id,
        str(uuid.uuid4()),
        saved_backlog["revision_number"],
    )
    stale_backlog = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        saved_backlog["revision_number"] - 1,
    )
    assert wrong_pair.status_code == stale_backlog.status_code == 409
    assert wrong_pair.json()["current_pair_approval_id"] == pair_approval["id"]
    assert stale_backlog.json()["current_backlog_revision"]["revision_number"] == 2

    with Session(engine) as db:
        assert db.scalar(select(ProjectApprovalManifest.id).limit(1)) is None
    created = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        saved_backlog["revision_number"],
    )
    assert created.status_code == 200, created.text


@pytest.mark.parametrize("kind", ["project", "agents", "backlog"])
def test_any_new_revision_invalidates_manifest_even_when_bytes_are_unchanged(
    client: TestClient,
    account_factory,
    kind: str,
) -> None:
    account_factory("revision-owner", "correct horse battery")
    _login(client, "revision-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name=f"Same bytes {kind}",
    )
    created = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert created.status_code == 200, created.text
    content_by_kind = {
        "project": PROJECT_TEXT,
        "agents": AGENTS_TEXT,
        "backlog": VALID_BACKLOG,
    }
    saved = _save(client, project_id, kind, 2, content_by_kind[kind])
    assert saved["revision_number"] == 3
    assert saved["content_sha256"] == created.json()[kind]["content_sha256"]

    status_view = client.get(f"/api/projects/{project_id}/final-approval").json()
    assert status_view["approved"] is False
    assert status_view["current_manifest"] is None
    assert status_view["latest_manifest"]["id"] == created.json()["id"]
    for file_kind in ("project", "agents", "backlog"):
        denied = client.get(f"/api/projects/{project_id}/final-approval/files/{file_kind}")
        assert denied.status_code == 409

    stale = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert stale.status_code == 409


@pytest.mark.parametrize("kind", ["project", "agents", "backlog"])
def test_manifest_validation_fails_closed_on_revision_digest_mismatch(
    client: TestClient,
    engine,
    account_factory,
    kind: str,
) -> None:
    account_factory("digest-owner", "correct horse battery")
    _login(client, "digest-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name=f"Digest mismatch {kind}",
    )
    created = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert created.status_code == 200, created.text

    with Session(engine) as db:
        document = db.scalar(
            select(ProjectDocument).where(
                ProjectDocument.project_id == uuid.UUID(project_id),
                ProjectDocument.kind == kind,
            )
        )
        assert document is not None
        revision = db.scalar(
            select(ProjectDocumentRevision).where(
                ProjectDocumentRevision.document_id == document.id,
                ProjectDocumentRevision.revision_number == document.head_revision_number,
            )
        )
        assert revision is not None and revision.content_sha256
        first = "0" if revision.content_sha256[0] != "0" else "1"
        revision.content_sha256 = first + revision.content_sha256[1:]
        db.commit()

    status_view = client.get(f"/api/projects/{project_id}/final-approval")
    assert status_view.status_code == 200
    assert status_view.json()["approved"] is False
    assert status_view.json()["current_manifest"] is None
    filename = {"project": "PROJECT.md", "agents": "AGENTS.md", "backlog": "BACKLOG.md"}[kind]
    assert any(
        "digest does not match" in error.lower()
        for error in status_view.json()["validation_errors"][filename]
    )
    denied = client.get(f"/api/projects/{project_id}/final-approval/files/{kind}")
    assert denied.status_code == 409

    rejected = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert rejected.status_code == 422, rejected.text


def test_manifest_routes_enforce_auth_project_access_csrf_and_admin_read_audits(
    client: TestClient,
    engine,
    settings: AppSettings,
    workspace_root: Path,
    account_factory,
) -> None:
    account_factory("manifest-private-owner", "correct horse battery")
    account_factory("manifest-outsider", "correct horse battery")
    admin_id = account_factory("manifest-auditor", "correct horse battery", role="admin")
    _login(client, "manifest-private-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name="Manifest private project",
    )
    created = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert created.status_code == 200
    status_path = f"/api/projects/{project_id}/final-approval"
    download_path = f"{status_path}/files/project"

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as anonymous:
        assert anonymous.get(status_path).status_code == 401
        assert anonymous.get(download_path).status_code == 401

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as outsider:
        _login(outsider, "manifest-outsider")
        denied_status = outsider.get(status_path)
        denied_download = outsider.get(download_path)
        denied_post = _approve_manifest(
            outsider,
            project_id,
            pair_approval["id"],
            backlog_revision,
        )
        guessed_manifest = outsider.get(f"{status_path}/files/project/{created.json()['id']}")
    assert (
        denied_status.status_code == denied_download.status_code == denied_post.status_code == 404
    )
    assert guessed_manifest.status_code == 404
    assert "Northstar" not in denied_status.text

    bad_origin = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
        headers=_headers(client, origin="https://attacker.invalid"),
    )
    missing_csrf = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
        headers={"Origin": PUBLIC_ORIGIN},
    )
    bad_number = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        True,  # type: ignore[arg-type] -- strict validation must reject bool as an integer.
    )
    extra_field = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
        extras={"approved": True},
    )
    assert bad_origin.status_code == missing_csrf.status_code == 403
    assert bad_number.status_code == extra_field.status_code == 422

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as admin:
        _login(admin, "manifest-auditor")
        admin_status = admin.get(status_path)
        repeated = _approve_manifest(
            admin,
            project_id,
            pair_approval["id"],
            backlog_revision,
        )
        downloaded = admin.get(download_path)
    assert admin_status.status_code == 200 and admin_status.json()["approved"] is True
    assert repeated.status_code == 200 and repeated.json()["id"] == created.json()["id"]
    assert downloaded.status_code == 200 and downloaded.content == PROJECT_TEXT.encode("utf-8")

    with Session(engine) as db:
        admin_reads = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.actor_user_id == admin_id,
                    AuditEvent.project_id == uuid.UUID(project_id),
                    AuditEvent.action.in_(
                        (
                            "admin.project.approval_manifest.read",
                            "admin.project.approved_file.read",
                        )
                    ),
                )
            ).all()
        )
        assert {event.action for event in admin_reads} == {
            "admin.project.approval_manifest.read",
            "admin.project.approved_file.read",
        }
        assert all(event.created_at is not None for event in admin_reads)
        assert (
            db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "project.approval_manifest.approved",
                    AuditEvent.project_id == uuid.UUID(project_id),
                )
            )
            == 1
        )


def test_manifest_reauthenticates_after_rate_limit_commit(
    client: TestClient,
    engine,
    account_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = account_factory("manifest-race-owner", "correct horse battery")
    _login(client, "manifest-race-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name="Manifest account recheck",
    )
    original_consume = manifest_module.consume_rate_bucket

    def deactivate_during_limiter_commit(db, **kwargs):
        decision = original_consume(db, **kwargs)
        db.execute(update(User).where(User.id == owner_id).values(is_active=False))
        return decision

    monkeypatch.setattr(manifest_module, "consume_rate_bucket", deactivate_during_limiter_commit)
    response = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert response.status_code == 401

    with Session(engine) as db:
        user = db.get(User, owner_id)
        assert user is not None and user.is_active is False
        assert db.scalar(select(ProjectApprovalManifest.id).limit(1)) is None
        assert (
            db.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.action == "project.approval_manifest.approved"
                )
            )
            is None
        )


def test_manifest_creation_is_rate_limited(
    client: TestClient,
    account_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_factory("manifest-limited-owner", "correct horse battery")
    _login(client, "manifest-limited-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name="Manifest rate limit",
    )

    monkeypatch.setattr(
        manifest_module,
        "consume_rate_bucket",
        lambda *_args, **_kwargs: RateLimitDecision(allowed=False, retry_after_seconds=120),
    )
    denied = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "120"
    with Session(client.app.state.database_engine) as db:
        assert db.scalar(select(ProjectApprovalManifest.id).limit(1)) is None


@pytest.mark.parametrize("commit_was_durable", [False, True], ids=["rolled-back", "uncertain"])
def test_manifest_commit_failure_is_atomic_and_safe_to_retry(
    client: TestClient,
    engine,
    account_factory,
    monkeypatch: pytest.MonkeyPatch,
    commit_was_durable: bool,
) -> None:
    account_factory("manifest-commit-owner", "correct horse battery")
    _login(client, "manifest-commit-owner")
    project_id, pair_approval, backlog_revision = _prepare_project(
        client,
        name="Manifest commit recovery",
    )
    original_commit = Session.commit
    commit_count = 0

    def fail_manifest_commit(db: Session) -> None:
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            if commit_was_durable:
                original_commit(db)
            raise OperationalError("COMMIT", {}, Exception("injected manifest commit failure"))
        original_commit(db)

    monkeypatch.setattr(Session, "commit", fail_manifest_commit)
    unavailable = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert unavailable.status_code == 503

    with Session(engine) as db:
        persisted = list(
            db.scalars(
                select(ProjectApprovalManifest).where(
                    ProjectApprovalManifest.project_id == uuid.UUID(project_id)
                )
            ).all()
        )
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "project.approval_manifest.approved",
                    AuditEvent.project_id == uuid.UUID(project_id),
                )
            ).all()
        )
    assert len(persisted) == len(events) == int(commit_was_durable)

    monkeypatch.undo()
    retried = _approve_manifest(
        client,
        project_id,
        pair_approval["id"],
        backlog_revision,
    )
    assert retried.status_code == 200, retried.text
    with Session(engine) as db:
        final_manifest_count = db.scalar(
            select(func.count(ProjectApprovalManifest.id)).where(
                ProjectApprovalManifest.project_id == uuid.UUID(project_id)
            )
        )
        final_event_count = db.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "project.approval_manifest.approved",
                AuditEvent.project_id == uuid.UUID(project_id),
            )
        )
    assert final_manifest_count == final_event_count == 1
    if commit_was_durable:
        assert retried.json()["id"] == str(persisted[0].id)
