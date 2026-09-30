from __future__ import annotations

import hashlib
import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import project_documents as project_documents_module
from app.config import AppSettings
from app.main import create_app
from app.models import (
    AuditEvent,
    DocumentConflictProposal,
    ProjectDocument,
    ProjectDocumentRevision,
)
from app.project_templates import ProjectTemplate
from app.rate_limit import RateLimitDecision, consume_rate_bucket

PUBLIC_ORIGIN = "http://127.0.0.1:8080"

VALID_BACKLOG = """# Runner-compatible fixture

## [x] TASK-001 — Foundation

**Depends on:** None
**Branch:** foundation
**PR:** https://example.invalid/123
### Done looks like
- A saved outcome is immutable.
### Verification
- Run the root helper.

---

## [ ] TASK-002 — Ready follow-up

**Depends on:** TASK-001
**Branch:** task-two
**PR:** pending
**Scope:** A ready task that can run.
### Done looks like
- The saved body remains readable.
### Verification
- Run focused tests.

---

## [-] TASK-003 — Draft prerequisite

**Depends on:** None
### Done looks like
- Keep this as a draft.
### Verification
- Review the saved text.

---

## [ ] TASK-004 — Waiting follow-up

**Depends on:** TASK-003
### Done looks like
- Wait for TASK-003.
### Verification
- Check eligibility.
"""


def _login(client: TestClient, username: str, password: str = "correct horse battery") -> None:
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200


def _headers(client: TestClient, *, origin: str = PUBLIC_ORIGIN) -> dict[str, str]:
    return {
        "Origin": origin,
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }


def _use_fixture_backlog_template(
    client: TestClient,
    content: str = VALID_BACKLOG,
) -> None:
    templates = client.app.state.project_templates
    template = templates["backlog"]
    templates["backlog"] = ProjectTemplate(
        kind="backlog",
        source=template.source,
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _create_project(client: TestClient, name: str = "Backlog API plan") -> str:
    response = client.post("/api/projects", json={"name": name}, headers=_headers(client))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _task(tasks: list[dict[str, object]], task_id: str) -> dict[str, object]:
    return next(task for task in tasks if task["id"] == task_id)


def _root_helper() -> ModuleType:
    helper_path = next(
        (
            parent / "scripts" / "backlog.py"
            for parent in Path(__file__).resolve().parents
            if (parent / "scripts" / "backlog.py").is_file()
        ),
        None,
    )
    if helper_path is None:
        container_copy = Path("/opt/impostr-compat/backlog.py")
        helper_path = container_copy if container_copy.is_file() else None
    assert helper_path is not None, "the root backlog compatibility helper is required"
    spec = importlib.util.spec_from_file_location("root_backlog_helper", helper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_task_view_uses_one_saved_revision_and_separates_readiness_from_eligibility(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    _use_fixture_backlog_template(client)
    project_id = _create_project(client)

    task_view = client.get(f"/api/projects/{project_id}/backlog/tasks")
    raw_document = client.get(f"/api/projects/{project_id}/documents/backlog")

    assert task_view.status_code == raw_document.status_code == 200
    result = task_view.json()
    assert result["revision_number"] == raw_document.json()["revision_number"] == 1
    assert result["content"] == raw_document.json()["content"] == VALID_BACKLOG
    assert result["content_sha256"] == raw_document.json()["content_sha256"]
    assert result["summary"] == {
        "draft_count": 1,
        "ready_count": 2,
        "eligible_count": 1,
        "waiting_count": 1,
    }
    ready = _task(result["tasks"], "TASK-002")
    waiting = _task(result["tasks"], "TASK-004")
    assert ready["ready"] is True and ready["eligible"] is True
    assert waiting["ready"] is True and waiting["eligible"] is False
    assert waiting["waiting_on"] == ["TASK-003"]
    assert "saved body remains readable" in str(ready["acceptance"])
    assert "Run focused tests" in str(ready["verification"])


def test_task_mutations_require_project_authorization_origin_and_csrf(
    client: TestClient,
    engine,
    settings: AppSettings,
    account_factory,
    workspace_root: Path,
) -> None:
    owner_id = account_factory("owner", "correct horse battery")
    account_factory("other", "correct horse battery")
    account_factory("admin", "correct horse battery", role="admin")
    _login(client, "owner")
    _use_fixture_backlog_template(client)
    project_id = _create_project(client)

    assert client.get(f"/api/projects/{project_id}/backlog/tasks").status_code == 200
    missing_csrf = client.post(
        f"/api/projects/{project_id}/backlog/tasks",
        json={
            "expected_revision": 1,
            "id": "TASK-005",
            "title": "No CSRF",
            "body": "**Depends on:** None\n",
        },
        headers={"Origin": PUBLIC_ORIGIN},
    )
    task_two_body = _task(
        client.get(f"/api/projects/{project_id}/backlog/tasks").json()["tasks"],
        "TASK-002",
    )["body"]
    wrong_origin = client.put(
        f"/api/projects/{project_id}/backlog/tasks/TASK-002",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Wrong origin",
            "body": str(task_two_body),
        },
        headers=_headers(client, origin="https://attacker.invalid"),
    )
    assert missing_csrf.status_code == wrong_origin.status_code == 403

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as other_client:
        _login(other_client, "other")
        denied_read = other_client.get(f"/api/projects/{project_id}/backlog/tasks")
        denied_write = other_client.put(
            f"/api/projects/{project_id}/backlog/tasks/TASK-002",
            json={
                "expected_revision": 1,
                "status": " ",
                "title": "Foreign attempt",
                "body": "**Depends on:** TASK-001\n",
            },
            headers=_headers(other_client),
        )
    assert denied_read.status_code == denied_write.status_code == 404
    assert "Runner-compatible fixture" not in denied_read.text

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as admin_client:
        _login(admin_client, "admin")
        assert admin_client.get(f"/api/projects/{project_id}/backlog/tasks").status_code == 200

    with Session(engine) as db:
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.actor_user_id != owner_id,
                AuditEvent.action == "admin.project.backlog_tasks.read",
                AuditEvent.project_id == uuid.UUID(project_id),
            )
        )
        assert audit is not None
        assert audit.details == {"revision_number": 1, "task_count": 4}


def test_create_and_edit_tasks_preserve_ids_body_metadata_and_revision_history(
    client: TestClient,
    engine,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    _use_fixture_backlog_template(client)
    project_id = _create_project(client)
    endpoint = f"/api/projects/{project_id}/backlog/tasks"
    headers = _headers(client)
    initial = client.get(endpoint).json()
    task_two = _task(initial["tasks"], "TASK-002")

    updated = client.put(
        f"{endpoint}/TASK-002",
        json={
            "expected_revision": 1,
            "status": "-",
            "title": "Revised follow-up",
            "body": str(task_two["body"]).replace(
                "The saved body remains readable.", "The task body is editable."
            ),
            "dependencies": ["TASK-003"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    saved = updated.json()
    assert saved["revision_number"] == 2
    saved_task = _task(saved["tasks"], "TASK-002")
    assert saved_task["status"] == "-"
    assert saved_task["title"] == "Revised follow-up"
    assert saved_task["dependencies"] == ["TASK-003"]
    assert saved_task["waiting_on"] == ["TASK-003"]
    assert saved_task["ready"] is False and saved_task["eligible"] is False
    assert "The task body is editable." in saved_task["acceptance"]
    assert "**Branch:** task-two\n**PR:** pending" in saved_task["body"]
    assert saved["content"] == (
        VALID_BACKLOG.replace(
            "## [ ] TASK-002 — Ready follow-up", "## [-] TASK-002 — Revised follow-up"
        )
        .replace("The saved body remains readable.", "The task body is editable.")
        .replace("**Depends on:** TASK-001", "**Depends on:** TASK-003", 1)
    )
    assert "# Runner-compatible fixture\n" in saved["content"]
    assert "## [x] TASK-001 — Foundation" in saved["content"]

    draft_body = (
        "**Depends on:** TASK-001\n"
        "**Scope:** New scope.\n\n"
        "### Done looks like\n- The new task remains a draft.\n\n"
        "### Verification\n- Run the fixture tests.\n"
    )
    created = client.post(
        endpoint,
        json={
            "expected_revision": 2,
            "id": "TASK-005",
            "title": "New draft",
            "body": draft_body,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    created_result = created.json()
    created_task = _task(created_result["tasks"], "TASK-005")
    assert created_task["status"] == "-"
    assert created_task["dependencies"] == ["TASK-001"]
    assert created_task["ready"] is False and created_task["eligible"] is False
    assert created_result["revision_number"] == 3

    invalid_status = client.post(
        endpoint,
        json={
            "expected_revision": 3,
            "id": "TASK-006",
            "title": "Cannot create ready",
            "status": " ",
            "body": "**Depends on:** None\n",
        },
        headers=headers,
    )
    unknown_dependency = client.post(
        endpoint,
        json={
            "expected_revision": 3,
            "id": "TASK-006",
            "title": "Unknown prerequisite",
            "body": "**Depends on:** TASK-999\n",
        },
        headers=headers,
    )
    duplicate_title = client.post(
        endpoint,
        json={
            "expected_revision": 3,
            "id": "TASK-006",
            "title": "revised FOLLOW-UP",
            "body": "**Depends on:** None\n",
        },
        headers=headers,
    )
    assert (
        invalid_status.status_code
        == unknown_dependency.status_code
        == duplicate_title.status_code
        == 422
    )

    protected_task = client.put(
        f"{endpoint}/TASK-001",
        json={
            "expected_revision": 3,
            "status": " ",
            "title": "Runner result changed",
            "body": "**Depends on:** None\n",
        },
        headers=headers,
    )
    assert protected_task.status_code == 409

    with Session(engine) as db:
        document = db.scalar(
            select(ProjectDocument).where(
                ProjectDocument.project_id == uuid.UUID(project_id),
                ProjectDocument.kind == "backlog",
            )
        )
        assert document is not None and document.head_revision_number == 3
        revisions = list(
            db.scalars(
                select(ProjectDocumentRevision).where(
                    ProjectDocumentRevision.document_id == document.id
                )
            ).all()
        )
        assert [revision.revision_number for revision in revisions] == [1, 2, 3]


@pytest.mark.parametrize("runner_status", ["~", "x", "!"])
def test_append_task_preserves_a_final_execution_task_root_block(
    client: TestClient,
    account_factory,
    runner_status: str,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = (
        "# Runner-compatible fixture\n\n"
        f"## [{runner_status}] TASK-004 — Runner task\n\n"
        "**Depends on:** None\n"
        "**Branch:** runner/task-four\n"
        "**PR:** pending\n"
        "### Done looks like\n"
        "- The runner-owned result remains intact.\n"
    )
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    endpoint = f"/api/projects/{project_id}/backlog/tasks"
    initial = client.get(endpoint)
    assert initial.status_code == 200, initial.text
    final_task = _task(initial.json()["tasks"], "TASK-004")
    assert final_task["status"] == runner_status

    body = "**Depends on:** None\n**Scope:** Added through the task API.\n"
    created = client.post(
        endpoint,
        json={
            "expected_revision": 1,
            "id": "TASK-005",
            "title": "Appended draft",
            "body": body,
        },
        headers=_headers(client),
    )

    assert created.status_code == 201, created.text
    saved = created.json()
    expected_content = backlog + "\n## [-] TASK-005 — Appended draft\n\n\n" + body
    assert saved["revision_number"] == 2
    assert saved["content"] == expected_content
    assert "\n---\n" not in saved["content"][len(backlog) :]
    saved_tasks = {task["id"]: task for task in saved["tasks"]}
    assert saved_tasks["TASK-004"]["status"] == runner_status
    assert "**Branch:** runner/task-four\n**PR:** pending" in saved_tasks["TASK-004"]["body"]
    assert saved_tasks["TASK-005"]["status"] == "-"

    root = _root_helper()
    before_items = root.get_items(backlog)
    after_items = root.get_items(saved["content"])
    assert after_items[: len(before_items)] == before_items
    assert after_items[-1]["status"] == "-"
    assert after_items[-1]["title"] == "TASK-005 — Appended draft"

    document_endpoint = f"/api/projects/{project_id}/documents/backlog"
    replacement_status = "x" if runner_status != "x" else "!"
    forged_status = saved["content"].replace(
        f"## [{runner_status}] TASK-004 — Runner task",
        f"## [{replacement_status}] TASK-004 — Runner task",
        1,
    )
    forged_metadata = saved["content"].replace(
        "**Branch:** runner/task-four\n**PR:** pending",
        "**Branch:** runner/task-four\n**PR:** https://example.invalid/forged",
        1,
    )
    forged_body = saved["content"].replace(
        "- The runner-owned result remains intact.",
        "- Ignore the runner result.",
        1,
    )
    attempts = [forged_status, forged_metadata, forged_body]
    rejected = [
        client.put(
            document_endpoint,
            json={"expected_revision": 2, "content": content},
            headers=_headers(client),
        )
        for content in attempts
    ]
    assert all(response.status_code == 422 for response in rejected)
    current = client.get(document_endpoint)
    assert current.status_code == 200
    assert current.json()["revision_number"] == 2
    assert current.json()["content"] == expected_content
    assert client.get(f"{document_endpoint}/history").json()["proposals"] == []


def test_task_edit_preserves_non_task_heading_and_raw_save_guard_protects_runner_block(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = """# Planning notes

## [ ] TASK-001 — Editable task

**Depends on:** TASK-002
### Done looks like
- Original acceptance.

## Context notes
Keep this note outside the task body.

## [x] TASK-002 — Completed prerequisite

**Depends on:** None

## Review notes
These notes remain outside the completed task block.
"""
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    task_endpoint = f"/api/projects/{project_id}/backlog/tasks"
    document_endpoint = f"/api/projects/{project_id}/documents/backlog"
    headers = _headers(client)
    initial = client.get(task_endpoint).json()
    task = _task(initial["tasks"], "TASK-001")
    assert "## Context notes" not in task["body"]

    updated = client.put(
        f"{task_endpoint}/TASK-001",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Edited task",
            "body": str(task["body"]).replace("Original acceptance.", "Updated acceptance."),
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    updated_content = updated.json()["content"]
    note = "## Context notes\nKeep this note outside the task body."
    assert note in updated_content
    assert (
        "## Review notes\nThese notes remain outside the completed task block." in updated_content
    )
    assert "## [x] TASK-002 — Completed prerequisite" in updated_content
    assert "## Review notes" not in _task(updated.json()["tasks"], "TASK-002")["body"]

    raw_edit = updated_content.replace("Updated acceptance.", "Raw-save acceptance.", 1)
    raw_saved = client.put(
        document_endpoint,
        json={"expected_revision": 2, "content": raw_edit},
        headers=headers,
    )
    assert raw_saved.status_code == 200, raw_saved.text
    assert note in raw_saved.json()["content"]

    forged_outcome = raw_saved.json()["content"].replace(
        "## [x] TASK-002 — Completed prerequisite",
        "## [ ] TASK-002 — Completed prerequisite",
        1,
    )
    denied = client.put(
        document_endpoint,
        json={"expected_revision": 3, "content": forged_outcome},
        headers=headers,
    )

    assert denied.status_code == 422
    current = client.get(task_endpoint).json()
    assert current["revision_number"] == 3
    assert note in current["content"]
    assert "## [x] TASK-002 — Completed prerequisite" in current["content"]
    assert (
        "## Review notes\nThese notes remain outside the completed task block."
        in current["content"]
    )


def test_raw_put_rejects_runner_metadata_after_h2_while_task_put_keeps_notes(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = """## [x] TASK-001 — Complete
**Depends on:** None

## Outcome details
Verified by runner.
**Branch:** original
**PR:** https://example.invalid/1

## [-] TASK-002 — Draft
**Depends on:** TASK-001

## Planning notes
**Branch:** retained
**PR:** pending
"""
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    task_path = f"/api/projects/{project_id}/backlog/tasks"
    document_path = f"/api/projects/{project_id}/documents/backlog"
    headers = _headers(client)
    draft = _task(client.get(task_path).json()["tasks"], "TASK-002")
    assert "## Planning notes" not in draft["body"]

    updated = client.put(
        f"{task_path}/TASK-002",
        json={
            "expected_revision": 1,
            "status": "-",
            "title": "Reworded draft",
            "body": draft["body"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["content"] == backlog.replace(
        "TASK-002 — Draft", "TASK-002 — Reworded draft"
    )

    for original, replacement in (
        ("Verified by runner.", "Not verified by runner."),
        ("**Branch:** original", "**Branch:** forged"),
        ("**PR:** https://example.invalid/1", "**PR:** https://example.invalid/2"),
        ("**Branch:** retained", "**Branch:** forged"),
        ("**PR:** pending", "**PR:** forged"),
    ):
        changed = updated.json()["content"].replace(original, replacement, 1)
        denied = client.put(
            document_path,
            json={"expected_revision": 2, "content": changed},
            headers=headers,
        )
        assert denied.status_code == 422, denied.text

    current = client.get(document_path).json()
    assert current["revision_number"] == 2
    assert current["content"] == updated.json()["content"]
    assert client.get(f"{document_path}/history").json()["proposals"] == []


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
@pytest.mark.parametrize("body_ending", ["newline", "none"])
def test_task_put_keeps_a_following_non_task_heading_separate_without_rewriting_bytes(
    client: TestClient,
    account_factory,
    line_ending: str,
    body_ending: str,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = line_ending.join(
        [
            "# Planning notes",
            "",
            "## [ ] TASK-001 — Editable task",
            "**Depends on:** None",
            "### Done looks like",
            "- Original acceptance.",
            "",
            "## Reference notes",
            "This note remains outside the task body.",
            "",
            "## [ ] TASK-002 — Follow-up",
            "**Depends on:** TASK-001",
        ]
    )
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    task_path = f"/api/projects/{project_id}/backlog/tasks"
    document_path = f"/api/projects/{project_id}/documents/backlog"
    initial = client.get(task_path)
    assert initial.status_code == 200, initial.text
    task = _task(initial.json()["tasks"], "TASK-001")
    assert "## Reference notes" not in str(task["body"])
    body = str(task["body"])
    if body_ending == "none":
        body = body.rstrip("\r\n")

    response = client.put(
        f"{task_path}/TASK-001",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Edited task",
            "body": body.replace("Original acceptance.", "Updated acceptance."),
        },
        headers=_headers(client),
    )

    if body_ending == "none":
        assert response.status_code == 422, response.text
        latest = client.get(document_path).json()
        assert latest["revision_number"] == 1
        assert latest["content"] == backlog
        history = client.get(f"{document_path}/history").json()
        assert [revision["revision_number"] for revision in history["revisions"]] == [1]
        assert history["proposals"] == []
        return

    assert response.status_code == 200, response.text
    saved = response.json()
    expected_content = backlog.replace(
        "## [ ] TASK-001 — Editable task",
        "## [ ] TASK-001 — Edited task",
        1,
    ).replace("Original acceptance.", "Updated acceptance.", 1)
    assert saved["revision_number"] == 2
    assert saved["content"] == expected_content
    assert "## Reference notes" in saved["content"]
    root = _root_helper()
    root_ready, root_waiting = root.eligible_items(saved["content"])
    assert [item["title"] for item in root_ready] == ["TASK-001 — Edited task"]
    assert [(item["title"], dependencies) for item, dependencies in root_waiting] == [
        ("TASK-002 — Follow-up", ["TASK-001"])
    ]
    saved_tasks = {item["id"]: item for item in saved["tasks"]}
    assert saved_tasks["TASK-001"]["eligible"] is True
    assert saved_tasks["TASK-002"]["waiting_on"] == ["TASK-001"]


@pytest.mark.parametrize("body", ["", "\n"])
def test_task_put_allows_an_empty_body_when_the_header_line_ends_before_a_note(
    client: TestClient,
    account_factory,
    body: str,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = "## [-] TASK-001 — Empty-body task\n## Reference notes\n**Depends on:** None\n"
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    task_path = f"/api/projects/{project_id}/backlog/tasks"
    initial = client.get(task_path)
    assert initial.status_code == 200, initial.text
    assert _task(initial.json()["tasks"], "TASK-001")["body"] == ""

    saved = client.put(
        f"{task_path}/TASK-001",
        json={
            "expected_revision": 1,
            "status": "-",
            "title": "Still empty",
            "body": body,
        },
        headers=_headers(client),
    )

    expected_content = backlog.replace(
        "## [-] TASK-001 — Empty-body task", "## [-] TASK-001 — Still empty", 1
    )
    if body:
        expected_content = expected_content.replace("## Reference notes", "\n## Reference notes", 1)
    assert saved.status_code == 200, saved.text
    assert saved.json()["content"] == expected_content
    assert _task(saved.json()["tasks"], "TASK-001")["body"] == body


def test_task_put_allows_an_unterminated_body_at_eof_and_preserves_horizontal_rule_notes(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    eof_backlog = (
        "## [-] TASK-001 — EOF task\r\n"
        "**Depends on:** None\r\n"
        "### Done looks like\r\n"
        "- Original acceptance."
    )
    _use_fixture_backlog_template(client, eof_backlog)
    project_id = _create_project(client)
    task_path = f"/api/projects/{project_id}/backlog/tasks"
    task = _task(client.get(task_path).json()["tasks"], "TASK-001")

    at_eof = client.put(
        f"{task_path}/TASK-001",
        json={
            "expected_revision": 1,
            "status": "-",
            "title": "Edited EOF task",
            "body": str(task["body"]).replace("Original acceptance.", "Updated acceptance."),
        },
        headers=_headers(client),
    )
    assert at_eof.status_code == 200, at_eof.text
    expected_eof = eof_backlog.replace("TASK-001 — EOF task", "TASK-001 — Edited EOF task", 1)
    expected_eof = expected_eof.replace("Original acceptance.", "Updated acceptance.", 1)
    assert at_eof.json()["content"] == expected_eof

    hr_backlog = (
        "## [-] TASK-001 — Horizontal rule task\n"
        "**Depends on:** None\n"
        "- Original acceptance.\n"
        "---\n"
        "\n## Reference notes\n"
        "This note stays after the separator.\n"
    )
    _use_fixture_backlog_template(client, hr_backlog)
    another_project = _create_project(client, "Horizontal rule plan")
    hr_path = f"/api/projects/{another_project}/backlog/tasks"
    hr_task = _task(client.get(hr_path).json()["tasks"], "TASK-001")
    saved = client.put(
        f"{hr_path}/TASK-001",
        json={
            "expected_revision": 1,
            "status": "-",
            "title": "Edited horizontal rule task",
            "body": str(hr_task["body"]).replace("Original acceptance.", "Updated acceptance."),
        },
        headers=_headers(client),
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["content"] == hr_backlog.replace(
        "TASK-001 — Horizontal rule task", "TASK-001 — Edited horizontal rule task", 1
    ).replace("Original acceptance.", "Updated acceptance.", 1)
    assert "\n---\n\n## Reference notes\n" in saved.json()["content"]


@pytest.mark.parametrize("task_status", ["-", " "])
def test_raw_put_rejects_all_line_oriented_metadata_variants_on_planning_tasks(
    client: TestClient,
    account_factory,
    task_status: str,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    metadata_lines = [
        "Branch:compact-value",
        "PR:compact-value",
        "Branch: spaced value",
        "PR: spaced value",
        "**Branch:**bold value",
        "**PR:** bold value",
        "- Branch: list value",
        "* **PR:** list value",
        "+ Branch: plus-list value",
        "3. PR: ordered-list value",
        "    Branch: indented value",
        "\t**PR:** tab-indented value",
    ]
    backlog = (
        f"## [{task_status}] TASK-001 — Planning task\n"
        "**Depends on:** None\n"
        "\n## Runner bookkeeping\n"
        + "\n".join(metadata_lines)
        + "\nInline prose mentions Branch: inline and PR: inline.\n"
        + "`Branch: inline-code`\n"
        + "```text\nBranch: fenced\nPR: fenced\n```\n"
        + "\n## [x] TASK-002 — Completed task\n"
        + "**Depends on:** None\n"
    )
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    document_path = f"/api/projects/{project_id}/documents/backlog"

    for metadata_line in metadata_lines:
        changed = backlog.replace(metadata_line, f"{metadata_line} forged", 1)
        response = client.put(
            document_path,
            json={"expected_revision": 1, "content": changed},
            headers=_headers(client),
        )
        assert response.status_code == 422, (metadata_line, response.text)

    current = client.get(document_path).json()
    assert current["revision_number"] == 1
    assert current["content"] == backlog
    history = client.get(f"{document_path}/history").json()
    assert [revision["revision_number"] for revision in history["revisions"]] == [1]
    assert history["proposals"] == []

    prose_edit = backlog.replace("Branch: inline and PR: inline", "Branch: edited and PR: edited")
    prose_edit = prose_edit.replace("Branch: fenced", "Branch: edited-fence")
    allowed = client.put(
        document_path,
        json={"expected_revision": 1, "content": prose_edit},
        headers=_headers(client),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["content"] == prose_edit


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_new_task_metadata_is_rejected_by_raw_and_task_routes_without_history(
    client: TestClient,
    account_factory,
    line_ending: str,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = f"## [-] TASK-001 — Existing draft{line_ending}**Depends on:** None{line_ending}"
    metadata_lines = [
        "Branch:compact-value",
        "PR:compact-value",
        "**Branch:** bold value",
        "**PR:** bold value",
        "- Branch: list value",
        "* **PR:** list value",
        "    Branch: indented value",
        "\t**PR:** tab-indented value",
    ]
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    task_path = f"/api/projects/{project_id}/backlog/tasks"
    document_path = f"/api/projects/{project_id}/documents/backlog"
    headers = _headers(client)

    for metadata_line in metadata_lines:
        body = f"**Depends on:** None{line_ending}{metadata_line}{line_ending}"
        created = client.post(
            task_path,
            json={
                "expected_revision": 1,
                "id": "TASK-002",
                "title": "New task API draft",
                "body": body,
            },
            headers=headers,
        )
        raw_content = backlog + line_ending + f"## [-] TASK-002 — New raw draft{line_ending}" + body
        raw_saved = client.put(
            document_path,
            json={"expected_revision": 1, "content": raw_content},
            headers=headers,
        )

        assert created.status_code == 422, (metadata_line, created.text)
        assert raw_saved.status_code == 422, (metadata_line, raw_saved.text)
        assert "Branch/PR metadata" in created.json()["detail"]
        assert "Branch/PR metadata" in raw_saved.json()["detail"]

    current = client.get(document_path).json()
    assert current["revision_number"] == 1
    assert current["content"] == backlog
    history = client.get(f"{document_path}/history").json()
    assert [revision["revision_number"] for revision in history["revisions"]] == [1]
    assert history["proposals"] == []


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_new_task_routes_allow_inline_and_fenced_branch_pr_prose(
    client: TestClient,
    account_factory,
    line_ending: str,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = f"## [-] TASK-001 — Existing draft{line_ending}**Depends on:** None{line_ending}"
    body = (
        f"**Depends on:** None{line_ending}"
        f"Inline prose mentions Branch: inline and PR: inline.{line_ending}"
        f"`Branch: inline code`{line_ending}"
        f"```text{line_ending}"
        f"Branch: fenced{line_ending}"
        f"PR: fenced{line_ending}"
        f"```{line_ending}"
    )
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    task_path = f"/api/projects/{project_id}/backlog/tasks"
    document_path = f"/api/projects/{project_id}/documents/backlog"
    headers = _headers(client)

    created = client.post(
        task_path,
        json={
            "expected_revision": 1,
            "id": "TASK-002",
            "title": "Inline and fenced prose",
            "body": body,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    raw_content = (
        created.json()["content"]
        + line_ending
        + f"## [-] TASK-003 — Raw inline and fenced prose{line_ending}"
        + body
    )
    raw_saved = client.put(
        document_path,
        json={"expected_revision": 2, "content": raw_content},
        headers=headers,
    )

    assert raw_saved.status_code == 200, raw_saved.text
    assert raw_saved.json()["revision_number"] == 3
    assert raw_saved.json()["content"] == raw_content
    history = client.get(f"{document_path}/history").json()
    assert [revision["revision_number"] for revision in history["revisions"]] == [3, 2, 1]
    assert history["proposals"] == []


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_stale_new_task_metadata_is_rejected_before_conflict_proposals(
    client: TestClient,
    account_factory,
    line_ending: str,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = f"## [-] TASK-001 — Existing draft{line_ending}**Depends on:** None{line_ending}"
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    task_path = f"/api/projects/{project_id}/backlog/tasks"
    document_path = f"/api/projects/{project_id}/documents/backlog"
    headers = _headers(client)
    original_task = _task(client.get(task_path).json()["tasks"], "TASK-001")

    winner = client.put(
        f"{task_path}/TASK-001",
        json={
            "expected_revision": 1,
            "status": "-",
            "title": "Updated existing draft",
            "body": original_task["body"],
        },
        headers=headers,
    )
    assert winner.status_code == 200
    assert winner.json()["revision_number"] == 2

    created = client.post(
        task_path,
        json={
            "expected_revision": 1,
            "id": "TASK-002",
            "title": "Stale task API draft",
            "body": f"**Depends on:** None{line_ending}**Branch:** forged{line_ending}",
        },
        headers=headers,
    )
    raw_content = (
        backlog
        + line_ending
        + f"## [-] TASK-002 — Stale raw draft{line_ending}"
        + f"**Depends on:** None{line_ending}"
        + f"PR: forged{line_ending}"
    )
    raw_saved = client.put(
        document_path,
        json={"expected_revision": 1, "content": raw_content},
        headers=headers,
    )

    assert created.status_code == 422, created.text
    assert raw_saved.status_code == 422, raw_saved.text
    current = client.get(document_path).json()
    assert current["revision_number"] == 2
    assert current["content"] == winner.json()["content"]
    history = client.get(f"{document_path}/history").json()
    assert [revision["revision_number"] for revision in history["revisions"]] == [2, 1]
    assert history["proposals"] == []

    valid_stale_create = client.post(
        task_path,
        json={
            "expected_revision": 1,
            "id": "TASK-003",
            "title": "Valid stale task API draft",
            "body": f"**Depends on:** None{line_ending}",
        },
        headers=headers,
    )
    assert valid_stale_create.status_code == 409
    assert valid_stale_create.json()["latest"]["revision_number"] == 2
    assert valid_stale_create.json()["proposal_id"]
    assert len(client.get(f"{document_path}/history").json()["proposals"]) == 1


def test_task_put_stale_edit_retains_conflict_proposal_behavior_with_following_heading(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = (
        "## [ ] TASK-001 — Editable task\n"
        "**Depends on:** None\n"
        "- Original acceptance.\n"
        "\n## Reference notes\n"
        "Keep this section separate.\n"
    )
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    task_path = f"/api/projects/{project_id}/backlog/tasks"
    document_path = f"/api/projects/{project_id}/documents/backlog"
    original = _task(client.get(task_path).json()["tasks"], "TASK-001")
    safe_body = str(original["body"])

    winner = client.put(
        f"{task_path}/TASK-001",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Winning edit",
            "body": safe_body.replace("Original acceptance.", "Winning acceptance."),
        },
        headers=_headers(client),
    )
    stale = client.put(
        f"{task_path}/TASK-001",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Stale edit",
            "body": safe_body.replace("Original acceptance.", "Stale acceptance."),
        },
        headers=_headers(client),
    )

    assert winner.status_code == 200 and winner.json()["revision_number"] == 2
    assert stale.status_code == 409
    assert stale.json()["latest"]["revision_number"] == 2
    assert stale.json()["proposal_id"]
    history = client.get(f"{document_path}/history").json()
    assert [revision["revision_number"] for revision in history["revisions"]] == [2, 1]
    assert len(history["proposals"]) == 1


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_task_put_edits_external_dependency_without_owning_the_note_or_runner_metadata(
    client: TestClient,
    account_factory,
    line_ending: str,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = """# Planning notes

## [ ] TASK-001 — Dependent

### Done looks like
- Original acceptance.

## Dependency notes
This Markdown note remains outside the task editor body.
**Branch:** retained-branch
**PR:** pending
**Depends on:** TASK-002
This trailing note is also preserved.

## Later dependency context
This heading remains beyond the changed dependency value.

## [x] TASK-002 — Completed prerequisite
**Depends on:** None
**Branch:** completed-branch
**PR:** https://example.invalid/2

## [-] TASK-003 — Draft prerequisite
**Depends on:** None

## [-] TASK-3 — Alternate draft prerequisite
**Depends on:** None
"""
    backlog = backlog.replace("\n", line_ending)
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    endpoint = f"/api/projects/{project_id}/backlog/tasks"
    initial = client.get(endpoint)
    assert initial.status_code == 200, initial.text
    task = _task(initial.json()["tasks"], "TASK-001")
    assert "## Dependency notes" not in str(task["body"])
    assert task["dependencies"] == ["TASK-002"]
    assert task["ready"] is True and task["eligible"] is True

    updated = client.put(
        f"{endpoint}/TASK-001",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Revised dependent",
            "body": str(task["body"]).replace("Original acceptance.", "Edited acceptance."),
            "dependencies": ["TASK-3"],
        },
        headers=_headers(client),
    )

    assert updated.status_code == 200, updated.text
    saved = updated.json()
    expected_content = (
        backlog.replace(
            "## [ ] TASK-001 — Dependent",
            "## [ ] TASK-001 — Revised dependent",
            1,
        )
        .replace("Original acceptance.", "Edited acceptance.", 1)
        .replace("**Depends on:** TASK-002", "**Depends on:** TASK-3", 1)
    )
    assert saved["revision_number"] == 2
    assert saved["content"] == expected_content
    revised_task = _task(saved["tasks"], "TASK-001")
    assert revised_task["dependencies"] == ["TASK-3"]
    assert revised_task["waiting_on"] == ["TASK-3"]
    assert revised_task["ready"] is True and revised_task["eligible"] is False
    root_ready, root_waiting = _root_helper().eligible_items(saved["content"])
    assert root_ready == []
    assert [(item["title"], dependencies) for item, dependencies in root_waiting] == [
        ("TASK-001 — Revised dependent", ["TASK-3"])
    ]


def test_task_put_rejects_invalid_unknown_and_cyclic_external_dependencies(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = """## [ ] TASK-001 — Parent
### Done looks like
- Remains editable.

## Dependency notes
**Depends on:** None

## [ ] TASK-002 — Child
**Depends on:** TASK-001
"""
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    endpoint = f"/api/projects/{project_id}/backlog/tasks"
    task = _task(client.get(endpoint).json()["tasks"], "TASK-001")
    headers = _headers(client)

    def update(dependencies: list[str] | None):
        return client.put(
            f"{endpoint}/TASK-001",
            json={
                "expected_revision": 1,
                "status": " ",
                "title": "Parent",
                "body": task["body"],
                "dependencies": dependencies,
            },
            headers=headers,
        )

    invalid = update(["not-an-id"])
    unknown = update(["TASK-999"])
    cyclic = update(["TASK-002"])
    null_dependencies = update(None)

    assert invalid.status_code == 422
    assert unknown.status_code == 422
    assert "unknown dependency" in unknown.json()["detail"].lower()
    assert cyclic.status_code == 422
    assert "cycle" in cyclic.json()["detail"].lower()
    assert null_dependencies.status_code == 422
    current = client.get(endpoint).json()
    assert current["revision_number"] == 1
    assert current["content"] == backlog
    assert (
        client.get(f"/api/projects/{project_id}/documents/backlog/history").json()["proposals"]
        == []
    )


def test_create_task_fails_closed_when_backlog_ends_inside_a_fenced_example(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = VALID_BACKLOG + "\n```markdown\n## [ ] TASK-999 — Example only\n"
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    endpoint = f"/api/projects/{project_id}/backlog/tasks"
    initial = client.get(endpoint)
    assert initial.status_code == 200

    response = client.post(
        endpoint,
        json={
            "expected_revision": 1,
            "id": "TASK-005",
            "title": "Must not land inside the example",
            "body": "**Depends on:** None\n",
        },
        headers=_headers(client),
    )

    assert response.status_code == 422
    assert "fenced" in response.json()["detail"].lower()
    current = client.get(endpoint).json()
    assert current["revision_number"] == 1
    assert all(task["id"] != "TASK-005" for task in current["tasks"])


def test_task_write_stale_revision_creates_a_conflict_proposal(
    client: TestClient,
    engine,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    _use_fixture_backlog_template(client)
    project_id = _create_project(client)
    endpoint = f"/api/projects/{project_id}/backlog/tasks"
    headers = _headers(client)
    initial = client.get(endpoint).json()
    task_two = _task(initial["tasks"], "TASK-002")
    task_four = _task(initial["tasks"], "TASK-004")

    winner = client.put(
        f"{endpoint}/TASK-002",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Saved follow-up",
            "body": task_two["body"],
        },
        headers=headers,
    )
    assert winner.status_code == 200 and winner.json()["revision_number"] == 2

    stale = client.put(
        f"{endpoint}/TASK-004",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Stale proposal follow-up",
            "body": task_four["body"],
        },
        headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json()["latest"]["revision_number"] == 2
    assert stale.json()["proposal_id"]

    with Session(engine) as db:
        document = db.scalar(
            select(ProjectDocument).where(
                ProjectDocument.project_id == uuid.UUID(project_id),
                ProjectDocument.kind == "backlog",
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
        assert len(proposals) == 1
        assert proposals[0].expected_revision_number == 1
        assert proposals[0].observed_revision_number == 2
        assert "Stale proposal follow-up" in proposals[0].content


def test_raw_backlog_write_stale_revision_preserves_the_newer_head_and_proposal(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    _use_fixture_backlog_template(client)
    project_id = _create_project(client)
    task_endpoint = f"/api/projects/{project_id}/backlog/tasks"
    document_endpoint = f"/api/projects/{project_id}/documents/backlog"
    headers = _headers(client)

    winner = client.put(
        f"{task_endpoint}/TASK-002",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Latest task edit",
            "body": _task(client.get(task_endpoint).json()["tasks"], "TASK-002")["body"],
        },
        headers=headers,
    )
    assert winner.status_code == 200 and winner.json()["revision_number"] == 2

    stale_content = VALID_BACKLOG.replace("Waiting follow-up", "Stale whole-document edit")
    stale = client.put(
        document_endpoint,
        json={"expected_revision": 1, "content": stale_content},
        headers=headers,
    )

    assert stale.status_code == 409
    assert stale.json()["latest"]["revision_number"] == 2
    assert "Latest task edit" in stale.json()["latest"]["content"]
    history = client.get(f"{document_endpoint}/history")
    assert history.status_code == 200
    assert len(history.json()["proposals"]) == 1
    proposal_id = history.json()["proposals"][0]["id"]
    proposal = client.get(f"{document_endpoint}/proposals/{proposal_id}")
    assert proposal.status_code == 200
    assert "Stale whole-document edit" in proposal.json()["content"]


@pytest.mark.parametrize("runner_status", ["~", "x", "!"])
def test_execution_task_blocks_are_read_only_through_task_and_raw_document_routes(
    client: TestClient,
    account_factory,
    runner_status: str,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = VALID_BACKLOG.replace(
        "## [x] TASK-001 — Foundation",
        f"## [{runner_status}] TASK-001 — Foundation",
        1,
    )
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    task_endpoint = f"/api/projects/{project_id}/backlog/tasks"
    document_endpoint = f"/api/projects/{project_id}/documents/backlog"
    headers = _headers(client)
    task = _task(client.get(task_endpoint).json()["tasks"], "TASK-001")

    task_edit = client.put(
        f"{task_endpoint}/TASK-001",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Forged runner result",
            "body": task["body"],
        },
        headers=headers,
    )
    forged_status = backlog.replace(f"## [{runner_status}] TASK-001", "## [-] TASK-001", 1)
    edited_runner_block = backlog.replace(
        "A saved outcome is immutable.", "A rewritten runner result.", 1
    )
    raw_status_edit = client.put(
        document_endpoint,
        json={"expected_revision": 1, "content": forged_status},
        headers=headers,
    )
    raw_body_edit = client.put(
        document_endpoint,
        json={"expected_revision": 1, "content": edited_runner_block},
        headers=headers,
    )

    assert task_edit.status_code == 409
    assert raw_status_edit.status_code == raw_body_edit.status_code == 422
    assert client.get(task_endpoint).json()["revision_number"] == 1


def test_document_backlog_put_cannot_bypass_task_transition_and_metadata_guards(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    _use_fixture_backlog_template(client)
    project_id = _create_project(client)
    path = f"/api/projects/{project_id}/documents/backlog"
    initial = client.get(path).json()

    forged_outcome = initial["content"].replace("## [x] TASK-001", "## [ ] TASK-001", 1)
    removed_metadata = initial["content"].replace("**PR:** pending\n", "", 1)
    new_ready_task = (
        initial["content"] + "\n## [ ] TASK-005 — Must start as draft\n\n**Depends on:** None\n"
    )
    unknown_dependency = initial["content"].replace(
        "**Depends on:** TASK-003", "**Depends on:** TASK-999", 1
    )
    malformed_heading = initial["content"].replace("## [ ] TASK-002", "## [?] TASK-002", 1)
    attempts = [
        forged_outcome,
        removed_metadata,
        new_ready_task,
        unknown_dependency,
        malformed_heading,
    ]

    responses = [
        client.put(
            path,
            json={"expected_revision": 1, "content": content},
            headers=_headers(client),
        )
        for content in attempts
    ]
    assert all(response.status_code == 422 for response in responses)
    assert client.get(path).json()["revision_number"] == 1
    assert client.get(f"{path}/history").json()["proposals"] == []


def test_task_writes_reuse_document_rate_limit(
    client: TestClient,
    account_factory,
    monkeypatch,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    _use_fixture_backlog_template(client)
    project_id = _create_project(client)
    task_two = _task(
        client.get(f"/api/projects/{project_id}/backlog/tasks").json()["tasks"],
        "TASK-002",
    )

    def deny_rate_limit(*_args: object, **_kwargs: object) -> RateLimitDecision:
        return RateLimitDecision(allowed=False, retry_after_seconds=45)

    monkeypatch.setattr(project_documents_module, "consume_rate_bucket", deny_rate_limit)
    denied = client.put(
        f"/api/projects/{project_id}/backlog/tasks/TASK-002",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Must remain unsaved",
            "body": task_two["body"],
        },
        headers=_headers(client),
    )

    assert denied.status_code == 429
    assert denied.headers["Retry-After"] == "45"
    assert client.get(f"/api/projects/{project_id}/backlog/tasks").json()["revision_number"] == 1
    monkeypatch.setattr(project_documents_module, "consume_rate_bucket", consume_rate_bucket)


def test_unauthenticated_backlog_task_routes_are_denied(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")

    assert (
        client.get("/api/projects/00000000-0000-4000-8000-000000000001/backlog/tasks").status_code
        == 401
    )


def test_task_update_rejects_unicode_line_breaks_in_titles(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    _use_fixture_backlog_template(client)
    project_id = _create_project(client)
    endpoint = f"/api/projects/{project_id}/backlog/tasks"
    task = _task(client.get(endpoint).json()["tasks"], "TASK-002")

    for title in ("First\u2028Second", "First\u0085Second", "First\vSecond"):
        response = client.put(
            f"{endpoint}/TASK-002",
            json={
                "expected_revision": 1,
                "status": " ",
                "title": title,
                "body": task["body"],
            },
            headers=_headers(client),
        )
        assert response.status_code == 422

    assert client.get(endpoint).json()["revision_number"] == 1


def test_task_update_repairs_an_imported_unicode_heading_separator(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("planner", "correct horse battery")
    _login(client, "planner")
    backlog = "# Unicode separator\n\n## [ ] TASK-001 — First\u2028**Depends on:** None\n"
    _use_fixture_backlog_template(client, backlog)
    project_id = _create_project(client)
    endpoint = f"/api/projects/{project_id}/backlog/tasks"
    task = _task(client.get(endpoint).json()["tasks"], "TASK-001")

    updated = client.put(
        f"{endpoint}/TASK-001",
        json={
            "expected_revision": 1,
            "status": " ",
            "title": "Updated first task",
            "body": task["body"],
        },
        headers=_headers(client),
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["content"].endswith(
        "## [ ] TASK-001 — Updated first task\n**Depends on:** None\n"
    )
