from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.backlog_markdown import (
    BacklogValidationError,
    has_unclosed_fence,
    parse_backlog,
    validate_backlog_write,
)

FIXTURE = """# Runner-compatible fixture

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


def test_canonical_fixture_matches_root_heading_and_eligibility_semantics() -> None:
    parsed = parse_backlog(FIXTURE)
    ready_ids = [task.id for task in parsed.tasks if task.ready]
    eligible_ids = [task.id for task in parsed.tasks if task.eligible]
    waiting_ids = {task.id: list(task.waiting_on) for task in parsed.tasks if task.waiting_on}

    root = _root_helper()
    root_ready, root_waiting = root.eligible_items(FIXTURE)

    assert [task["title"].split(" — ", 1)[0] for task in root_ready] == eligible_ids
    assert ready_ids == ["TASK-002", "TASK-004"]
    assert waiting_ids == {"TASK-004": ["TASK-003"]}
    assert parsed.summary.draft_count == 1
    assert parsed.summary.ready_count == 2
    assert parsed.summary.eligible_count == len(root_ready) == 1
    assert parsed.summary.waiting_count == len(root_waiting) == 1
    assert parsed.tasks[0].metadata_lines == (
        "**Branch:** foundation",
        "**PR:** https://example.invalid/123",
    )
    assert parsed.tasks[1].acceptance == "- The saved body remains readable."
    assert parsed.tasks[1].verification == "- Run focused tests."


def test_fenced_task_examples_are_ignored_like_the_root_helper() -> None:
    content = FIXTURE + "\n```markdown\n## [x] TASK-999 — Example only\n```\n"

    parsed = parse_backlog(content)
    root_items = _root_helper().get_items(content)

    assert [task.id for task in parsed.tasks] == ["TASK-001", "TASK-002", "TASK-003", "TASK-004"]
    assert len(root_items) == len(parsed.tasks)


def test_fenced_dependency_lines_follow_the_root_helper_body_scan() -> None:
    content = """# Runner-compatible fixture

## [x] TASK-001 — Foundation
**Depends on:** None

## [ ] TASK-002 — Fenced dependency
```markdown
**Depends on:** TASK-001
```
"""

    parsed = parse_backlog(content)
    root_ready, root_waiting = _root_helper().eligible_items(content)
    task = parsed.tasks[1]

    # The compatibility helper scans dependency declarations inside task bodies
    # without excluding fenced examples. The task view deliberately reports the
    # same readiness so it cannot claim a state the runner would not act on.
    assert task.dependencies == ("TASK-001",)
    assert task.ready and task.eligible
    assert [item["title"].split(" — ", 1)[0] for item in root_ready] == [task.id]
    assert root_waiting == []


def test_horizontal_rule_separator_stays_outside_the_task_body() -> None:
    parsed = parse_backlog(FIXTURE)
    foundation = parsed.tasks[0]

    assert foundation.body.endswith("- Run the root helper.")
    assert parsed.content[foundation.body_end : foundation.raw_end] == "\n\n---\n\n"


def test_non_task_level_two_heading_is_outside_editable_body_but_root_scan_includes_it() -> None:
    content = """# Runner-compatible fixture

## [ ] TASK-001 — Dependent

### Done looks like
- This is the editable task body.

## Reference notes
**Depends on:** TASK-002
This text belongs to the backlog, not TASK-001.

## [x] TASK-002 — Complete
**Depends on:** None

## [-] TASK-003 — Draft prerequisite
**Depends on:** None
"""

    parsed = parse_backlog(content)
    root = _root_helper()
    root_items = root.get_items(content)
    root_ready, root_waiting = root.eligible_items(content)
    dependent = parsed.tasks[0]

    assert "## Reference notes" not in dependent.body
    assert "## Reference notes" in root_items[0]["body"]
    assert content[dependent.body_end : dependent.raw_end].startswith("## Reference notes\n")
    assert dependent.dependencies == ("TASK-002",)
    assert content[dependent.dependency_value_start : dependent.dependency_value_end] == "TASK-002"
    assert dependent.dependency_value_start >= dependent.body_end
    assert dependent.ready and dependent.eligible
    assert [item["title"].split(" — ", 1)[0] for item in root_ready] == [dependent.id]
    assert root_waiting == []

    edited = content.replace("**Depends on:** TASK-002", "**Depends on:** TASK-003", 1)
    edited_task = parse_backlog(edited).tasks[0]
    edited_ready, edited_waiting = root.eligible_items(edited)
    assert edited_task.dependencies == ("TASK-003",)
    assert edited_task.waiting_on == ("TASK-003",)
    assert edited_ready == []
    assert [
        (item["title"].split(" — ", 1)[0], dependencies) for item, dependencies in edited_waiting
    ] == [("TASK-001", ["TASK-003"])]


def test_dependency_declarations_split_between_task_body_and_notes_are_ambiguous() -> None:
    content = """## [ ] TASK-001 — Ambiguous dependency
**Depends on:** None

## Reference notes
**Depends on:** TASK-002

## [x] TASK-002 — Complete
**Depends on:** None
"""

    with pytest.raises(BacklogValidationError, match="exactly one Depends on"):
        parse_backlog(content)
    with pytest.raises(ValueError, match="Multiple dependency declarations"):
        _root_helper().eligible_items(content)


def test_raw_write_guards_metadata_and_execution_outcomes_after_non_task_headings() -> None:
    content = """## [x] TASK-001 — Completed
**Depends on:** None

## Outcome details
The runner verified this result.
**Branch:** feature/original
**PR:** https://example.invalid/1

## [-] TASK-002 — Draft
**Depends on:** TASK-001

## Planning notes
**Branch:** later-branch
**PR:** pending
"""
    parsed = parse_backlog(content)
    root = _root_helper().get_items(content)
    assert "## Outcome details" not in parsed.tasks[0].body
    assert "**Branch:** feature/original" in root[0]["body"]
    assert "**Branch:** later-branch" in root[1]["body"]

    for altered in (
        content.replace("The runner verified this result.", "Unverified result."),
        content.replace("**Branch:** feature/original", "**Branch:** feature/forged"),
        content.replace("**PR:** https://example.invalid/1", "**PR:** https://example.invalid/2"),
        content.replace("**Branch:** later-branch", "**Branch:** forged"),
        content.replace("**PR:** pending", "**PR:** forged"),
    ):
        with pytest.raises(BacklogValidationError):
            validate_backlog_write(content, altered)


@pytest.mark.parametrize(
    "metadata_line",
    [
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
    ],
)
def test_line_oriented_branch_and_pr_metadata_forms_are_protected(
    metadata_line: str,
) -> None:
    content = "\n".join(
        [
            "## [-] TASK-001 — Planning task",
            "**Depends on:** None",
            "",
            "## Task notes",
            metadata_line,
            "",
        ]
    )

    parsed = parse_backlog(content)
    assert parsed.tasks[0].metadata_lines == (metadata_line,)

    altered = content.replace(metadata_line, f"{metadata_line} changed", 1)
    with pytest.raises(BacklogValidationError, match="Branch/PR metadata"):
        validate_backlog_write(content, altered)


@pytest.mark.parametrize(
    ("fence_tail", "unclosed"),
    [
        (
            "```text\nBranch: fenced\nPR: fenced\n```\n",
            False,
        ),
        (
            "~~~markdown\nBranch: fenced\nPR: fenced\n",
            True,
        ),
    ],
)
def test_fenced_and_inline_branch_pr_mentions_are_not_runner_metadata(
    fence_tail: str,
    unclosed: bool,
) -> None:
    content = (
        "## [-] TASK-001 — Planning task\n"
        "**Depends on:** None\n"
        "The words Branch: inline and PR: inline are explanatory prose.\n"
        f"{fence_tail}"
    )

    parsed = parse_backlog(content)
    assert parsed.tasks[0].metadata_lines == ()
    assert has_unclosed_fence(content) is unclosed

    altered = content.replace("Branch: inline", "Branch: revised", 1).replace(
        "Branch: fenced", "Branch: revised in example", 1
    )
    assert validate_backlog_write(content, altered).content == altered


@pytest.mark.parametrize(
    ("content", "unclosed"),
    [
        ("", False),
        ("```markdown\n## [x] TASK-999 — Example\n```\n", False),
        ("```markdown\n## [x] TASK-999 — Example\n", True),
    ],
)
def test_fence_state_distinguishes_a_closed_example_from_an_unclosed_tail(
    content: str,
    unclosed: bool,
) -> None:
    assert has_unclosed_fence(content) is unclosed


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            FIXTURE.replace("TASK-004 — Waiting follow-up", "task-001 — duplicate id"),
            "Duplicate task ID",
        ),
        (
            FIXTURE.replace("TASK-004 — Waiting follow-up", "TASK-004 — ready follow-up"),
            "Duplicate task title",
        ),
        (
            FIXTURE.replace("**Depends on:** TASK-003", "**Depends on:** TASK-999"),
            "unknown dependency",
        ),
        (
            FIXTURE.replace("**Depends on:** TASK-003", "**Depends on:** TASK-004"),
            "cannot depend on itself",
        ),
        (
            FIXTURE.replace("**Depends on:** TASK-001", "**Depends on:** TASK-004").replace(
                "**Depends on:** TASK-003", "**Depends on:** TASK-002"
            ),
            "Dependency cycle",
        ),
        (
            FIXTURE.replace(
                "**Depends on:** TASK-003",
                "**Depends on:** None\n**Depends on:** None",
            ),
            "exactly one Depends on",
        ),
        (FIXTURE.replace("## [ ] TASK-002", "## [?] TASK-002"), "Malformed task heading"),
    ],
)
def test_invalid_backlog_syntax_is_rejected(content: str, message: str) -> None:
    with pytest.raises(BacklogValidationError, match=message):
        parse_backlog(content)


def test_missing_dependency_declaration_is_rejected_even_when_root_defaults_to_none() -> None:
    missing = FIXTURE.replace("**Depends on:** TASK-003\n", "")

    with pytest.raises(BacklogValidationError, match="exactly one Depends on"):
        parse_backlog(missing)


def test_task_edits_are_lossless_and_preserve_runner_owned_blocks_and_metadata() -> None:
    updated = FIXTURE.replace("Ready follow-up", "Renamed follow-up").replace(
        "**Scope:** A ready task that can run.",
        "**Scope:** A ready task with preserved surroundings.",
    )

    parsed = validate_backlog_write(FIXTURE, updated)

    assert parsed.content == updated
    assert "# Runner-compatible fixture\n" in parsed.content
    assert parsed.tasks[0].status == "x"
    root_task = _root_helper().get_items(updated)[0]
    assert parsed.tasks[0].block_signature == (
        f"## [{root_task['status']}] {root_task['title']}\n{root_task['body']}"
    )


@pytest.mark.parametrize(
    "updated",
    [
        FIXTURE.replace("## [x] TASK-001", "## [ ] TASK-001"),
        FIXTURE.replace("**Branch:** foundation", "**Branch:** changed"),
        FIXTURE.replace("https://example.invalid/123", "https://example.invalid/456"),
        FIXTURE.replace("## [-] TASK-003", "## [~] TASK-003"),
        FIXTURE.replace("## [ ] TASK-004 — Waiting follow-up", ""),
        FIXTURE + "\n## [ ] TASK-005 — New ready task\n\n**Depends on:** None\n",
    ],
)
def test_outcome_metadata_and_new_task_readiness_cannot_be_synthesized(updated: str) -> None:
    with pytest.raises(BacklogValidationError):
        validate_backlog_write(FIXTURE, updated)


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
@pytest.mark.parametrize(
    "metadata_line",
    [
        "Branch:compact-value",
        "PR:compact-value",
        "**Branch:** bold value",
        "**PR:** bold value",
        "- Branch: list value",
        "* **PR:** list value",
        "    Branch: indented value",
        "\t**PR:** tab-indented value",
    ],
)
def test_new_draft_tasks_cannot_introduce_runner_owned_metadata(
    line_ending: str,
    metadata_line: str,
) -> None:
    previous = f"## [-] TASK-001 — Existing draft{line_ending}**Depends on:** None{line_ending}"
    submitted = (
        previous
        + line_ending
        + f"## [-] TASK-002 — New draft{line_ending}"
        + f"**Depends on:** None{line_ending}"
        + f"{metadata_line}{line_ending}"
    )

    with pytest.raises(BacklogValidationError, match="Branch/PR metadata"):
        validate_backlog_write(previous, submitted)


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_new_draft_task_allows_inline_and_fenced_branch_pr_prose(line_ending: str) -> None:
    previous = f"## [-] TASK-001 — Existing draft{line_ending}**Depends on:** None{line_ending}"
    body = (
        f"**Depends on:** None{line_ending}"
        f"Inline prose mentions Branch: inline and PR: inline.{line_ending}"
        f"`Branch: inline code`{line_ending}"
        f"```text{line_ending}"
        f"Branch: fenced{line_ending}"
        f"PR: fenced{line_ending}"
        f"```{line_ending}"
    )
    submitted = previous + line_ending + f"## [-] TASK-002 — New draft{line_ending}" + body

    parsed = validate_backlog_write(previous, submitted)

    assert parsed.tasks[1].metadata_lines == ()


def test_stale_proposals_may_retain_the_old_planning_snapshot_but_not_new_outcomes() -> None:
    current = FIXTURE.replace("## [ ] TASK-002", "## [x] TASK-002")
    stale_planning_edit = FIXTURE.replace("Waiting follow-up", "Older planning edit")

    with pytest.raises(BacklogValidationError, match="changed after the expected revision"):
        validate_backlog_write(FIXTURE, stale_planning_edit, current_content=current)
