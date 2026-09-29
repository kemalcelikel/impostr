from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import document_pair_approvals as approval_module
from app.config import AppSettings
from app.main import create_app
from app.models import AuditEvent, ProjectDocumentPairApproval, ProjectDocumentRevision, User
from app.project_templates import ProjectTemplate

PUBLIC_ORIGIN = "http://127.0.0.1:8080"


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


PROJECT_TEXT = valid_project()
AGENTS_TEXT = valid_agents()


def _login(client: TestClient, username: str, password: str) -> None:
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


def _create_project(client: TestClient, name: str = "Approval test plan") -> str:
    response = client.post("/api/projects", json={"name": name}, headers=_headers(client))
    assert response.status_code == 201
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


def _approve(
    client: TestClient,
    project_id: str,
    project_revision: object,
    agents_revision: object,
    *,
    body_extras: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
):
    payload: dict[str, object] = {
        "expected_project_revision": project_revision,
        "expected_agents_revision": agents_revision,
    }
    if body_extras:
        payload.update(body_extras)
    return client.post(
        f"/api/projects/{project_id}/document-pair-approval",
        json=payload,
        headers=headers if headers is not None else _headers(client),
    )


def test_approval_validation_is_per_file_and_uses_revision_one_provenance(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)

    unchanged_starter = _approve(client, project_id, 1, 1)
    assert unchanged_starter.status_code == 422
    unchanged_files = unchanged_starter.json()["detail"]["files"]
    assert set(unchanged_files) == {"PROJECT.md", "AGENTS.md"}
    assert all(
        any("starter" in message.lower() for message in messages)
        for messages in unchanged_files.values()
    )
    assert all(
        any("unchanged from its saved starter" in message.lower() for message in messages)
        for messages in unchanged_files.values()
    )

    _save(client, project_id, "project", 1, PROJECT_TEXT)
    placeholder = "# Agent rules for <PROJECT_NAME>\n\nUse the agreed toolchain.\n"
    _save(client, project_id, "agents", 1, placeholder)
    unresolved = _approve(client, project_id, 2, 2)
    assert unresolved.status_code == 422
    assert set(unresolved.json()["detail"]["files"]) == {"AGENTS.md"}
    assert "placeholder" in " ".join(unresolved.json()["detail"]["files"]["AGENTS.md"]).lower()

    checklist = "# Agent rules\n\n## Starter checklist\n\n1. Carry this checklist forward.\n"
    _save(client, project_id, "agents", 2, checklist)
    retained_checklist = _approve(client, project_id, 2, 3)
    assert retained_checklist.status_code == 422
    assert set(retained_checklist.json()["detail"]["files"]) == {"AGENTS.md"}
    assert (
        "checklist" in " ".join(retained_checklist.json()["detail"]["files"]["AGENTS.md"]).lower()
    )

    _save(client, project_id, "agents", 3, AGENTS_TEXT)
    # Simulate a packaged template update after project creation. Approval must
    # continue to validate against the immutable revision-one provenance.
    templates = dict(client.app.state.project_templates)
    updated_digest = hashlib.sha256(PROJECT_TEXT.encode("utf-8")).hexdigest()
    templates["project"] = ProjectTemplate(
        kind="project",
        source="PROJECT.md.example",
        content=PROJECT_TEXT,
        sha256=updated_digest,
    )
    client.app.state.project_templates = templates

    approved = _approve(client, project_id, 2, 4)
    assert approved.status_code == 200, approved.text
    assert approved.json()["project_revision_number"] == 2
    assert approved.json()["agents_revision_number"] == 4


def test_approval_rejects_missing_decisions_and_partial_starter_notes(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    _save(client, project_id, "project", 1, "# Any title\nAny body.\n")
    _save(client, project_id, "agents", 1, "# Any rules\nRun tests.\n")
    too_short = _approve(client, project_id, 2, 2)
    assert too_short.status_code == 422
    assert set(too_short.json()["detail"]["files"]) == {"PROJECT.md", "AGENTS.md"}
    assert "Purpose and users" in str(too_short.json()["detail"]["files"]["PROJECT.md"])
    assert "Setup and verification commands" in str(
        too_short.json()["detail"]["files"]["AGENTS.md"]
    )

    # A quoted skeleton is not a real section or decision in either document.
    project_skeleton = "# Any title\n\n```markdown\n" + valid_project() + "\n```\n"
    agents_skeleton = "# Any rules\n\n```markdown\n" + valid_agents() + "\n```\n"
    _save(client, project_id, "project", 2, project_skeleton)
    _save(client, project_id, "agents", 2, agents_skeleton)
    quoted = _approve(client, project_id, 3, 3)
    assert quoted.status_code == 422
    assert set(quoted.json()["detail"]["files"]) == {"PROJECT.md", "AGENTS.md"}

    project_with_notes = valid_project() + (
        "\n> Replace every `<PLACEHOLDER>`, remove inapplicable optional sections, and remove\n"
    )
    agents_with_checklist = valid_agents() + (
        "\n2. Complete the source-of-truth table and setup/check commands. Verify commands\n"
    )
    _save(client, project_id, "project", 3, project_with_notes)
    _save(client, project_id, "agents", 3, agents_with_checklist)
    partial = _approve(client, project_id, 4, 4)
    assert partial.status_code == 422
    assert "setup notes" in str(partial.json()["detail"]["files"]["PROJECT.md"])
    assert "checklist" in str(partial.json()["detail"]["files"]["AGENTS.md"])

    missing_decision = valid_project().replace(
        "- Problem: Planning drafts need a human owner.", "- Problem: "
    )
    _save(client, project_id, "project", 4, missing_decision)
    _save(client, project_id, "agents", 4, valid_agents())
    incomplete = _approve(client, project_id, 5, 5)
    assert incomplete.status_code == 422
    assert set(incomplete.json()["detail"]["files"]) == {"PROJECT.md"}
    assert "Problem" in str(incomplete.json()["detail"]["files"]["PROJECT.md"])


def test_indented_code_cannot_supply_required_headings_fields_or_decisions(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]

    project_fields = (
        "- Summary: Northstar research platform supports private planning.\n"
        "- Problem: Planning drafts need a human owner.\n"
        "- Primary users: The project owner.\n"
        "- Usage context: A private local planning browser.\n"
        "- Product outcomes: Reviewable private drafts."
    )
    project_fields_as_code = "\n".join(f"    {line}" for line in project_fields.splitlines())
    project_with_code_fields = PROJECT_TEXT.replace(project_fields, project_fields_as_code)
    assert project_with_code_fields != PROJECT_TEXT

    project_with_code_decision = PROJECT_TEXT.replace(
        "A stale write reports a conflict; only saved versions can be approved.",
        "    A stale write reports a conflict; only saved versions can be approved.",
    )
    project_with_code_heading = PROJECT_TEXT.replace(
        "## 4. Technology and environment — required\n\n"
        "Python 3.12 and PostgreSQL 17 store revisions.\n\n",
        "    ## 4. Technology and environment — required\n"
        "    Python 3.12 and PostgreSQL 17 store revisions.\n\n",
    )
    agents_with_code_decision = AGENTS_TEXT.replace(
        "Keep secrets out of Git; deny cross-project access.",
        "    Keep secrets out of Git; deny cross-project access.",
    )
    agents_with_code_heading = AGENTS_TEXT.replace(
        "## Security and hardening workflow\n\n"
        "Keep secrets out of Git; deny cross-project access.\n\n",
        "    ## Security and hardening workflow\n"
        "    Keep secrets out of Git; deny cross-project access.\n\n",
    )

    project_cases = (
        (project_with_code_fields, "PROJECT.md", "Summary"),
        (
            project_with_code_decision,
            "PROJECT.md",
            "Behavior and domain rules",
        ),
        (
            project_with_code_heading,
            "PROJECT.md",
            "Technology and environment",
        ),
    )
    agents_cases = (
        (
            agents_with_code_decision,
            "AGENTS.md",
            "Security and hardening workflow",
        ),
        (
            agents_with_code_heading,
            "AGENTS.md",
            "Security and hardening workflow",
        ),
    )

    for content, filename, expected_error in project_cases:
        project_revision = _save(client, project_id, "project", project_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, f"{filename}: {rejected.text}"
        errors = rejected.json()["detail"]["files"]
        assert set(errors) == {filename}
        assert expected_error in str(errors[filename])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    for content, filename, expected_error in agents_cases:
        agents_revision = _save(client, project_id, "agents", agents_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, f"{filename}: {rejected.text}"
        errors = rejected.json()["detail"]["files"]
        assert set(errors) == {filename}
        assert expected_error in str(errors[filename])

    # Ordinary prose and top-level Markdown list decisions remain valid evidence.
    agents_revision = _save(client, project_id, "agents", agents_revision, AGENTS_TEXT)[
        "revision_number"
    ]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200, approved.text


def test_comment_mask_keeps_line_alignment_and_ignores_comment_tokens_in_fences() -> None:
    content = (
        "Visible <!-- inline note --> text.\n"
        "<!-- a multiline note\n"
        "## Hidden heading\n"
        "end of note -->\n"
        "````html\n"
        "<!-- an unclosed comment in code\n"
        "````\n"
        "Visible after the fence.\n"
        "Inline `<!-- literal code -->` stays visible.\n"
    )

    masked = approval_module._mask_html_comments(content)

    assert masked.count("\n") == content.count("\n")
    assert len(masked.splitlines()) == len(content.splitlines())
    assert "Visible" in masked.splitlines()[0] and "text." in masked.splitlines()[0]
    assert all("Hidden heading" not in line for line in masked.splitlines())
    assert masked.splitlines()[5] == "<!-- an unclosed comment in code"
    assert masked.splitlines()[7] == "Visible after the fence."
    assert "<!-- literal code -->" in masked.splitlines()[8]


def test_only_visible_substantive_markdown_counts_for_both_approval_documents(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]

    project_cases = (
        (
            PROJECT_TEXT.replace(
                "## 4. Technology and environment — required",
                "<!--\n## 4. Technology and environment — required\n-->",
            ),
            "Technology and environment",
        ),
        (
            PROJECT_TEXT.replace(
                "## 4. Technology and environment — required",
                "```markdown\n## 4. Technology and environment — required\n```",
            ),
            "Technology and environment",
        ),
        (
            PROJECT_TEXT.replace(
                "- Problem: Planning drafts need a human owner.",
                "- Problem: <!-- this value is hidden\ncontinued hidden text -->",
            ),
            "Problem",
        ),
        (
            PROJECT_TEXT.replace(
                "- Problem: Planning drafts need a human owner.",
                "```markdown\n- Problem: Planning drafts need a human owner.\n```",
            ),
            "Problem",
        ),
        (
            PROJECT_TEXT.replace(
                "A stale write reports a conflict; only saved versions can be approved.",
                "<!-- A stale write reports a conflict; only saved versions can be approved. -->",
            ),
            "Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(
                "A stale write reports a conflict; only saved versions can be approved.",
                "```text\nA stale write reports a conflict; only saved versions can be approved.\n"
                "```",
            ),
            "Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(
                "A stale write reports a conflict; only saved versions can be approved.",
                "A versioned write creates immutable history.\n- Retry behavior: Pending",
            ),
            "Resolve undecided decisions under Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(
                "A stale write reports a conflict; only saved versions can be approved.",
                "Versioned writes preserve history.\n"
                "| Failure | Recovery |\n| --- | --- |\n| Timeout | **TBD** |",
            ),
            "Resolve undecided decisions under Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(
                "A stale write reports a conflict; only saved versions can be approved.",
                "| Failure | Recovery |\n| --- | --- |",
            ),
            "Add a project-specific decision under Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(
                "- Problem: Planning drafts need a human owner.",
                '- Problem: <review-panel data-state="Planning drafts need an owner.">'
                "</review-panel>",
            ),
            "Problem",
        ),
        (
            PROJECT_TEXT.replace(
                "- Problem: Planning drafts need a human owner.",
                "- Problem: <span hidden>Planning drafts need an owner.</span>",
            ),
            "Problem",
        ),
        (
            PROJECT_TEXT.replace(
                "- Problem: Planning drafts need a human owner.",
                "- Problem: <review-panel>Planning drafts need an owner.",
            ),
            "Problem",
        ),
        (
            PROJECT_TEXT.replace(
                "- Versioned document review.",
                '<section data-scope="Versioned document review"></section>',
            ),
            "Describe what is in scope",
        ),
        (
            PROJECT_TEXT.replace(
                "- Versioned document review.\n",
                "- Versioned document review.\n- Expansion: TODO\n",
            ),
            "Describe what is in scope",
        ),
    )

    for content, expected_error in project_cases:
        saved = _save(client, project_id, "project", project_revision, content)
        project_revision = saved["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        project_errors = rejected.json()["detail"]["files"]["PROJECT.md"]
        assert any(expected_error in error for error in project_errors), project_errors

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    agents_cases = (
        (
            AGENTS_TEXT.replace(
                "## Setup and verification commands",
                "<!--\n## Setup and verification commands\n-->",
            ),
            "Setup and verification commands",
        ),
        (
            AGENTS_TEXT.replace(
                "Run `python3 -m pytest` from api/ after installing locked dependencies.",
                "<!--\nRun `python3 -m pytest` from api/ after installing locked dependencies.\n"
                "-->",
            ),
            "Setup and verification commands",
        ),
        (
            AGENTS_TEXT.replace(
                "Run `python3 -m pytest` from api/ after installing locked dependencies.",
                "~~~markdown\n"
                "Run `python3 -m pytest` from api/ after installing locked dependencies.\n"
                "~~~",
            ),
            "Setup and verification commands",
        ),
        (
            AGENTS_TEXT.replace(
                "Keep secrets out of Git; deny cross-project access.",
                '<review-panel data-policy="deny cross-project access"></review-panel>',
            ),
            "Security and hardening workflow",
        ),
        (
            AGENTS_TEXT.replace(
                "Keep secrets out of Git; deny cross-project access.",
                '<span aria-hidden="true">Keep secrets out of Git.</span>',
            ),
            "Security and hardening workflow",
        ),
        (
            AGENTS_TEXT.replace(
                "Keep secrets out of Git; deny cross-project access.",
                "Keep credentials out of Git.\n- Incident owner: **TODO**",
            ),
            "Resolve undecided decisions under Security and hardening workflow",
        ),
        (
            AGENTS_TEXT.replace(
                "Keep secrets out of Git; deny cross-project access.",
                "Keep credentials out of Git.\n"
                "| Threat | Response |\n| --- | --- |\n| Leakage | `pending` |",
            ),
            "Resolve undecided decisions under Security and hardening workflow",
        ),
        (
            AGENTS_TEXT.replace(
                "Keep secrets out of Git; deny cross-project access.",
                "| Threat | Response |\n| --- | --- |",
            ),
            "Add a project-specific decision under Security and hardening workflow",
        ),
    )

    for content, expected_error in agents_cases:
        saved = _save(client, project_id, "agents", agents_revision, content)
        agents_revision = saved["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        agents_errors = rejected.json()["detail"]["files"]["AGENTS.md"]
        assert any(expected_error in error for error in agents_errors), agents_errors

    # Fence contents and raw HTML are not evidence; Markdown-native list/table
    # cells, inline code, formatting, and link labels outside HTML still count.
    positive_project = (
        PROJECT_TEXT.replace(
            "A stale write reports a conflict; only saved versions can be approved.",
            "```html\n<!-- comment markers inside this fence are literal code\n```\n"
            "- **Stale writes:** [create a conflict proposal](#history) and "
            "preserve `both revisions`.\n- Example: `printf value | sort` sorts inputs.\n"
            "- Requests remain visible while pending owner review.",
        )
        .replace(
            "Python 3.12 and PostgreSQL 17 store revisions.",
            "| Area | Decision |\n| :--- | ---: |\n"
            '| Storage | <review-panel data-store="postgres">Ignored.</review-panel> '
            "**PostgreSQL stores immutable revisions.** |",
        )
        .replace(
            "- Problem: Planning drafts need a human owner.",
            "- Problem: **Planning drafts need a human owner**.",
        )
    )
    positive_agents = (
        AGENTS_TEXT.replace(
            "Run `python3 -m pytest` from api/ after installing locked dependencies.",
            "~~~html\n<!-- comment markers inside this fence are literal code\n~~~\n"
            "1. Run [the API checks](#setup) with `python3 -m pytest`.",
        )
        .replace(
            "Keep secrets out of Git; deny cross-project access.",
            "| Security | Decision |\n| --- | --- |\n"
            "| Credentials | <review-panel>Ignored.</review-panel> "
            "Keep secrets outside Git and deny cross-project access. |",
        )
        .replace(
            "The owner controls task state and integration.",
            "- The owner controls task state and integration.",
        )
    )
    project_revision = _save(client, project_id, "project", project_revision, positive_project)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, positive_agents)[
        "revision_number"
    ]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200, approved.text


def test_raw_html_is_preserved_but_only_markdown_can_prove_pair_decisions(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    assert _approve(client, project_id, project_revision, agents_revision).status_code == 200

    problem = "- Problem: Planning drafts need a human owner."
    behavior = "A stale write reports a conflict; only saved versions can be approved."
    project_cases = (
        (PROJECT_TEXT.replace(problem, "- Problem: <strong>Needs an owner.</strong>"), "Problem"),
        (
            PROJECT_TEXT.replace(problem, "- Problem: <review-panel>Owner needed.</review-panel>"),
            "Problem",
        ),
        (
            PROJECT_TEXT.replace(problem, '- Problem: <div style="opacity:0">Owner needed.</div>'),
            "Problem",
        ),
        (PROJECT_TEXT.replace(problem, '- Problem: <img alt="Needs an owner.">'), "Problem"),
        (PROJECT_TEXT.replace(problem, "- Problem: <!-- Needs an owner. -->"), "Problem"),
        (PROJECT_TEXT.replace(problem, "- Problem: <span>Needs an owner."), "Problem"),
        (PROJECT_TEXT.replace(problem, "- Problem: <123>Needs an owner.</123>"), "Problem"),
        (PROJECT_TEXT.replace(problem, "- Problem: ![Needs an owner][image]"), "Problem"),
        (PROJECT_TEXT.replace(problem, "[problem]: https://example.invalid/owner"), "Problem"),
        (
            PROJECT_TEXT.replace(behavior, f"<section>{behavior}</section>"),
            "Behavior and domain rules",
        ),
    )
    for content, expected in project_cases:
        saved = _save(client, project_id, "project", project_revision, content)
        assert saved["content"] == content  # HTML remains in the immutable draft bytes.
        project_revision = saved["revision_number"]
        status_response = client.get(f"/api/projects/{project_id}/document-pair-approval")
        assert status_response.status_code == 200
        assert status_response.json()["approved"] is False
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert expected in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    security = "Keep secrets out of Git; deny cross-project access."
    agents_cases = (
        (AGENTS_TEXT.replace(setup, f"<em>{setup}</em>"), "Setup and verification commands"),
        (
            AGENTS_TEXT.replace(setup, f"<review-panel>{setup}</review-panel>"),
            "Setup and verification commands",
        ),
        (
            AGENTS_TEXT.replace(setup, f'<span class="plain">{setup}</span>'),
            "Setup and verification commands",
        ),
        (AGENTS_TEXT.replace(setup, f"<!-- {setup} -->"), "Setup and verification commands"),
        (AGENTS_TEXT.replace(setup, f"```text\n{setup}\n```"), "Setup and verification commands"),
        (
            AGENTS_TEXT.replace(setup, "[check]: https://example.invalid/command"),
            "Setup and verification commands",
        ),
        (
            AGENTS_TEXT.replace(setup, "<https://example.invalid/command>"),
            "Setup and verification commands",
        ),
        (
            AGENTS_TEXT.replace(security, f"<section>{security}"),
            "Security and hardening workflow",
        ),
        (
            AGENTS_TEXT.replace(security, f"<123>{security}</123>"),
            "Security and hardening workflow",
        ),
    )
    for content, expected in agents_cases:
        saved = _save(client, project_id, "agents", agents_revision, content)
        assert saved["content"] == content
        agents_revision = saved["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert expected in str(rejected.json()["detail"]["files"]["AGENTS.md"])

    # HTML may remain adjacent to evidence, but only the Markdown-native label,
    # inline-code value, emphasis, prose/list item and data cell prove decisions.
    project_good = PROJECT_TEXT.replace(
        problem,
        "- Problem: <review-panel>Ignored.</review-panel> "
        "[Drafts need a human owner][reason] and `revision review`.",
    ).replace(
        behavior,
        "<span>Ignored.</span> - **Preserve immutable revisions** after stale writes.",
    )
    agents_good = AGENTS_TEXT.replace(
        setup,
        "### API checks\n- <strong>Ignored.</strong> Run [locked checks](#api) with `pytest`.",
    ).replace(
        security,
        "<review-panel>Ignored.</review-panel>\n"
        "| Rule | Decision |\n| --- | --- |\n| Access | **Deny cross-project reads.** |",
    )
    project_revision = _save(client, project_id, "project", project_revision, project_good)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, agents_good)[
        "revision_number"
    ]
    assert _approve(client, project_id, project_revision, agents_revision).status_code == 200


def test_nonvoid_self_closing_html_never_proves_pair_or_current_approval(
    client: TestClient, engine, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    problem = "- Problem: Planning drafts need a human owner."
    behavior = "A stale write reports a conflict; only saved versions can be approved."
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    security = "Keep secrets out of Git; deny cross-project access."
    self_closing_problem = "- Problem: <div/>Planning drafts need a human owner."
    project_bad = (
        (PROJECT_TEXT.replace(problem, self_closing_problem), "Problem"),
        (
            PROJECT_TEXT.replace(behavior, "<review-panel />Save immutable revisions."),
            "Behavior and domain rules",
        ),
        (PROJECT_TEXT.replace(problem, '- Problem: <img alt="Needs an owner." />'), "Problem"),
    )
    for content, expected in project_bad:
        saved = _save(client, project_id, "project", project_revision, content)
        assert saved["content"] == content
        project_revision = saved["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert expected in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    agents_bad = (
        (
            AGENTS_TEXT.replace(setup, "<span/>Run locked API checks."),
            "Setup and verification commands",
        ),
        (
            AGENTS_TEXT.replace(security, '<div data-note="x/>y" />Deny cross-project reads.'),
            "Security and hardening workflow",
        ),
    )
    for content, expected in agents_bad:
        saved = _save(client, project_id, "agents", agents_revision, content)
        assert saved["content"] == content
        agents_revision = saved["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert expected in str(rejected.json()["detail"]["files"]["AGENTS.md"])

    project_good = PROJECT_TEXT.replace(
        problem,
        '- Problem: <img alt="Not evidence" /><br/><div>Also not evidence.</div> '
        "**Planning drafts need a human owner.**",
    )
    agents_good = AGENTS_TEXT.replace(
        setup,
        "<div>Not evidence.</div><br /> Run locked API checks from api/.",
    )
    project_revision = _save(client, project_id, "project", project_revision, project_good)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, agents_good)[
        "revision_number"
    ]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200, approved.text

    with Session(engine) as db:
        revision = db.get(
            ProjectDocumentRevision, uuid.UUID(approved.json()["project_revision_id"])
        )
        assert revision is not None
        revision.content = PROJECT_TEXT.replace(problem, self_closing_problem)
        revision.content_sha256 = hashlib.sha256(revision.content.encode()).hexdigest()
        db.commit()
    path = f"/api/projects/{project_id}/document-pair-approval"
    status_response = client.get(path)
    assert status_response.status_code == 200
    assert status_response.json()["approved"] is False
    assert status_response.json()["latest_approval"]["id"] == approved.json()["id"]
    repeated = _approve(client, project_id, project_revision, agents_revision)
    assert repeated.status_code == 422
    assert set(repeated.json()["detail"]["files"]) == {"PROJECT.md"}


def test_cdata_and_ambiguous_declarations_never_prove_decisions_or_current_approval(
    client: TestClient, engine, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    problem = "- Problem: Planning drafts need a human owner."
    behavior = "A stale write reports a conflict; only saved versions can be approved."
    security = "Keep secrets out of Git; deny cross-project access."
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    project_bad = (
        (PROJECT_TEXT.replace(problem, "- Problem: <![CDATA[>Needs a human owner.]]>"), "Problem"),
        (
            PROJECT_TEXT.replace(behavior, f"<![CDATA[>\n{behavior}\n]]>"),
            "Behavior and domain rules",
        ),
        (PROJECT_TEXT.replace(problem, "- Problem: <![CDATA[>Needs an owner."), "Problem"),
        (
            PROJECT_TEXT.replace(problem, "- Problem: <!DOCTYPE proof >Needs an owner."),
            "Problem",
        ),
    )
    for content, expected in project_bad:
        saved = _save(client, project_id, "project", project_revision, content)
        assert saved["content"] == content
        project_revision = saved["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert expected in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    agents_bad = (
        (AGENTS_TEXT.replace(security, f"<![CDATA[>\n{security}\n]]>"), "Security"),
        (
            AGENTS_TEXT.replace(setup, "- Setup command: <![CDATA[>Run locked API checks.]]>"),
            "Setup and verification commands",
        ),
        (AGENTS_TEXT.replace(security, f"<![CDATA[>\n{security}"), "Security"),
        (AGENTS_TEXT.replace(security, f"<!DOCTYPE policy >\n{security}"), "Security"),
    )
    for content, expected in agents_bad:
        saved = _save(client, project_id, "agents", agents_revision, content)
        assert saved["content"] == content
        agents_revision = saved["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert expected in str(rejected.json()["detail"]["files"]["AGENTS.md"])

    # A closed CDATA block has a known boundary; Markdown outside it survives.
    project_good = PROJECT_TEXT.replace(
        problem,
        "- Problem: <![CDATA[>Hidden claim <!-- not a Markdown comment >]]> "
        "**Planning drafts need an owner.**",
    )
    agents_good = AGENTS_TEXT.replace(
        security,
        "<![CDATA[>\n<!-- not a Markdown comment >\n]]>\n"
        "- Keep secrets out of Git; deny cross-project access.",
    )
    project_revision = _save(client, project_id, "project", project_revision, project_good)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, agents_good)[
        "revision_number"
    ]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200, approved.text
    path = f"/api/projects/{project_id}/document-pair-approval"
    assert client.get(path).json()["approved"] is True

    # Model a previously approved row created before this rule was enforced.
    with Session(engine) as db:
        revision = db.get(ProjectDocumentRevision, uuid.UUID(approved.json()["agents_revision_id"]))
        assert revision is not None
        revision.content = AGENTS_TEXT.replace(security, f"<![CDATA[>\n{security}\n]]>")
        revision.content_sha256 = hashlib.sha256(revision.content.encode()).hexdigest()
        db.commit()
    status_response = client.get(path)
    assert status_response.status_code == 200
    assert status_response.json()["approved"] is False
    assert status_response.json()["latest_approval"]["id"] == approved.json()["id"]
    rejected_repeat = _approve(client, project_id, project_revision, agents_revision)
    assert rejected_repeat.status_code == 422
    assert set(rejected_repeat.json()["detail"]["files"]) == {"AGENTS.md"}


def test_approval_uses_block_visibility_and_heading_hierarchy_for_both_files(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]

    problem = "- Problem: Planning drafts need a human owner."
    behavior = "A stale write reports a conflict; only saved versions can be approved."
    scope = "### In scope\n- Versioned document review."
    technology = "## 4. Technology and environment — required"
    project_cases = (
        (
            PROJECT_TEXT.replace(problem, "- Problem: <div hidden>\nOwner needed.\n</div>"),
            "Problem",
        ),
        (PROJECT_TEXT.replace(problem, "- Problem: <div\n hidden>Owner needed.</div>"), "Problem"),
        (PROJECT_TEXT.replace(problem, "- Problem: <!-- owner -->"), "Problem"),
        (
            PROJECT_TEXT.replace(behavior, f"<div hidden>\n{behavior}\n</div>"),
            "Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(behavior, f'<div style="display: none">{behavior}</div>'),
            "Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(technology, f"<section hidden>\n{technology}\n</section>"),
            "Technology and environment",
        ),
        (
            PROJECT_TEXT.replace(behavior, f"> ```markdown\n> {behavior}\n> ```"),
            "Behavior and domain rules",
        ),
        (PROJECT_TEXT.replace(problem, f"> ```markdown\n> {problem}\n> ```"), "Problem"),
        (
            PROJECT_TEXT.replace(technology, f"> ```markdown\n> {technology}\n> ```"),
            "Technology and environment",
        ),
        (
            PROJECT_TEXT.replace(behavior, "- Save drafts.\n    - Retry policy: TBD"),
            "Resolve undecided decisions under Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(behavior, "- Example:\n      Decision: approved"),
            "Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(scope, "### In scope\n- Review drafts.\n    - Expansion: TODO"),
            "Describe what is in scope",
        ),
        (
            PROJECT_TEXT.replace(
                scope, "### Out of scope\n- Versioned review.\n### In scope\n- TBD"
            ),
            "Describe what is in scope",
        ),
        (
            PROJECT_TEXT.replace(scope, "- Versioned document review.").replace(
                technology, f"### In scope\n- Review drafts.\n{technology}"
            ),
            "Describe what is in scope",
        ),
    )
    for content, expected in project_cases:
        project_revision = _save(client, project_id, "project", project_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert expected in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    security = "Keep secrets out of Git; deny cross-project access."
    setup_heading = "## Setup and verification commands"
    setup_name = "Setup and verification commands"
    agents_cases = (
        (AGENTS_TEXT.replace(setup, f"<div hidden>\n{setup}\n</div>"), setup_name),
        (
            AGENTS_TEXT.replace(
                setup_heading, f"<section aria-hidden='true'>\n{setup_heading}\n</section>"
            ),
            setup_name,
        ),
        (AGENTS_TEXT.replace(setup, f"> ```markdown\n> {setup}\n> ```"), setup_name),
        (
            AGENTS_TEXT.replace(setup, f"- > ```markdown\n  > {setup}\n  > ```"),
            setup_name,
        ),
        (
            AGENTS_TEXT.replace(security, "- Block access.\n    - Incident owner: TBD"),
            "Resolve undecided decisions under Security",
        ),
        (
            AGENTS_TEXT.replace(setup, "- Example:\n      - Run locked checks."),
            setup_name,
        ),
        (
            AGENTS_TEXT.replace(
                security,
                "- Block access.\n    | Threat | Response |\n    | --- | --- |\n    | Leak | TBD |",
            ),
            "Resolve undecided decisions under Security",
        ),
        (
            AGENTS_TEXT.replace(
                security,
                "- Block access.\n    <!--\n    - Incident owner: TBD\n    -->",
            ),
            None,
        ),
    )
    for content, expected in agents_cases:
        agents_revision = _save(client, project_id, "agents", agents_revision, content)[
            "revision_number"
        ]
        result = _approve(client, project_id, project_revision, agents_revision)
        if expected is None:
            assert result.status_code == 200, result.text
        else:
            assert result.status_code == 422, result.text
            assert expected in str(result.json()["detail"]["files"]["AGENTS.md"])

    visible_project = (
        PROJECT_TEXT.replace(
            problem, "- Problem: <div hidden>Unseen</div> **Planning drafts need an owner.**"
        )
        .replace(
            "- Primary users: The project owner.",
            '- Primary users: <span data-note="hidden details">Ignored.</span> The project owner.',
        )
        .replace(
            behavior,
            "> ```markdown\n> This is an example, not a decision.\n> ```\n"
            "### Conflict handling\n- Save immutable revisions.\n"
            "    - Present conflicts to the owner.",
        )
    )
    visible_agents = AGENTS_TEXT.replace(
        setup,
        "> ```markdown\n> Fake setup only.\n"
        "### API checks\n- Run the locked checks.\n    - Command: `python3 -m pytest`.",
    ).replace(
        security,
        '<section data-style="display:none">\n- Ignored.\n</section>\n'
        "- Keep secrets outside Git and deny cross-project access.",
    )
    project_revision = _save(client, project_id, "project", project_revision, visible_project)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, visible_agents)[
        "revision_number"
    ]
    assert _approve(client, project_id, project_revision, agents_revision).status_code == 200


def test_required_child_headings_with_undecided_values_block_both_documents(
    client: TestClient, engine, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    behavior = "A stale write reports a conflict; only saved versions can be approved."
    scope = "### In scope\n- Versioned document review."
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    security = "Keep secrets out of Git; deny cross-project access."
    project_bad = (
        (PROJECT_TEXT.replace(behavior, behavior + "\n### Conflict resolution: TODO"), "Behavior"),
        (PROJECT_TEXT.replace(scope, scope + "\n#### Expansion: TBD"), "In scope"),
        (
            PROJECT_TEXT.replace(
                behavior,
                behavior + "\n### Conflict handling\n- Save revisions.\n#### Owner: pending input",
            ),
            "Behavior",
        ),
        (
            PROJECT_TEXT.replace(behavior, "### Conflict resolution: Save immutable versions."),
            "Behavior",
        ),
        (PROJECT_TEXT.replace(behavior, behavior + "\n### Review owner: ???"), "Behavior"),
    )
    for content, section in project_bad:
        project_revision = _save(client, project_id, "project", project_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert section.lower() in str(rejected.json()["detail"]["files"]["PROJECT.md"]).lower()

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    agents_bad = (
        (AGENTS_TEXT.replace(security, security + "\n### Secret rotation: TODO"), "Security"),
        (AGENTS_TEXT.replace(setup, setup + "\n### API checks: Pending owner input"), "Setup"),
        (
            AGENTS_TEXT.replace(
                security,
                security + "\n### Security checks\n- Deny cross-project reads.\n#### Owner: TBD",
            ),
            "Security",
        ),
        (AGENTS_TEXT.replace(setup, "### API checks: Run pytest now."), "Setup"),
        (AGENTS_TEXT.replace(security, security + "\n### Review owner: ???"), "Security"),
    )
    for content, section in agents_bad:
        agents_revision = _save(client, project_id, "agents", agents_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert section in str(rejected.json()["detail"]["files"]["AGENTS.md"])

    project_good = PROJECT_TEXT.replace(
        behavior,
        behavior + "\n### Conflict resolution: Save immutable versions.\n"
        "- Show stale-write conflicts to the owner.\n"
        "### Optional export review after the pilot\n"
        "- Keep current revisions immutable.",
    )
    agents_good = AGENTS_TEXT.replace(
        security,
        security + "\n### Secret rotation: Review credentials quarterly.\n"
        "- Keep secrets outside Git.\n"
        "### Optional browser-check review after the pilot\n"
        "- Run locked API checks now.",
    )
    project_revision = _save(client, project_id, "project", project_revision, project_good)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, agents_good)[
        "revision_number"
    ]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200, approved.text

    with Session(engine) as db:
        agents_saved = db.get(
            ProjectDocumentRevision, uuid.UUID(approved.json()["agents_revision_id"])
        )
        assert agents_saved is not None
        agents_saved.content = AGENTS_TEXT.replace(
            security, security + "\n### Secret rotation: TODO"
        )
        agents_saved.content_sha256 = hashlib.sha256(agents_saved.content.encode()).hexdigest()
        db.commit()
    path = f"/api/projects/{project_id}/document-pair-approval"
    status_response = client.get(path)
    assert status_response.status_code == 200
    assert status_response.json()["approved"] is False
    assert status_response.json()["latest_approval"]["id"] == approved.json()["id"]
    repeated = _approve(client, project_id, project_revision, agents_revision)
    assert repeated.status_code == 422
    assert set(repeated.json()["detail"]["files"]) == {"AGENTS.md"}

    with Session(engine) as db:
        project_saved = db.get(
            ProjectDocumentRevision, uuid.UUID(approved.json()["project_revision_id"])
        )
        assert project_saved is not None
        project_saved.content = PROJECT_TEXT.replace(
            behavior, behavior + "\n### Conflict resolution: TODO"
        )
        project_saved.content_sha256 = hashlib.sha256(project_saved.content.encode()).hexdigest()
        db.commit()
    assert client.get(path).json()["approved"] is False
    rejected_both = _approve(client, project_id, project_revision, agents_revision)
    assert rejected_both.status_code == 422
    assert set(rejected_both.json()["detail"]["files"]) == {"PROJECT.md", "AGENTS.md"}


def test_standalone_undecided_decisions_are_not_excused_by_other_prose(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]

    project_cases = (
        (
            PROJECT_TEXT.replace(
                "A stale write reports a conflict; only saved versions can be approved.",
                "Save immutable revisions.\n- Recovery: Compare both versions.\n- TBD",
            ),
            "Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(
                "- Versioned document review.",
                "- Versioned document review.\n    - **TODO**",
            ),
            "Describe what is in scope",
        ),
        (
            PROJECT_TEXT.replace(
                "Python 3.12 and PostgreSQL 17 store revisions.",
                "Python 3.12 and PostgreSQL 17 store revisions.\nPending owner decision",
            ),
            "Technology and environment",
        ),
    )
    for content, section in project_cases:
        project_revision = _save(client, project_id, "project", project_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert section in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    agents_cases = (
        (
            AGENTS_TEXT.replace(
                "Run `python3 -m pytest` from api/ after installing locked dependencies.",
                "### API checks\nRun `python3 -m pytest` from api/.\n- TBD",
            ),
            "Setup and verification commands",
        ),
        (
            AGENTS_TEXT.replace(
                "Keep secrets out of Git; deny cross-project access.",
                "- Deny cross-project access.\n    - `Unknown`",
            ),
            "Security and hardening workflow",
        ),
    )
    for content, section in agents_cases:
        agents_revision = _save(client, project_id, "agents", agents_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert "Resolve undecided decisions under" in str(
            rejected.json()["detail"]["files"]["AGENTS.md"]
        )
        assert section in str(rejected.json()["detail"]["files"]["AGENTS.md"])

    # The same marker in comments or indented/fenced examples is not a live
    # decision, while genuine visible prose still satisfies these sections.
    visible_project = PROJECT_TEXT.replace(
        "A stale write reports a conflict; only saved versions can be approved.",
        "Save immutable revisions.\n    - TBD\n<!-- TODO -->",
    )
    visible_agents = AGENTS_TEXT.replace(
        "Keep secrets out of Git; deny cross-project access.",
        "Keep secrets out of Git; deny cross-project access.\n```markdown\n- TBD\n```",
    )
    project_revision = _save(client, project_id, "project", project_revision, visible_project)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, visible_agents)[
        "revision_number"
    ]
    assert _approve(client, project_id, project_revision, agents_revision).status_code == 200


def test_deferred_decision_qualifiers_reject_without_blocking_actual_plans(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    problem = "- Problem: Planning drafts need a human owner."
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    deferred = (
        "Pending owner input",
        "Pending team review after the trial ends",
        "To be decided by owner",
        "To be decided by owner after the trial ends",
        "To be determined by the product team.",
        "To be determined by the product team after both pilot projects finish",
        "To be specified with stakeholders",
        "Not yet decided by the engineering team",
        "Not yet decided by the engineering team after the release review finishes",
        "Decide later with project owner",
        "To be decided by owner after the trial ends. Final decision: TBD",
        "To be decided by owner after the trial ends. Final decision: later",
        "To be decided by owner after the trial ends. Final decision: pending owner input",
        "To be decided by owner after the trial ends. "
        "Final decision: Planning drafts lack an accountable human owner.",
    )
    for value in deferred:
        project_revision = _save(
            client,
            project_id,
            "project",
            project_revision,
            PROJECT_TEXT.replace(problem, f"- Problem: **{value}**"),
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, (value, rejected.text)
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert "Problem" in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    agent_cases = (
        "- Setup command: Pending owner input",
        "- Setup command: Pending technical review after the pilot concludes",
        "| Task | Command |\n| --- | --- |\n| API | Pending team input |",
        "- Setup command: To be decided by owner",
        "- Setup command: To be decided by owner after the trial ends",
        "| Task | Command |\n| --- | --- |\n| API | To be confirmed by QA team |",
        "| Task | Command |\n| --- | --- |\n"
        "| API | To be confirmed by the quality team after launch review |",
        f"{setup}\n- To be determined with stakeholders",
        f"{setup}\n- To be determined with stakeholders after the pilot concludes",
        "- Setup command: To be decided by owner after the trial ends. "
        "Final decision: pending owner input",
        "- Setup command: To be decided by owner after the trial ends. "
        "Final decision: Run the locked API checks from api/.",
    )
    for value in agent_cases:
        agents_revision = _save(
            client, project_id, "agents", agents_revision, AGENTS_TEXT.replace(setup, value)
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, (value, rejected.text)
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert "Setup and verification commands" in str(
            rejected.json()["detail"]["files"]["AGENTS.md"]
        )

    # Plans for optional future choices without an unresolved marker still
    # accompany concrete decisions about the current project.
    actual_plan = PROJECT_TEXT.replace(
        problem,
        "- Problem: Drafts need an owner now; optional export choices will be "
        "evaluated after the pilot while the owner reviews current revisions.",
    )
    actual_checks = AGENTS_TEXT.replace(
        setup,
        "Run the locked API checks now; optional browser checks will be evaluated after the pilot.",
    )
    project_revision = _save(client, project_id, "project", project_revision, actual_plan)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, actual_checks)[
        "revision_number"
    ]
    assert _approve(client, project_id, project_revision, agents_revision).status_code == 200

    # A human replaces the pending value rather than appending an alleged
    # resolution to the same value. Concrete answers remain eligible.
    resolved_problem = PROJECT_TEXT.replace(
        problem,
        "- Problem: Planning drafts lack an accountable human owner.",
    )
    resolved_checks = AGENTS_TEXT.replace(
        setup,
        "Run the locked API checks from api/.",
    )
    project_revision = _save(client, project_id, "project", project_revision, resolved_problem)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, resolved_checks)[
        "revision_number"
    ]
    assert _approve(client, project_id, project_revision, agents_revision).status_code == 200

    # Short concrete answers are allowed without an arbitrary length quota.
    short_command = AGENTS_TEXT.replace(setup, "pytest")
    agents_revision = _save(client, project_id, "agents", agents_revision, short_command)[
        "revision_number"
    ]
    assert _approve(client, project_id, project_revision, agents_revision).status_code == 200


def test_unresolved_clauses_after_concrete_required_values_block_approval(
    client: TestClient, engine, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200
    problem = "- Problem: Planning drafts need a human owner."
    security = "Keep secrets out of Git; deny cross-project access."
    project_cases = (
        PROJECT_TEXT.replace(problem, problem + " TODO"),
        PROJECT_TEXT.replace(problem, problem + " TBD after owner review"),
        PROJECT_TEXT.replace(problem, problem + " Pending owner input"),
        PROJECT_TEXT.replace(problem, problem + " TODO; Final decision: keep drafts private."),
        PROJECT_TEXT.replace(problem, problem + "; TODO: identify the actual owner."),
        PROJECT_TEXT.replace(problem, problem.rstrip(".") + " TODO: identify the actual owner."),
        PROJECT_TEXT.replace(problem, problem + " — TBD after owner review."),
        PROJECT_TEXT.replace(problem, problem.rstrip(".") + " - TBD after owner review."),
        PROJECT_TEXT.replace(problem, problem.rstrip(".") + " _ TBD after owner review."),
        PROJECT_TEXT.replace(problem, problem + " / Pending owner input."),
    )
    for content in project_cases:
        project_revision = _save(client, project_id, "project", project_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert "Problem" in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    agents_cases = (
        AGENTS_TEXT.replace(setup, setup + " TODO"),
        AGENTS_TEXT.replace(setup, setup + "; TODO: verify the command."),
        AGENTS_TEXT.replace(setup, setup.rstrip(".") + " TODO: verify the command."),
        AGENTS_TEXT.replace(security, security + " Pending team review"),
        AGENTS_TEXT.replace(security, security + " / Pending team review."),
        AGENTS_TEXT.replace(setup, setup.rstrip(".") + " - TBD after owner review."),
        AGENTS_TEXT.replace(setup, setup.rstrip(".") + " _ TBD after owner review."),
        AGENTS_TEXT.replace(
            security,
            "| Rule | Decision |\n| --- | --- |\n| Access | Deny cross-project reads. TODO |",
        ),
        AGENTS_TEXT.replace(
            security,
            "| Rule | Decision |\n| --- | --- |\n"
            "| Access | Deny cross-project reads; TBD: identify reviewer. |",
        ),
    )
    for content in agents_cases:
        agents_revision = _save(client, project_id, "agents", agents_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert "Resolve undecided decisions" in str(rejected.json()["detail"]["files"]["AGENTS.md"])

    positive_project = PROJECT_TEXT.replace(
        problem,
        "- Problem: Planning drafts need a human owner - optional exports will be "
        "reviewed after the pilot, but the current owner reviews revisions.",
    )
    positive_agents = AGENTS_TEXT.replace(
        setup,
        "Run locked API tests now - optional browser checks will be reviewed after the pilot.",
    )
    project_revision = _save(client, project_id, "project", project_revision, positive_project)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, positive_agents)[
        "revision_number"
    ]
    latest_approval = _approve(client, project_id, project_revision, agents_revision)
    assert latest_approval.status_code == 200, latest_approval.text

    # An old approval row cannot grandfather a marked answer into current status.
    with Session(engine) as db:
        revision = db.get(
            ProjectDocumentRevision, uuid.UUID(latest_approval.json()["project_revision_id"])
        )
        assert revision is not None
        revision.content = PROJECT_TEXT.replace(problem, "- Problem: Owner choice TBD after review")
        revision.content_sha256 = hashlib.sha256(revision.content.encode()).hexdigest()
        db.commit()
    path = f"/api/projects/{project_id}/document-pair-approval"
    current = client.get(path)
    assert current.status_code == 200
    assert current.json()["approved"] is False
    assert current.json()["latest_approval"]["id"] == latest_approval.json()["id"]
    repeated = _approve(client, project_id, project_revision, agents_revision)
    assert repeated.status_code == 422
    assert set(repeated.json()["detail"]["files"]) == {"PROJECT.md"}

    with Session(engine) as db:
        agents_saved = db.get(
            ProjectDocumentRevision, uuid.UUID(latest_approval.json()["agents_revision_id"])
        )
        assert agents_saved is not None
        agents_saved.content = AGENTS_TEXT.replace(setup, "Setup command TBA after owner review")
        agents_saved.content_sha256 = hashlib.sha256(agents_saved.content.encode()).hexdigest()
        db.commit()
    assert client.get(path).json()["approved"] is False
    rejected_both = _approve(client, project_id, project_revision, agents_revision)
    assert rejected_both.status_code == 422
    assert set(rejected_both.json()["detail"]["files"]) == {"PROJECT.md", "AGENTS.md"}


def test_explicit_markers_anywhere_in_required_values_reject_both_documents(
    client: TestClient, engine, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    problem = "- Problem: Planning drafts need a human owner."
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    for value in (
        "Owner choice TBD after owner review",
        "Owner choice TBC after owner review",
        "Owner choice TBA after owner review",
        "Owner choice TODO after owner review",
        "Planning drafts need an owner; optional exports remain TBD after the pilot.",
    ):
        project_revision = _save(
            client,
            project_id,
            "project",
            project_revision,
            PROJECT_TEXT.replace(problem, f"- Problem: {value}"),
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, (value, rejected.text)
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert "Problem" in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    for value in (
        "Setup command TBD after owner review",
        "Setup command TBC after owner review",
        "Setup command TBA after owner review",
        "Setup command TODO after owner review",
        "Run locked tests now; optional browser checks may be TODO after the pilot.",
    ):
        agents_revision = _save(
            client, project_id, "agents", agents_revision, AGENTS_TEXT.replace(setup, value)
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, (value, rejected.text)
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert "Setup and verification commands" in str(
            rejected.json()["detail"]["files"]["AGENTS.md"]
        )

    # Optional planning is allowed when it does not keep an explicit marker in
    # the evidence offered for today's required decision.
    project_good = PROJECT_TEXT.replace(
        problem,
        "- Problem: Drafts need an owner now; optional exports will be evaluated after the pilot.",
    )
    agents_good = AGENTS_TEXT.replace(
        setup, "Run locked API tests now; optional browser checks will be reviewed after the pilot."
    )
    project_revision = _save(client, project_id, "project", project_revision, project_good)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, agents_good)[
        "revision_number"
    ]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200, approved.text

    with Session(engine) as db:
        project_saved = db.get(
            ProjectDocumentRevision, uuid.UUID(approved.json()["project_revision_id"])
        )
        assert project_saved is not None
        project_saved.content = PROJECT_TEXT.replace(
            problem, "- Problem: Owner choice TBD after review"
        )
        project_saved.content_sha256 = hashlib.sha256(project_saved.content.encode()).hexdigest()
        db.commit()
    path = f"/api/projects/{project_id}/document-pair-approval"
    status_response = client.get(path)
    assert status_response.status_code == 200
    assert status_response.json()["approved"] is False
    assert status_response.json()["latest_approval"]["id"] == approved.json()["id"]
    repeated = _approve(client, project_id, project_revision, agents_revision)
    assert repeated.status_code == 422
    assert set(repeated.json()["detail"]["files"]) == {"PROJECT.md"}

    with Session(engine) as db:
        agents_saved = db.get(
            ProjectDocumentRevision, uuid.UUID(approved.json()["agents_revision_id"])
        )
        assert agents_saved is not None
        agents_saved.content = AGENTS_TEXT.replace(setup, "Setup command TBA after owner review")
        agents_saved.content_sha256 = hashlib.sha256(agents_saved.content.encode()).hexdigest()
        db.commit()
    assert client.get(path).json()["approved"] is False
    repeated_both = _approve(client, project_id, project_revision, agents_revision)
    assert repeated_both.status_code == 422
    assert set(repeated_both.json()["detail"]["files"]) == {"PROJECT.md", "AGENTS.md"}


def test_styled_and_classed_html_never_supplies_approval_evidence(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    problem = "- Problem: Planning drafts need a human owner."
    project_cases = (
        '- Problem: <span style="display:/* note */none">Hidden owner.</span>',
        '- Problem: <span style="/* note */ visibility: hidden">Hidden owner.</span>',
        '- Problem: <span style="display:no/* note */ne">Hidden owner.</span>',
        '- Problem: <span style="display:&#47;* note *&#47;none">Hidden owner.</span>',
        '- Problem: <span style="display:/* unclosed">Hidden owner.</span>',
        '- Problem: <span style="opacity:0">Hidden owner.</span>',
        '- Problem: <span style="font-size:0">Hidden owner.</span>',
        '- Problem: <span style="color:green">Cannot verify visibility.</span>',
        '- Problem: <span class="screen-only">Cannot verify visibility.</span>',
        '- Problem: <span id="hidden">Cannot verify visibility.</span>',
        "- Problem: <span inert>Cannot verify visibility.</span>",
    )
    for replacement in project_cases:
        project_revision = _save(
            client,
            project_id,
            "project",
            project_revision,
            PROJECT_TEXT.replace(problem, replacement),
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert "Problem" in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    behavior = "A stale write reports a conflict; only saved versions can be approved."
    technology = "## 4. Technology and environment — required"
    project_sections = (
        (
            PROJECT_TEXT.replace(
                behavior, f'<div class="screen-only"><strong>{behavior}</strong></div>'
            ),
            "Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(technology, f'<div style="font-size:0">\n{technology}\n</div>'),
            "Technology and environment",
        ),
    )
    for content, section in project_sections:
        project_revision = _save(client, project_id, "project", project_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert section in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    security = "Keep secrets out of Git; deny cross-project access."
    for style in (
        "display:/* note */none",
        "visibility:/* note */hidden!important",
        "color: green; /* note */ display: none",
        "display: /* note */ none !important",
        "opacity:0",
        "font-size:0",
        "color:green",
    ):
        content = AGENTS_TEXT.replace(security, f'<div style="{style}">{security}</div>')
        agents_revision = _save(client, project_id, "agents", agents_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert "Security and hardening workflow" in str(
            rejected.json()["detail"]["files"]["AGENTS.md"]
        )
    for tag in (
        '<div class="visually-hidden">',
        '<div id="hidden">',
        '<div aria-hidden="false">',
    ):
        content = AGENTS_TEXT.replace(security, f"{tag}{security}</div>")
        agents_revision = _save(client, project_id, "agents", agents_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert "Security and hardening workflow" in str(
            rejected.json()["detail"]["files"]["AGENTS.md"]
        )
    setup_heading = "## Setup and verification commands"
    classed_heading = AGENTS_TEXT.replace(
        setup_heading, f'<div class="screen-only">\n{setup_heading}\n</div>'
    )
    agents_revision = _save(client, project_id, "agents", agents_revision, classed_heading)[
        "revision_number"
    ]
    rejected = _approve(client, project_id, project_revision, agents_revision)
    assert rejected.status_code == 422, rejected.text
    assert "Setup and verification commands" in str(rejected.json()["detail"]["files"]["AGENTS.md"])

    visible_project = PROJECT_TEXT.replace(
        problem,
        '- Problem: <span style="display:/* note */none">Not visible.</span>'
        '<span class="no-evidence">Also not evidence.</span>'
        "**Planning drafts need a human owner.**",
    )
    visible_agents = AGENTS_TEXT.replace(
        security,
        '<span style="opacity:0">Not evidence.</span>'
        '<span class="no-evidence">Not evidence either.</span>'
        "*Keep secrets out of Git; deny cross-project access.*",
    )
    project_revision = _save(client, project_id, "project", project_revision, visible_project)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, visible_agents)[
        "revision_number"
    ]
    assert _approve(client, project_id, project_revision, agents_revision).status_code == 200


def test_images_and_nonvisible_html_cannot_supply_required_decisions(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]

    problem = "- Problem: Planning drafts need a human owner."
    behavior = "A stale write reports a conflict; only saved versions can be approved."
    project_cases = (
        (PROJECT_TEXT.replace(problem, "- Problem: ![needs an owner][diagram]"), "Problem"),
        (PROJECT_TEXT.replace(problem, "- Problem: ![TBD][diagram]"), "Problem"),
        (PROJECT_TEXT.replace(problem, "- Problem: ![needs an owner][]"), "Problem"),
        (PROJECT_TEXT.replace(problem, "- Problem: ![needs an owner]"), "Problem"),
        (PROJECT_TEXT.replace(problem, "- Problem: ![needs an owner] [diagram]"), "Problem"),
        (
            PROJECT_TEXT.replace(problem, "- Problem: ![needs [an] owner](./diagrams/(plan).png)"),
            "Problem",
        ),
        (
            PROJECT_TEXT.replace(problem, "- Problem: <noscript>Needs an owner.</noscript>"),
            "Problem",
        ),
        (
            PROJECT_TEXT.replace(behavior, "![a decision][diagram]"),
            "Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(behavior, "<noscript>Save immutable versions.</noscript>"),
            "Behavior and domain rules",
        ),
        (
            PROJECT_TEXT.replace(
                "## 4. Technology and environment — required",
                "<noscript>\n## 4. Technology and environment — required\n</noscript>",
            ),
            "Technology and environment",
        ),
    )
    for content, error in project_cases:
        project_revision = _save(client, project_id, "project", project_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert error in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    security = "Keep secrets out of Git; deny cross-project access."
    setup_name = "Setup and verification commands"
    agents_cases = (
        (AGENTS_TEXT.replace(setup, "![Run the checks][diagram]"), setup_name),
        (AGENTS_TEXT.replace(setup, "![Run the checks][]"), setup_name),
        (AGENTS_TEXT.replace(setup, "![Run the checks]"), setup_name),
        (AGENTS_TEXT.replace(setup, "![Run the checks]\n[diagram]"), setup_name),
        (
            AGENTS_TEXT.replace(
                setup, "| Step | Instruction |\n| --- | --- |\n| API | ![Run checks][diagram] |"
            ),
            setup_name,
        ),
        (
            AGENTS_TEXT.replace(security, "<noscript>Keep secrets outside Git.</noscript>"),
            "Security and hardening workflow",
        ),
        (
            AGENTS_TEXT.replace(security, "<noembed>Keep secrets outside Git.</noembed>"),
            "Security and hardening workflow",
        ),
        (
            AGENTS_TEXT.replace(security, "<noframes>Keep secrets outside Git.</noframes>"),
            "Security and hardening workflow",
        ),
        (
            AGENTS_TEXT.replace(security, "<canvas>Keep secrets outside Git.</canvas>"),
            "Security and hardening workflow",
        ),
    )
    for content, error in agents_cases:
        agents_revision = _save(client, project_id, "agents", agents_revision, content)[
            "revision_number"
        ]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert error in str(rejected.json()["detail"]["files"]["AGENTS.md"])

    # Image alt text and fallback HTML never supply a decision, but adjacent
    # prose and ordinary reference-link labels remain eligible.
    visible_project = PROJECT_TEXT.replace(
        problem,
        "- Problem: ![only an illustration][diagram] "
        "[Planning drafts need a human owner][decision].",
    ).replace(
        behavior,
        "<noscript>Only fallback content.</noscript>\n"
        "Saved versions remain immutable. ![architecture diagram][diagram]",
    )
    visible_agents = AGENTS_TEXT.replace(
        setup,
        "![example][diagram] Run [the API checks][decision] from api/.",
    ).replace(
        security,
        "<noscript>Fallback policy.</noscript> Keep secrets out of Git.",
    )
    project_revision = _save(client, project_id, "project", project_revision, visible_project)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, visible_agents)[
        "revision_number"
    ]
    assert _approve(client, project_id, project_revision, agents_revision).status_code == 200


def test_approval_rejects_new_placeholders_in_required_project_decisions(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    _save(client, project_id, "agents", 1, AGENTS_TEXT)
    undecided_values = (
        "<DECIDE_LATER>",
        "<new_decision>",
        "<choose problem>",
        "<choose-problem>",
        "TBD",
        "TBD — decide later",
        "TODO: owner choice required",
        "to be completed",
        "not applicable",
        "Pending owner confirmation",
        "Unknown at this time",
        "unspecified",
        "N/A",
        "[TBD](#decision)",
        "**TBD**",
        "`TBD`",
        "<strong>TBD</strong>",
        "<review-panel>TBD</review-panel>",
        '<review-panel data-state="pending">TBD</review-panel>',
    )
    for index, undecided in enumerate(undecided_values, start=1):
        text = valid_project().replace(
            "- Problem: Planning drafts need a human owner.", f"- Problem: {undecided}"
        )
        _save(client, project_id, "project", index, text)
        response = _approve(client, project_id, index + 1, 2)
        assert response.status_code == 422, response.text
        assert set(response.json()["detail"]["files"]) == {"PROJECT.md"}
        messages = response.json()["detail"]["files"]["PROJECT.md"]
        assert any("Problem" in message for message in messages)
        if undecided in {"<DECIDE_LATER>", "<choose problem>", "<choose-problem>"}:
            assert any("placeholder" in message.lower() for message in messages)

    custom_markup_revision = len(undecided_values) + 1
    wrapped_decision = valid_project().replace(
        "- Problem: Planning drafts need a human owner.",
        "- Problem: <review-panel>Planning drafts need a human owner.</review-panel>",
    )
    _save(client, project_id, "project", custom_markup_revision, wrapped_decision)
    rejected_markup = _approve(client, project_id, custom_markup_revision + 1, 2)
    assert rejected_markup.status_code == 422, rejected_markup.text
    assert "Problem" in str(rejected_markup.json()["detail"]["files"]["PROJECT.md"])

    resolved = valid_project().replace(
        "- Problem: Planning drafts need a human owner.",
        "- Problem: **Planning drafts need a human owner.**",
    )
    _save(client, project_id, "project", custom_markup_revision + 1, resolved)
    assert _approve(client, project_id, custom_markup_revision + 2, 2).status_code == 200

    duplicate = valid_project().replace(
        "- Problem: Planning drafts need a human owner.",
        "- Problem: <new_decision>\n- Problem: Planning drafts need a human owner.",
    )
    _save(client, project_id, "project", custom_markup_revision + 2, duplicate)
    rejected_duplicate = _approve(client, project_id, custom_markup_revision + 3, 2)
    assert rejected_duplicate.status_code == 422
    assert "Problem" in str(rejected_duplicate.json()["detail"]["files"]["PROJECT.md"])


def test_new_angle_markers_are_rejected_in_both_documents_but_html_and_links_are_not(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_text = valid_project() + (
        "\nSee <https://example.invalid/path>, <em>the owner</em>, "
        '<a href="https://example.invalid/path">the project docs</a>, and '
        "<section hidden>optional details</section> and "
        "<review-panel hidden>private notes</review-panel>.\n"
    )
    agents_text = valid_agents() + (
        "\nUse <code>examples</code> only as illustrations. "
        "Render <review-panel>read-only details</review-panel>.\n"
    )
    _save(client, project_id, "project", 1, project_text)
    _save(client, project_id, "agents", 1, agents_text + "\nRun <setup_command> first.\n")
    agents_unresolved = _approve(client, project_id, 2, 2)
    assert agents_unresolved.status_code == 422
    assert set(agents_unresolved.json()["detail"]["files"]) == {"AGENTS.md"}
    assert (
        "placeholder" in " ".join(agents_unresolved.json()["detail"]["files"]["AGENTS.md"]).lower()
    )

    _save(client, project_id, "agents", 2, agents_text)
    _save(client, project_id, "project", 2, project_text + "\nDecision: <review_owner>\n")
    project_unresolved = _approve(client, project_id, 3, 3)
    assert project_unresolved.status_code == 422
    assert set(project_unresolved.json()["detail"]["files"]) == {"PROJECT.md"}

    _save(client, project_id, "project", 3, project_text + "\nDecision: <choose-problem>\n")
    dashed_unresolved = _approve(client, project_id, 4, 3)
    assert dashed_unresolved.status_code == 422
    assert set(dashed_unresolved.json()["detail"]["files"]) == {"PROJECT.md"}

    _save(client, project_id, "project", 4, project_text)
    _save(
        client,
        project_id,
        "agents",
        3,
        agents_text.replace(
            "Run `python3 -m pytest` from api/ after installing locked dependencies.",
            "- Setup command: <choose-command>",
        ),
    )
    dashed_agents_unresolved = _approve(client, project_id, 5, 4)
    assert dashed_agents_unresolved.status_code == 422
    assert set(dashed_agents_unresolved.json()["detail"]["files"]) == {"AGENTS.md"}
    assert "placeholder" in str(dashed_agents_unresolved.json()["detail"]["files"]).lower()

    _save(client, project_id, "agents", 4, agents_text)
    approved = _approve(client, project_id, 5, 5)
    assert approved.status_code == 200, approved.text


def test_simple_new_placeholders_and_undecided_agent_sections_reject_only_affected_file(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    _save(client, project_id, "project", 1, PROJECT_TEXT)
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    for revision, agents_text in enumerate(
        (
            valid_agents().replace(setup, "Run <owner> through setup."),
            valid_agents() + "\nThe human reviewer is <reviewer>.\n",
            valid_agents().replace(setup, "**TBD**"),
            valid_agents().replace(
                "Keep secrets out of Git; deny cross-project access.", "- `TBD`"
            ),
        ),
        start=1,
    ):
        _save(client, project_id, "agents", revision, agents_text)
        rejected = _approve(client, project_id, 2, revision + 1)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        if revision >= 3:
            assert any(
                "Setup and verification commands" in message
                or "Security and hardening workflow" in message
                for message in rejected.json()["detail"]["files"]["AGENTS.md"]
            )

    _save(client, project_id, "agents", 5, AGENTS_TEXT)
    assert _approve(client, project_id, 2, 6).status_code == 200


def test_required_agent_sections_reject_labeled_and_table_only_tbd(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    _save(client, project_id, "project", 1, PROJECT_TEXT)
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    undecided = (
        "- Setup command: TBD",
        "This setup matters.\n- Setup command: TBD",
        "| Task | Command |\n| --- | --- |\n| Setup | **TBD** |",
        "| Task | Command |\n| --- | --- |\n| Setup | TBD |\n| Check | `TBD` |",
        "| Task | Command |\n| --- | --- |\n| Setup | TBD |\nThis setup matters.",
        "This setup matters.\n| TBD |",
        "This setup matters.\n| Command |\n| --- |\n| **TBD** |",
        "| Command |\n| --- |",
    )
    for revision, replacement in enumerate(undecided, start=1):
        _save(client, project_id, "agents", revision, valid_agents().replace(setup, replacement))
        rejected = _approve(client, project_id, 2, revision + 1)
        assert rejected.status_code == 422, rejected.text
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert any(
            "Setup and verification commands" in error
            for error in rejected.json()["detail"]["files"]["AGENTS.md"]
        )

    valid_table = "| Task | Command |\n| --- | --- |\n| Check | `python3 -m pytest` |"
    _save(
        client,
        project_id,
        "agents",
        len(undecided) + 1,
        valid_agents().replace(setup, valid_table),
    )
    assert _approve(client, project_id, 2, len(undecided) + 2).status_code == 200

    valid_single_column = "| Command |\n| --- |\n| `python3 -m pytest` |"
    _save(
        client,
        project_id,
        "agents",
        len(undecided) + 2,
        valid_agents().replace(setup, valid_single_column),
    )
    assert _approve(client, project_id, 2, len(undecided) + 3).status_code == 200


def test_pipe_prose_and_table_boundaries_preserve_decisions_and_reject_ambiguity(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    behavior = "A stale write reports a conflict; only saved versions can be approved."
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    positive_pairs = (
        (
            r"Save `PROJECT.md` \| `AGENTS.md` after review.",
            r"Run `python3 -m pytest` \| `ruff check .` from api/.",
        ),
        (
            "Save `PROJECT.md` | `AGENTS.md` after review.",
            "Run `python3 -m pytest` | `ruff check .` from api/.",
        ),
        (
            "Save PROJECT.md | AGENTS.md after review.",
            "Run pytest | ruff from api/ after installing locked dependencies.",
        ),
        (
            "| Case | Decision |\n| --- | --- |\n"
            r"| Stale write | Save `PROJECT.md \| AGENTS.md` and show conflict. |",
            "| Check | Command |\n| --- | --- |\n"
            r"| API | Run `pytest | ruff` after installing locked dependencies. |",
        ),
        (
            "Case | Decision\n--- | ---\nStale write | Preserve immutable revisions.",
            "Check | Command\n--- | ---\nAPI | Run pytest from api/.",
        ),
    )
    for project_text, agents_text in positive_pairs:
        project_revision = _save(
            client,
            project_id,
            "project",
            project_revision,
            PROJECT_TEXT.replace(behavior, project_text),
        )["revision_number"]
        agents_revision = _save(
            client,
            project_id,
            "agents",
            agents_revision,
            AGENTS_TEXT.replace(setup, agents_text),
        )["revision_number"]
        approved = _approve(client, project_id, project_revision, agents_revision)
        assert approved.status_code == 200, (project_text, agents_text, approved.text)

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    for undecided in (
        "A stale write creates a conflict.\n| TBD |",
        "Run pytest | ruff | mypy",
        "Case | Decision\n--- | ---\nStale write | Save drafts | extra",
    ):
        project_revision = _save(
            client,
            project_id,
            "project",
            project_revision,
            PROJECT_TEXT.replace(behavior, undecided),
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, (undecided, rejected.text)
        assert "Behavior and domain rules" in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    for undecided in (
        "| TBD |",
        "A stale write creates a conflict.\n| TBD |",
        "| Rule | Decision |\n| --- | --- |\n| Conflict | TBD |",
        "| Rule | Decision |\n| --- | --- |\n| Conflict | Save drafts | extra |",
        "Run pytest | ruff | mypy",
    ):
        agents_revision = _save(
            client, project_id, "agents", agents_revision, AGENTS_TEXT.replace(setup, undecided)
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, (undecided, rejected.text)
        assert "Setup and verification commands" in str(
            rejected.json()["detail"]["files"]["AGENTS.md"]
        )


def test_thematic_breaks_neither_supply_nor_invalidate_required_decisions(
    client: TestClient, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    behavior = "A stale write reports a conflict; only saved versions can be approved."
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    problem = "- Problem: Planning drafts need a human owner."
    for break_line in (
        "---",
        "***",
        "___",
        "  -  -  -  ",
        " * * * ",
        " _  _  _ ",
        "-\t-\t-",
    ):
        project_text = PROJECT_TEXT.replace(behavior, f"{behavior}\n{break_line}").replace(
            problem, f"{problem}\n{break_line}"
        )
        agents_text = AGENTS_TEXT.replace(setup, f"{setup}\n{break_line}")
        project_revision = _save(client, project_id, "project", project_revision, project_text)[
            "revision_number"
        ]
        agents_revision = _save(client, project_id, "agents", agents_revision, agents_text)[
            "revision_number"
        ]
        accepted = _approve(client, project_id, project_revision, agents_revision)
        assert accepted.status_code == 200, (break_line, accepted.text)

    project_missing = PROJECT_TEXT.replace(behavior, " *  *  * ")
    agents_missing = AGENTS_TEXT.replace(setup, " _  _  _ ")
    project_revision = _save(client, project_id, "project", project_revision, project_missing)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, agents_missing)[
        "revision_number"
    ]
    missing = _approve(client, project_id, project_revision, agents_revision)
    assert missing.status_code == 422
    assert set(missing.json()["detail"]["files"]) == {"PROJECT.md", "AGENTS.md"}
    assert "Behavior and domain rules" in str(missing.json()["detail"]["files"]["PROJECT.md"])
    assert "Setup and verification commands" in str(missing.json()["detail"]["files"]["AGENTS.md"])

    mixed_project = PROJECT_TEXT.replace(behavior, "*_- ")
    mixed_agents = AGENTS_TEXT.replace(setup, "*_- ")
    project_revision = _save(client, project_id, "project", project_revision, mixed_project)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, mixed_agents)[
        "revision_number"
    ]
    ambiguous = _approve(client, project_id, project_revision, agents_revision)
    assert ambiguous.status_code == 422
    assert set(ambiguous.json()["detail"]["files"]) == {"PROJECT.md", "AGENTS.md"}

    project_unresolved = PROJECT_TEXT.replace(behavior, f"{behavior}\n---\n- Retry: TBD")
    agents_unresolved = AGENTS_TEXT.replace(setup, f"{setup}\n***\n| Command | TBD |")
    project_revision = _save(client, project_id, "project", project_revision, project_unresolved)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, agents_unresolved)[
        "revision_number"
    ]
    rejected = _approve(client, project_id, project_revision, agents_revision)
    assert rejected.status_code == 422
    assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md", "AGENTS.md"}
    assert "Resolve undecided decisions" in str(rejected.json()["detail"]["files"]["PROJECT.md"])
    assert "Resolve undecided decisions" in str(rejected.json()["detail"]["files"]["AGENTS.md"])


def test_multiline_reference_definitions_do_not_supply_decisions_or_current_approval(
    client: TestClient, engine, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    behavior = "A stale write reports a conflict; only saved versions can be approved."
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    reference_blocks = (
        '[checks]: https://example.invalid/plan\n  "Save immutable revisions."',
        "[checks]: https://example.invalid/plan\n\t'Run locked checks.'",
        "[checks]: https://example.invalid/plan\n (Keep the draft private.)",
        '[checks]:\n  https://example.invalid/plan\n  "Run locked checks."',
        '[checks]: https://example.invalid/plan\n  "Unclosed title\nRun locked checks.',
    )
    for definition in reference_blocks:
        project_revision = _save(
            client,
            project_id,
            "project",
            project_revision,
            PROJECT_TEXT.replace(behavior, definition),
        )["revision_number"]
        agents_revision = _save(
            client,
            project_id,
            "agents",
            agents_revision,
            AGENTS_TEXT.replace(setup, definition),
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, (definition, rejected.text)
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md", "AGENTS.md"}
        assert "Behavior and domain rules" in str(rejected.json()["detail"]["files"]["PROJECT.md"])
        assert "Setup and verification commands" in str(
            rejected.json()["detail"]["files"]["AGENTS.md"]
        )

    # A title is tied to the immediately preceding definition; after a blank
    # line, genuine Markdown list/prose remains eligible and indented code does not.
    definition = reference_blocks[0]
    project_good = PROJECT_TEXT.replace(
        behavior,
        definition + "\n\n    Not a decision: code example.\n- Preserve immutable revisions.",
    )
    agents_good = AGENTS_TEXT.replace(
        setup,
        definition + "\n\n    Not a decision: code example.\nRun locked checks from api/.",
    )
    project_revision = _save(client, project_id, "project", project_revision, project_good)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, agents_good)[
        "revision_number"
    ]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200, approved.text

    # The blank line ends the definition: similarly indented quoted prose is
    # now a visible paragraph, not a title belonging to the reference.
    project_quoted_prose = PROJECT_TEXT.replace(
        behavior, definition + '\n\n  "Preserve immutable revisions."'
    )
    agents_quoted_prose = AGENTS_TEXT.replace(
        setup, definition + '\n\n  "Run locked checks from api/."'
    )
    project_revision = _save(client, project_id, "project", project_revision, project_quoted_prose)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, agents_quoted_prose)[
        "revision_number"
    ]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200, approved.text

    with Session(engine) as db:
        revision = db.get(ProjectDocumentRevision, uuid.UUID(approved.json()["agents_revision_id"]))
        assert revision is not None
        revision.content = AGENTS_TEXT.replace(setup, reference_blocks[0])
        revision.content_sha256 = hashlib.sha256(revision.content.encode()).hexdigest()
        db.commit()
    path = f"/api/projects/{project_id}/document-pair-approval"
    current = client.get(path)
    assert current.status_code == 200
    assert current.json()["approved"] is False
    assert current.json()["latest_approval"]["id"] == approved.json()["id"]
    repeated = _approve(client, project_id, project_revision, agents_revision)
    assert repeated.status_code == 422
    assert set(repeated.json()["detail"]["files"]) == {"AGENTS.md"}


def test_link_destinations_never_supply_required_decisions_or_current_approval(
    client: TestClient, engine, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    project_revision = _save(client, project_id, "project", 1, PROJECT_TEXT)["revision_number"]
    agents_revision = _save(client, project_id, "agents", 1, AGENTS_TEXT)["revision_number"]
    problem = "- Problem: Planning drafts need a human owner."
    setup = "Run `python3 -m pytest` from api/ after installing locked dependencies."
    project_bad = (
        "[](https://example.invalid/(x)Needs an owner)",
        r"[](https://example.invalid/\)Needs an owner)",
        '[](https://example.invalid/path "Needs an owner")',
        "[][checks]",
        "[](https://example.invalid/(x)Needs an owner",
        '[Planning drafts need an owner](https://example.invalid/(x) "unclosed title"',
        "[Planning drafts need an owner](https://example.invalid/a Needs an owner)",
        '![Needs an owner](https://example.invalid/(x) "title )")',
    )
    for link in project_bad:
        project_revision = _save(
            client,
            project_id,
            "project",
            project_revision,
            PROJECT_TEXT.replace(problem, f"- Problem: {link}"),
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, (link, rejected.text)
        assert set(rejected.json()["detail"]["files"]) == {"PROJECT.md"}
        assert "Problem" in str(rejected.json()["detail"]["files"]["PROJECT.md"])

    project_revision = _save(client, project_id, "project", project_revision, PROJECT_TEXT)[
        "revision_number"
    ]
    agents_bad = (
        "[](https://example.invalid/(x)Run locked API checks)",
        r"[](https://example.invalid/\)Run locked API checks)",
        '[](https://example.invalid/path "Run locked API checks")',
        "[][checks]",
        "[](https://example.invalid/(x)Run locked API checks",
        '[Run locked API checks](https://example.invalid/(x) "unclosed title"',
        "[Run locked API checks](https://example.invalid/a Run locked checks)",
        '![Run locked API checks](https://example.invalid/(x) "title )")',
    )
    for link in agents_bad:
        agents_revision = _save(
            client, project_id, "agents", agents_revision, AGENTS_TEXT.replace(setup, link)
        )["revision_number"]
        rejected = _approve(client, project_id, project_revision, agents_revision)
        assert rejected.status_code == 422, (link, rejected.text)
        assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}
        assert "Setup and verification commands" in str(
            rejected.json()["detail"]["files"]["AGENTS.md"]
        )

    positive_project = PROJECT_TEXT.replace(
        problem,
        "- Problem: [Planning drafts need a human owner]"
        '(https://example.invalid/(x) "note ) in title") '
        "and `[](url)` is a literal inline-code example.",
    )
    positive_agents = AGENTS_TEXT.replace(
        setup,
        "Run [locked API checks][checks] and `python3 -m pytest` from api/. "
        r"[Review the steps](https://example.invalid/\)docs).",
    )
    project_revision = _save(client, project_id, "project", project_revision, positive_project)[
        "revision_number"
    ]
    agents_revision = _save(client, project_id, "agents", agents_revision, positive_agents)[
        "revision_number"
    ]
    approved = _approve(client, project_id, project_revision, agents_revision)
    assert approved.status_code == 200, approved.text

    with Session(engine) as db:
        revision = db.get(
            ProjectDocumentRevision, uuid.UUID(approved.json()["project_revision_id"])
        )
        assert revision is not None
        revision.content = PROJECT_TEXT.replace(problem, f"- Problem: {project_bad[0]}")
        revision.content_sha256 = hashlib.sha256(revision.content.encode()).hexdigest()
        db.commit()
    path = f"/api/projects/{project_id}/document-pair-approval"
    status_response = client.get(path)
    assert status_response.status_code == 200
    assert status_response.json()["approved"] is False
    assert status_response.json()["latest_approval"]["id"] == approved.json()["id"]
    repeated = _approve(client, project_id, project_revision, agents_revision)
    assert repeated.status_code == 422
    assert set(repeated.json()["detail"]["files"]) == {"PROJECT.md"}


def test_admin_invalid_stale_and_idempotent_approval_posts_audit_private_reads(
    client: TestClient, engine, settings: AppSettings, workspace_root, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    admin_id = account_factory("audit-admin", "correct horse battery", role="admin")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client, "Private pair audit")
    private_project = valid_project("Private specification sentinel")
    private_agents = valid_agents("Private rules sentinel")
    _save(client, project_id, "project", 1, private_project)
    _save(client, project_id, "agents", 1, private_agents)
    invalid_project = private_project.replace(
        "- Problem: Planning drafts need a human owner.", "- Problem: <new_decision>"
    )
    _save(client, project_id, "project", 2, invalid_project)

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as admin:
        _login(admin, "audit-admin", "correct horse battery")
        invalid = _approve(admin, project_id, 3, 2)
        assert invalid.status_code == 422
        assert set(invalid.json()["detail"]["files"]) == {"PROJECT.md"}
        assert invalid_project not in invalid.text and private_agents not in invalid.text

        stale = _approve(admin, project_id, 1, 1)
        assert stale.status_code == 409
        assert stale.json()["latest"]["project"]["content"] == invalid_project
        assert stale.json()["latest"]["agents"]["content"] == private_agents

        _save(client, project_id, "project", 3, private_project)
        approved = _approve(client, project_id, 4, 2)
        assert approved.status_code == 200
        repeated = _approve(admin, project_id, 4, 2)
        assert repeated.status_code == 200
        assert repeated.json()["id"] == approved.json()["id"]

    with Session(engine) as db:
        reads = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "admin.project.document_pair_approval.read",
                    AuditEvent.actor_user_id == admin_id,
                    AuditEvent.project_id == uuid.UUID(project_id),
                )
            ).all()
        )
        assert sorted(event.details["operation"] for event in reads) == [
            "idempotent_post",
            "stale_post",
            "validation_error_post",
        ]
        invalid_read = next(
            event for event in reads if event.details["operation"] == "validation_error_post"
        )
        assert invalid_read.details == {
            "operation": "validation_error_post",
            "project_revision_number": 3,
            "agents_revision_number": 2,
        }
        assert all(
            invalid_project not in str(event.details)
            and private_project not in str(event.details)
            and private_agents not in str(event.details)
            for event in reads
        )
        assert (
            db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "project.document_pair.approved",
                    AuditEvent.project_id == uuid.UUID(project_id),
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(ProjectDocumentPairApproval.id)).where(
                    ProjectDocumentPairApproval.project_id == uuid.UUID(project_id)
                )
            )
            == 1
        )


def test_existing_approval_fails_closed_when_saved_pair_becomes_invalid(
    client: TestClient, engine, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client)
    _save(client, project_id, "project", 1, PROJECT_TEXT)
    _save(client, project_id, "agents", 1, AGENTS_TEXT)
    first = _approve(client, project_id, 2, 2)
    assert first.status_code == 200
    # Model an old row that was admitted before stronger validation (or damaged
    # stored content). Its tuple must not be reported approved or returned as an
    # idempotent success merely because the immutable approval row still exists.
    with Session(engine) as db:
        revision = db.get(ProjectDocumentRevision, uuid.UUID(first.json()["agents_revision_id"]))
        assert revision is not None
        revision.content = "# Bare rules\nNothing decided.\n"
        revision.content_sha256 = hashlib.sha256(revision.content.encode()).hexdigest()
        db.commit()

    path = f"/api/projects/{project_id}/document-pair-approval"
    status_response = client.get(path)
    assert status_response.status_code == 200
    assert status_response.json()["approved"] is False
    assert status_response.json()["latest_approval"]["id"] == first.json()["id"]
    rejected = _approve(client, project_id, 2, 2)
    assert rejected.status_code == 422
    assert set(rejected.json()["detail"]["files"]) == {"AGENTS.md"}


def test_pair_approval_is_idempotent_audited_and_stale_saves_invalidate_it(
    client: TestClient,
    engine,
    account_factory,
) -> None:
    owner_id = account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client, "Immutable pair approval")
    project_text = valid_project("Private approval payload Project-only sentinel")
    agents_text = valid_agents("Private agent policy Agent-only sentinel")
    _save(client, project_id, "project", 1, project_text)
    _save(client, project_id, "agents", 1, agents_text)
    path = f"/api/projects/{project_id}/document-pair-approval"

    initial_status = client.get(path)
    assert initial_status.status_code == 200
    assert initial_status.json()["approved"] is False
    assert initial_status.json()["latest_approval"] is None

    created = _approve(client, project_id, 2, 2)
    repeated = _approve(client, project_id, 2, 2)
    assert created.status_code == repeated.status_code == 200
    assert repeated.json()["id"] == created.json()["id"]
    assert created.json()["project_revision_id"] != created.json()["agents_revision_id"]

    with Session(engine) as db:
        records = list(db.scalars(select(ProjectDocumentPairApproval)).all())
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "project.document_pair.approved",
                    AuditEvent.project_id == uuid.UUID(project_id),
                )
            ).all()
        )
        assert len(records) == len(events) == 1
        assert records[0].actor_user_id == owner_id
        assert events[0].details == {
            "project_revision_id": created.json()["project_revision_id"],
            "project_revision_number": 2,
            "agents_revision_id": created.json()["agents_revision_id"],
            "agents_revision_number": 2,
        }
        assert project_text not in str(events[0].details)
        assert agents_text not in str(events[0].details)

    current = client.get(path).json()
    assert current["approved"] is True
    assert current["latest_approval"]["id"] == created.json()["id"]

    newer_agents = valid_agents("Changed agent policy; a later saved revision invalidates approval")
    _save(client, project_id, "agents", 2, newer_agents)
    pending = client.get(path).json()
    assert pending["approved"] is False
    assert pending["current_project_revision"]["revision_number"] == 2
    assert pending["current_agents_revision"]["revision_number"] == 3
    assert pending["latest_approval"]["id"] == created.json()["id"]
    assert pending["latest_approval"]["agents_revision_number"] == 2

    stale = _approve(client, project_id, 2, 2)
    assert stale.status_code == 409
    assert stale.json()["latest"]["project"]["revision_number"] == 2
    assert stale.json()["latest"]["agents"]["revision_number"] == 3
    assert stale.json()["latest"]["agents"]["content"] == newer_agents
    assert stale.json()["approval_status"]["approved"] is False
    with Session(engine) as db:
        assert len(list(db.scalars(select(ProjectDocumentPairApproval)).all())) == 1

    new_project = valid_project("Updated project document; a second approved pair")
    _save(client, project_id, "project", 2, new_project)
    second = _approve(client, project_id, 3, 3)
    assert second.status_code == 200
    assert second.json()["id"] != created.json()["id"]

    first_page = client.get(path, params={"limit": 1, "offset": 0}).json()
    assert first_page["approved"] is True
    assert first_page["latest_approval"]["id"] == second.json()["id"]
    assert [item["id"] for item in first_page["approvals"]] == [second.json()["id"]]
    assert first_page["approval_has_more"] is True
    older_page = client.get(
        path, params={"limit": 1, "cursor": first_page["approval_next_cursor"]}
    ).json()
    assert [item["id"] for item in older_page["approvals"]] == [created.json()["id"]]
    assert older_page["approval_next_cursor"] is None
    assert client.get(path, params={"limit": 1, "cursor": "not-a-cursor"}).status_code == 422
    too_early = "0001-01-01T00:00:00+23:00|00000000-0000-4000-8000-000000000001"
    assert client.get(path, params={"cursor": too_early}).status_code == 422
    assert client.get(path, params={"limit": 1, "offset": 1}).status_code == 422

    with Session(engine) as db:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "project.document_pair.approved",
                    AuditEvent.project_id == uuid.UUID(project_id),
                )
            ).all()
        )
        assert len(list(db.scalars(select(ProjectDocumentPairApproval)).all())) == 2
        assert len(events) == 2
        assert all(project_text not in str(event.details) for event in events)
        assert all(agents_text not in str(event.details) for event in events)


def test_approval_cursor_does_not_repeat_rows_after_newer_pair_is_inserted(
    client: TestClient, engine, account_factory
) -> None:
    account_factory("owner", "correct horse battery")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client, "History cursor")
    _save(client, project_id, "project", 1, PROJECT_TEXT)
    _save(client, project_id, "agents", 1, AGENTS_TEXT)
    first = _approve(client, project_id, 2, 2)
    assert first.status_code == 200
    _save(client, project_id, "project", 2, valid_project("Second pair"))
    second = _approve(client, project_id, 3, 2)
    assert second.status_code == 200
    path = f"/api/projects/{project_id}/document-pair-approval"
    page_one = client.get(path, params={"limit": 1}).json()
    assert [item["id"] for item in page_one["approvals"]] == [second.json()["id"]]
    assert page_one["approval_next_cursor"]

    _save(client, project_id, "project", 3, valid_project("Third pair"))
    third = _approve(client, project_id, 4, 2)
    assert third.status_code == 200
    page_two = client.get(
        path, params={"limit": 1, "cursor": page_one["approval_next_cursor"]}
    ).json()
    assert [item["id"] for item in page_two["approvals"]] == [first.json()["id"]]
    assert page_two["approval_next_cursor"] is None
    assert page_two["latest_approval"]["id"] == third.json()["id"]
    assert page_two["approved"] is True
    assert page_two["current_project_revision"]["revision_number"] == 4

    # A timestamp tie must use the UUID tie-breaker, not an unstable offset.
    with Session(engine) as db:
        db.execute(
            update(ProjectDocumentPairApproval)
            .where(
                ProjectDocumentPairApproval.id.in_(
                    [uuid.UUID(first.json()["id"]), uuid.UUID(second.json()["id"])]
                )
            )
            .values(created_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
        db.commit()
    root_page = client.get(path, params={"limit": 1}).json()
    assert [item["id"] for item in root_page["approvals"]] == [third.json()["id"]]
    tie_one = client.get(
        path, params={"limit": 1, "cursor": root_page["approval_next_cursor"]}
    ).json()
    tie_two = client.get(
        path, params={"limit": 1, "cursor": tie_one["approval_next_cursor"]}
    ).json()
    assert [tie_one["approvals"][0]["id"], tie_two["approvals"][0]["id"]] == sorted(
        [first.json()["id"], second.json()["id"]], reverse=True
    )
    assert tie_two["approval_next_cursor"] is None


def test_pair_approval_authorization_csrf_and_strict_expected_versions(
    client: TestClient,
    engine,
    settings: AppSettings,
    account_factory,
    workspace_root,
) -> None:
    owner_id = account_factory("owner", "correct horse battery")
    account_factory("outsider", "correct horse battery")
    admin_id = account_factory("review-admin", "correct horse battery", role="admin")
    _login(client, "owner", "correct horse battery")
    project_id = _create_project(client, "Private approval")
    _save(client, project_id, "project", 1, PROJECT_TEXT)
    _save(client, project_id, "agents", 1, AGENTS_TEXT)
    path = f"/api/projects/{project_id}/document-pair-approval"
    payload = {"expected_project_revision": 2, "expected_agents_revision": 2}

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as anonymous:
        assert anonymous.get(path).status_code == 401
        csrf = anonymous.get("/api/auth/csrf").json()["csrf_token"]
        unauthenticated = anonymous.post(
            path,
            json=payload,
            headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": csrf},
        )
        assert unauthenticated.status_code == 401

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as outsider:
        _login(outsider, "outsider", "correct horse battery")
        assert outsider.get(path).status_code == 404
        foreign_cursor = "2026-09-29T12:00:00.000000+00:00|00000000-0000-4000-8000-000000000001"
        assert outsider.get(path, params={"cursor": foreign_cursor}).status_code == 404
        assert _approve(outsider, project_id, 2, 2).status_code == 404

    bad_origin = _approve(
        client,
        project_id,
        2,
        2,
        headers=_headers(client, origin="https://attacker.invalid"),
    )
    missing_csrf = _approve(
        client,
        project_id,
        2,
        2,
        headers={"Origin": PUBLIC_ORIGIN},
    )
    strict_string = _approve(client, project_id, "2", 2)
    strict_float = _approve(client, project_id, 2.0, 2)
    strict_bool = _approve(client, project_id, True, 2)
    extra_field = _approve(client, project_id, 2, 2, body_extras={"approved": True})
    assert bad_origin.status_code == missing_csrf.status_code == 403
    assert all(
        response.status_code == 422
        for response in (strict_string, strict_float, strict_bool, extra_field)
    )

    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as admin_client:
        _login(admin_client, "review-admin", "correct horse battery")
        approved = _approve(admin_client, project_id, 2, 2)
        assert approved.status_code == 200
        assert approved.json()["actor_user_id"] == str(admin_id)
        assert admin_client.get(path).status_code == 200

    with Session(engine) as db:
        approvals = list(db.scalars(select(ProjectDocumentPairApproval)).all())
        assert len(approvals) == 1
        assert approvals[0].actor_user_id == admin_id
        assert owner_id != admin_id
        assert (
            db.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.action == "admin.project.document_pair_approval.read",
                    AuditEvent.actor_user_id == admin_id,
                )
            )
            is not None
        )


def test_approval_reauthenticates_after_rate_limit_commit(
    client: TestClient,
    engine,
    account_factory,
    monkeypatch,
) -> None:
    owner_id = account_factory("race-owner", "correct horse battery")
    _login(client, "race-owner", "correct horse battery")
    project_id = _create_project(client, "Approval recheck")
    _save(client, project_id, "project", 1, PROJECT_TEXT)
    _save(client, project_id, "agents", 1, AGENTS_TEXT)
    original_consume = approval_module.consume_rate_bucket

    def deactivate_during_limiter_commit(db, **kwargs):
        decision = original_consume(db, **kwargs)
        db.execute(update(User).where(User.id == owner_id).values(is_active=False))
        return decision

    monkeypatch.setattr(approval_module, "consume_rate_bucket", deactivate_during_limiter_commit)
    response = _approve(client, project_id, 2, 2)
    assert response.status_code == 401

    with Session(engine) as db:
        owner = db.get(User, owner_id)
        assert owner is not None and owner.is_active is False
        assert db.scalar(select(ProjectDocumentPairApproval.id).limit(1)) is None
        assert (
            db.scalar(
                select(AuditEvent.id).where(AuditEvent.action == "project.document_pair.approved")
            )
            is None
        )
