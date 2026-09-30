"""Lossless task spans and validation for runner-compatible BACKLOG.md drafts."""

from __future__ import annotations

import re
from bisect import bisect_left
from collections import deque
from dataclasses import dataclass
from typing import Literal, cast

TaskStatus = Literal["-", " ", "~", "x", "!"]
PLANNING_STATUSES = frozenset({"-", " "})
EXECUTION_STATUSES = frozenset({"~", "x", "!"})

# Keep these syntax rules aligned with scripts/backlog.py. The API deliberately
# applies additional identity, required-dependency, and cycle checks.
_ROOT_STATUS_PATTERN = re.compile(r"^## \[([ ~x!\-])\] (.+)$")
_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*-\d+$")
_CANONICAL_HEADING_PATTERN = re.compile(r"^## \[([ ~x!\-])\] ([A-Za-z][A-Za-z0-9_-]*-\d+) — (.+)$")
_DEPENDENCY_PATTERN = re.compile(r"^\s*(?:\*\*)?Depends on:(?:\*\*)?\s*(.*?)\s*$")
_FENCE_OPEN_PATTERN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_NON_TASK_H2_PATTERN = re.compile(r"^ {0,3}##(?:[ \t]|$)")
_BRANCH_PR_PATTERN = re.compile(
    r"^[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+)?(?:\*\*)?(?:Branch|PR):(?:\*\*)?[ \t]*.*$",
    re.IGNORECASE,
)
_HORIZONTAL_RULE_PATTERN = re.compile(r"^ {0,3}(?:-{3,}|\*{3,}|_{3,})[ \t]*$")


class BacklogValidationError(ValueError):
    """The backlog cannot be safely understood or written by the planning API."""


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    end: int
    text_end: int
    text: str
    in_fence: bool


@dataclass(frozen=True, slots=True)
class BacklogTask:
    """A parsed task plus source spans for lossless editing."""

    id: str
    status: TaskStatus
    title: str
    dependencies: tuple[str, ...]
    body: str
    acceptance: str | None
    verification: str | None
    ready: bool
    eligible: bool
    waiting_on: tuple[str, ...]
    header_start: int
    header_text_end: int
    header_end: int
    body_start: int
    body_end: int
    raw_end: int
    dependency_value_start: int
    dependency_value_end: int
    metadata_lines: tuple[str, ...]
    block_signature: str


@dataclass(frozen=True, slots=True)
class BacklogSummary:
    draft_count: int
    ready_count: int
    eligible_count: int
    waiting_count: int


@dataclass(frozen=True, slots=True)
class ParsedBacklog:
    content: str
    tasks: tuple[BacklogTask, ...]
    summary: BacklogSummary


@dataclass(frozen=True, slots=True)
class _TaskHeading:
    id: str
    status: TaskStatus
    title: str
    line: _Line


@dataclass(frozen=True, slots=True)
class _DependencyDeclaration:
    dependencies: tuple[str, ...]
    value_start: int
    value_end: int


def validate_task_id(task_id: str) -> str:
    """Validate the permanent ID grammar used by the root runner helper."""
    if not _ID_PATTERN.fullmatch(task_id):
        raise BacklogValidationError(
            "Task IDs must start with a letter and end in a hyphenated number."
        )
    return task_id


def _read_lines(content: str) -> list[_Line]:
    lines: list[_Line] = []
    offset = 0
    fence: tuple[str, int] | None = None
    for raw_line in content.splitlines(keepends=True):
        text = raw_line.rstrip("\r\n")
        inside_fence = fence is not None
        if fence is not None:
            marker, minimum_length = fence
            closing = re.fullmatch(
                r" {0,3}" + re.escape(marker) + "{" + str(minimum_length) + r",}\s*",
                text,
            )
            if closing:
                fence = None
                inside_fence = False
        else:
            opening = _FENCE_OPEN_PATTERN.match(text)
            if opening:
                fence = (opening.group(1)[0], len(opening.group(1)))
                inside_fence = True

        text_end = offset + len(text)
        end = offset + len(raw_line)
        lines.append(_Line(offset, end, text_end, text, inside_fence))
        offset = end
    return lines


def has_unclosed_fence(content: str) -> bool:
    """Return whether the document ends inside a fenced example."""
    lines = _read_lines(content)
    return bool(lines and lines[-1].in_fence)


def _task_body_end(
    lines: list[_Line],
    line_starts: list[int],
    body_start: int,
    raw_end: int,
) -> int:
    first_line = bisect_left(line_starts, body_start)
    end_line = bisect_left(line_starts, raw_end)
    task_end = raw_end
    for line in lines[first_line:end_line]:
        if not line.in_fence and _NON_TASK_H2_PATTERN.match(line.text):
            task_end = line.start
            break

    end_line = bisect_left(line_starts, task_end)
    interval = lines[first_line:end_line]
    nonblank = [line for line in interval if line.text.strip()]
    if not nonblank:
        return task_end

    last = nonblank[-1]
    if last.in_fence or not _HORIZONTAL_RULE_PATTERN.fullmatch(last.text):
        return task_end

    previous = nonblank[-2] if len(nonblank) > 1 else None
    # A trailing horizontal rule separates task blocks. Its preceding line ending
    # and blank separator lines belong to the separator, not to the task body.
    return previous.text_end if previous is not None else body_start


def _section_content(body: str, names: frozenset[str]) -> str | None:
    lines = body.splitlines(keepends=True)
    headings: list[tuple[int, int, int, str]] = []
    offset = 0
    fence: tuple[str, int] | None = None
    for raw_line in lines:
        text = raw_line.rstrip("\r\n")
        if fence is not None:
            marker, minimum_length = fence
            if re.fullmatch(
                r" {0,3}" + re.escape(marker) + "{" + str(minimum_length) + r",}\s*",
                text,
            ):
                fence = None
        else:
            opening = _FENCE_OPEN_PATTERN.match(text)
            if opening:
                fence = (opening.group(1)[0], len(opening.group(1)))
            else:
                match = re.match(r"^( {0,3})(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", text)
                if match:
                    headings.append(
                        (
                            offset,
                            offset + len(raw_line),
                            len(match.group(2)),
                            match.group(3).strip(),
                        )
                    )
        offset += len(raw_line)

    selected_index: int | None = None
    selected_level: int | None = None
    value_start: int | None = None
    for index, (_start, end, level, title) in enumerate(headings):
        if title.casefold() in names:
            selected_index = index
            selected_level = level
            value_start = end
            break
    if selected_index is None or selected_level is None or value_start is None:
        return None

    value_end = len(body)
    for next_start, _next_end, next_level, _ in headings[selected_index + 1 :]:
        if next_level <= selected_level:
            value_end = next_start
            break
    return body[value_start:value_end].strip()


def _metadata_lines(
    lines: list[_Line],
    line_starts: list[int],
    body_start: int,
    body_end: int,
) -> tuple[str, ...]:
    first_line = bisect_left(line_starts, body_start)
    end_line = bisect_left(line_starts, body_end)
    return tuple(
        line.text.rstrip("\r\n")
        for line in lines[first_line:end_line]
        if not line.in_fence and _BRANCH_PR_PATTERN.fullmatch(line.text)
    )


def _dependency_declaration(body: str, task_id: str) -> _DependencyDeclaration:
    # The root helper searches the whole body, including fenced code. Match one
    # physical line at a time to retain that observable fence behavior without
    # allowing its leading ``\s*`` to backtrack across a large blank body.
    declarations = [
        (line, match)
        for line in _read_lines(body)
        if (match := _DEPENDENCY_PATTERN.fullmatch(line.text)) is not None
    ]
    if len(declarations) != 1:
        raise BacklogValidationError(
            f"Task {task_id} must contain exactly one Depends on declaration."
        )

    line, match = declarations[0]
    value = match.group(1).strip()
    if not value:
        raise BacklogValidationError(f"Task {task_id} has an empty Depends on declaration.")
    if value.casefold() == "none":
        dependencies: tuple[str, ...] = ()
    else:
        dependencies = tuple(part.strip() for part in value.split(","))
        if any(not dependency for dependency in dependencies):
            raise BacklogValidationError(f"Task {task_id} has an invalid dependency list.")
        if any(not _ID_PATTERN.fullmatch(dependency) for dependency in dependencies):
            raise BacklogValidationError(f"Task {task_id} has an invalid dependency ID.")

    return _DependencyDeclaration(
        dependencies=dependencies,
        value_start=line.start + match.start(1),
        value_end=line.start + match.end(1),
    )


def _root_block_signature(content: str, heading: _TaskHeading, raw_end: int) -> str:
    """Match the root helper's status/title and stripped task-body view."""
    header = content[heading.line.start : heading.line.text_end].strip()
    body = content[heading.line.text_end : raw_end].strip()
    return f"{header}\n{body}"


def replace_task_dependency_value(
    content: str,
    task_id: str,
    dependencies: tuple[str, ...],
) -> str:
    """Replace only one task's dependency value, retaining its Markdown framing."""
    declaration = _dependency_declaration(content, task_id)
    if any(not _ID_PATTERN.fullmatch(dependency) for dependency in dependencies):
        raise BacklogValidationError(f"Task {task_id} has an invalid dependency ID.")
    value = "None" if not dependencies else ", ".join(dependencies)
    return content[: declaration.value_start] + value + content[declaration.value_end :]


def parse_backlog(content: str) -> ParsedBacklog:
    """Validate runner syntax while retaining exact source offsets and task text."""
    lines = _read_lines(content)
    line_starts = [line.start for line in lines]
    headings: list[_TaskHeading] = []
    for line_number, line in enumerate(lines, start=1):
        if line.in_fence:
            continue
        if _ROOT_STATUS_PATTERN.fullmatch(line.text):
            match = _CANONICAL_HEADING_PATTERN.fullmatch(line.text)
            if match is None:
                raise BacklogValidationError(f"Malformed task heading on line {line_number}.")
            task_id = match.group(2)
            task_status = cast(TaskStatus, match.group(1))
            title = match.group(3)
            if not title.strip():
                raise BacklogValidationError(f"Task {task_id} must have a non-empty title.")
            headings.append(_TaskHeading(task_id, task_status, title.strip(), line))
        elif line.text.startswith("## ["):
            raise BacklogValidationError(f"Malformed task heading on line {line_number}.")

    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    pending: list[
        tuple[_TaskHeading, int, int, int, str, _DependencyDeclaration, tuple[str, ...]]
    ] = []
    for index, heading in enumerate(headings):
        id_key = heading.id.casefold()
        title_key = heading.title.casefold()
        if id_key in seen_ids:
            raise BacklogValidationError(f"Duplicate task ID: {heading.id}.")
        if title_key in seen_titles:
            raise BacklogValidationError(f"Duplicate task title: {heading.title}.")
        seen_ids.add(id_key)
        seen_titles.add(title_key)

        raw_end = headings[index + 1].line.start if index + 1 < len(headings) else len(content)
        body_start = heading.line.end
        body_end = _task_body_end(lines, line_starts, body_start, raw_end)
        body = content[body_start:body_end]
        # The editor owns only body_start:body_end, but the root helper owns the
        # entire interval through raw_end. Validate dependencies and protected
        # metadata over that full interval without giving task PUTs edit access
        # to intervening level-two notes.
        declaration = _dependency_declaration(content[body_start:raw_end], heading.id)
        metadata = _metadata_lines(lines, line_starts, body_start, raw_end)
        pending.append(
            (
                heading,
                raw_end,
                body_start,
                body_end,
                body,
                declaration,
                metadata,
            )
        )

    by_id = {heading.id.casefold(): heading for heading in headings}
    dependency_keys: dict[str, tuple[str, ...]] = {}
    for heading, _raw_end, _body_start, _body_end, _body, declaration, _metadata in pending:
        dependency_ids: list[str] = []
        for dependency in declaration.dependencies:
            key = dependency.casefold()
            if key == heading.id.casefold():
                raise BacklogValidationError(f"Task {heading.id} cannot depend on itself.")
            if key not in by_id:
                raise BacklogValidationError(
                    f"Task {heading.id} has an unknown dependency: {dependency}."
                )
            dependency_ids.append(key)
        dependency_keys[heading.id.casefold()] = tuple(dependency_ids)

    dependents: dict[str, list[str]] = {task_key: [] for task_key in dependency_keys}
    remaining_dependencies: dict[str, int] = {}
    for task_key, dependencies in dependency_keys.items():
        remaining_dependencies[task_key] = len(dependencies)
        for dependency_key in dependencies:
            dependents[dependency_key].append(task_key)
    dependency_free = deque(
        task_key for task_key, remaining in remaining_dependencies.items() if remaining == 0
    )
    visited = 0
    while dependency_free:
        task_key = dependency_free.popleft()
        visited += 1
        for dependent in dependents[task_key]:
            remaining_dependencies[dependent] -= 1
            if remaining_dependencies[dependent] == 0:
                dependency_free.append(dependent)
    if visited != len(dependency_keys):
        cycle_key = next(
            task_key for task_key, remaining in remaining_dependencies.items() if remaining > 0
        )
        raise BacklogValidationError(f"Dependency cycle includes task {by_id[cycle_key].id}.")

    tasks: list[BacklogTask] = []
    for heading, raw_end, body_start, body_end, body, declaration, metadata in pending:
        waiting_on = tuple(
            dependency
            for dependency in declaration.dependencies
            if by_id[dependency.casefold()].status != "x"
        )
        ready = heading.status == " "
        tasks.append(
            BacklogTask(
                id=heading.id,
                status=heading.status,
                title=heading.title,
                dependencies=declaration.dependencies,
                body=body,
                acceptance=_section_content(body, frozenset({"done looks like", "acceptance"})),
                verification=_section_content(body, frozenset({"verification"})),
                ready=ready,
                eligible=ready and not waiting_on,
                waiting_on=waiting_on,
                header_start=heading.line.start,
                header_text_end=heading.line.text_end,
                header_end=heading.line.end,
                body_start=body_start,
                body_end=body_end,
                raw_end=raw_end,
                dependency_value_start=body_start + declaration.value_start,
                dependency_value_end=body_start + declaration.value_end,
                metadata_lines=metadata,
                block_signature=_root_block_signature(content, heading, raw_end),
            )
        )

    summary = BacklogSummary(
        draft_count=sum(task.status == "-" for task in tasks),
        ready_count=sum(task.ready for task in tasks),
        eligible_count=sum(task.eligible for task in tasks),
        waiting_count=sum(task.ready and not task.eligible for task in tasks),
    )
    return ParsedBacklog(content=content, tasks=tuple(tasks), summary=summary)


def validate_task_edit_assembly(
    original_content: str,
    assembled_content: str,
    task: BacklogTask,
    *,
    suffix_start: int,
    suffix_replacement: tuple[int, int, int] | None = None,
) -> ParsedBacklog:
    """Parse a task edit and ensure its untouched level-two notes stay separate.

    ``suffix_start`` is the output offset where ``original_content[task.body_end:]``
    was reattached. When that suffix contains one edited value, ``suffix_replacement``
    is its original ``(start, end, replacement_length)`` span.
    """
    assembled = parse_backlog(assembled_content)
    assembled_lines = {line.start: line for line in _read_lines(assembled_content)}
    replacement_delta = 0
    replacement_start: int | None = None
    replacement_end: int | None = None
    if suffix_replacement is not None:
        replacement_start, replacement_end, replacement_length = suffix_replacement
        replacement_delta = replacement_length - (replacement_end - replacement_start)

    for line in _read_lines(original_content):
        if line.start < task.body_end:
            continue
        if line.start >= task.raw_end:
            break
        if line.in_fence or not _NON_TASK_H2_PATTERN.match(line.text):
            continue

        output_start = suffix_start + line.start - task.body_end
        if replacement_start is not None and replacement_end is not None:
            if replacement_start <= line.start < replacement_end:
                raise BacklogValidationError(
                    f"Task {task.id} edit cannot replace a preserved level-two heading."
                )
            if line.start >= replacement_end:
                output_start += replacement_delta

        output_line = assembled_lines.get(output_start)
        if (
            output_line is None
            or output_line.in_fence
            or not _NON_TASK_H2_PATTERN.match(output_line.text)
            or output_line.text != line.text
        ):
            raise BacklogValidationError(
                f"Task {task.id} edit would merge or hide a preserved level-two section."
            )

    return assembled


def validate_backlog_write(
    previous_content: str,
    submitted_content: str,
    *,
    current_content: str | None = None,
) -> ParsedBacklog:
    """Validate a backlog edit and keep existing identity/outcome metadata intact."""
    previous = parse_backlog(previous_content)
    submitted = parse_backlog(submitted_content)
    current = parse_backlog(current_content) if current_content is not None else previous

    _validate_task_transitions(previous, submitted)
    _validate_current_execution_tasks(previous, current, submitted)
    return submitted


def _tasks_by_id(backlog: ParsedBacklog) -> dict[str, BacklogTask]:
    return {task.id.casefold(): task for task in backlog.tasks}


def _validate_task_transitions(
    previous: ParsedBacklog,
    submitted: ParsedBacklog,
) -> None:
    previous_tasks = _tasks_by_id(previous)
    submitted_tasks = _tasks_by_id(submitted)

    for task_key, previous_task in previous_tasks.items():
        submitted_task = submitted_tasks.get(task_key)
        if submitted_task is None:
            raise BacklogValidationError(f"Task {previous_task.id} cannot be deleted or renamed.")
        if submitted_task.id != previous_task.id:
            raise BacklogValidationError(f"Task ID casing cannot be changed: {previous_task.id}.")
        if previous_task.metadata_lines != submitted_task.metadata_lines:
            raise BacklogValidationError(
                f"Branch/PR metadata for task {previous_task.id} must be preserved."
            )

        if previous_task.status in EXECUTION_STATUSES:
            if (
                submitted_task.status != previous_task.status
                or submitted_task.block_signature != previous_task.block_signature
            ):
                raise BacklogValidationError(f"Execution task {previous_task.id} is read-only.")
        elif submitted_task.status not in PLANNING_STATUSES:
            raise BacklogValidationError(
                f"Task {previous_task.id} may only move between draft and ready."
            )

    for task_key, submitted_task in submitted_tasks.items():
        if task_key not in previous_tasks:
            if submitted_task.status != "-":
                raise BacklogValidationError(f"New task {submitted_task.id} must start as a draft.")
            if submitted_task.metadata_lines:
                raise BacklogValidationError(
                    f"New task {submitted_task.id} cannot introduce "
                    "runner-owned Branch/PR metadata."
                )


def _validate_current_execution_tasks(
    previous: ParsedBacklog,
    current: ParsedBacklog,
    submitted: ParsedBacklog,
) -> None:
    """Do not let a stale planning snapshot change a newer runner outcome."""
    previous_tasks = _tasks_by_id(previous)
    current_tasks = _tasks_by_id(current)
    submitted_tasks = _tasks_by_id(submitted)

    for task_key, current_task in current_tasks.items():
        previous_task = previous_tasks.get(task_key)
        if previous_task is None:
            # The stale snapshot did not know about this task; its save will be a
            # proposal, not a document-head replacement.
            continue
        submitted_task = submitted_tasks.get(task_key)
        if submitted_task is None:
            # _validate_task_transitions already rejects deletion of a task that
            # existed in the client's expected revision.
            continue
        if current_task.status in EXECUTION_STATUSES and (
            submitted_task.status != current_task.status
            or submitted_task.block_signature != current_task.block_signature
        ):
            raise BacklogValidationError(
                f"Execution task {current_task.id} changed after the expected revision."
            )
