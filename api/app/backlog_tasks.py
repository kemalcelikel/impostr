"""Project-authorized backlog task views and optimistic task edits."""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi import Path as PathParameter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backlog_markdown import (
    EXECUTION_STATUSES,
    BacklogTask,
    BacklogValidationError,
    ParsedBacklog,
    has_unclosed_fence,
    parse_backlog,
    replace_task_dependency_value,
    validate_task_edit_assembly,
    validate_task_id,
)
from app.dependencies import CurrentActor, DbSession, SettingsDependency
from app.document_contract import MAX_DOCUMENT_BYTES, MAX_REVISION_NUMBER
from app.models import ProjectDocument, ProjectDocumentRevision
from app.project_documents import (
    DocumentWriteRequest,
    _admin_read_audit,
    _get_project_and_actor,
    _load_document,
    _read_revision,
    save_project_document,
)

router = APIRouter(prefix="/projects/{project_id}/backlog/tasks", tags=["backlog tasks"])
_TITLE_WITH_ID_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*-\d+\s+—\s+")


class BacklogTaskSummaryView(BaseModel):
    draft_count: int
    ready_count: int
    eligible_count: int
    waiting_count: int


class BacklogTaskView(BaseModel):
    id: str
    status: str
    title: str
    dependencies: list[str]
    body: str
    acceptance: str | None
    verification: str | None
    ready: bool
    eligible: bool
    waiting_on: list[str]


class BacklogTaskDocumentView(BaseModel):
    revision_number: int
    content_sha256: str
    content: str
    tasks: list[BacklogTaskView]
    summary: BacklogTaskSummaryView


class _TaskWriteFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[
        int,
        Field(strict=True, ge=1, le=MAX_REVISION_NUMBER),
    ]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    body: Annotated[str, Field(max_length=MAX_DOCUMENT_BYTES)]

    @field_validator("title")
    @classmethod
    def validate_title(cls, title: str) -> str:
        normalized = title.strip()
        if not normalized or len(normalized.splitlines()) != 1:
            raise ValueError("Task titles must be one non-empty line.")
        if _TITLE_WITH_ID_PREFIX.match(normalized):
            raise ValueError("Task titles must not repeat the task ID.")
        return normalized

    @field_validator("body")
    @classmethod
    def validate_body(cls, body: str) -> str:
        if "\x00" in body:
            raise ValueError("Task Markdown cannot contain a NUL character.")
        try:
            body_size = len(body.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as exc:
            raise ValueError("Task Markdown must contain valid UTF-8 text.") from exc
        if body_size > MAX_DOCUMENT_BYTES:
            raise ValueError("Task Markdown may not exceed 128 KiB.")
        return body


class BacklogTaskDraftRequest(_TaskWriteFields):
    id: Annotated[str, Field(min_length=1, max_length=MAX_DOCUMENT_BYTES)]

    @field_validator("id")
    @classmethod
    def validate_id(cls, task_id: str) -> str:
        try:
            return validate_task_id(task_id)
        except BacklogValidationError as exc:
            raise ValueError(str(exc)) from exc


class BacklogTaskUpdateRequest(_TaskWriteFields):
    status: Literal["-", " "]
    dependencies: Annotated[
        list[str] | None,
        Field(max_length=MAX_DOCUMENT_BYTES // 5 + 1),
    ] = None

    @field_validator("dependencies")
    @classmethod
    def validate_dependencies(cls, dependencies: list[str] | None) -> list[str] | None:
        if dependencies is None:
            return None
        normalized: list[str] = []
        encoded_size = 0
        for index, dependency in enumerate(dependencies):
            if len(dependency) > MAX_DOCUMENT_BYTES:
                raise ValueError("Task dependency IDs may not exceed the document size limit.")
            candidate = dependency.strip()
            try:
                normalized.append(validate_task_id(candidate))
            except BacklogValidationError as exc:
                raise ValueError(str(exc)) from exc
            encoded_size += len(candidate) + (2 if index else 0)
            if encoded_size > MAX_DOCUMENT_BYTES:
                raise ValueError("Task dependencies may not exceed the document size limit.")
        return normalized


def _document_view(
    revision_number: int,
    content: str,
    content_sha256: str,
    parsed: ParsedBacklog,
) -> BacklogTaskDocumentView:
    return BacklogTaskDocumentView(
        revision_number=revision_number,
        content_sha256=content_sha256,
        content=content,
        tasks=[
            BacklogTaskView(
                id=task.id,
                status=task.status,
                title=task.title,
                dependencies=list(task.dependencies),
                body=task.body,
                acceptance=task.acceptance,
                verification=task.verification,
                ready=task.ready,
                eligible=task.eligible,
                waiting_on=list(task.waiting_on),
            )
            for task in parsed.tasks
        ],
        summary=BacklogTaskSummaryView(
            draft_count=parsed.summary.draft_count,
            ready_count=parsed.summary.ready_count,
            eligible_count=parsed.summary.eligible_count,
            waiting_count=parsed.summary.waiting_count,
        ),
    )


def _parse_or_422(content: str) -> ParsedBacklog:
    try:
        return parse_backlog(content)
    except BacklogValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _expected_revision_content(
    db: Session,
    document: ProjectDocument,
    expected_revision: int,
) -> ProjectDocumentRevision:
    expected = db.scalar(
        select(ProjectDocumentRevision).where(
            ProjectDocumentRevision.document_id == document.id,
            ProjectDocumentRevision.revision_number == expected_revision,
        )
    )
    if expected is not None:
        return expected
    # A future expected number has no immutable base. Build a safe proposal from
    # the current head; the shared document writer will still return a 409.
    return _read_revision(db, document, document.head_revision_number)


def _document_write_request(expected_revision: int, content: str) -> DocumentWriteRequest:
    try:
        return DocumentWriteRequest(expected_revision=expected_revision, content=content)
    except ValidationError as exc:
        # Do not echo full Markdown, which may include sensitive project planning.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The edited backlog exceeds the supported size or contains invalid text.",
        ) from exc


def _save_task_change(
    *,
    project_id: uuid.UUID,
    request: Request,
    db: Session,
    actor: CurrentActor,
    settings: SettingsDependency,
    expected_revision: int,
    content: str,
) -> BacklogTaskDocumentView | JSONResponse:
    saved = save_project_document(
        project_id,
        "backlog",
        _document_write_request(expected_revision, content),
        request,
        db,
        actor,
        settings,
    )
    if isinstance(saved, JSONResponse):
        return saved
    parsed = _parse_or_422(saved.content)
    return _document_view(
        saved.revision_number,
        saved.content,
        saved.content_sha256,
        parsed,
    )


def _find_task(parsed: ParsedBacklog, task_id: str) -> BacklogTask | None:
    key = task_id.casefold()
    return next((task for task in parsed.tasks if task.id.casefold() == key), None)


def _preferred_line_ending(content: str) -> str:
    for line in content.splitlines(keepends=True):
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
        if line.endswith("\r"):
            return "\r"
    return "\n"


def _append_draft(
    content: str,
    *,
    task_id: str,
    title: str,
    body: str,
) -> str:
    if has_unclosed_fence(content):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Close the fenced code block before adding a task.",
        )

    line_ending = _preferred_line_ending(content)
    if content:
        separator_prefix = line_ending if content.endswith(("\r", "\n")) else line_ending * 2
        # The root helper includes non-whitespace separators in the preceding
        # task's body. A horizontal rule here would therefore rewrite a final
        # runner-owned task merely by appending a new draft.
        section_prefix = separator_prefix
    else:
        section_prefix = ""
    if body and not body.startswith(("\r", "\n")):
        body = line_ending * 2 + body
    return content + section_prefix + f"## [-] {task_id} — {title}{line_ending}" + body


@router.get("", response_model=BacklogTaskDocumentView)
def get_backlog_tasks(
    project_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
) -> BacklogTaskDocumentView:
    active_user, project = _get_project_and_actor(db, actor, project_id)
    document = _load_document(db, project_id, "backlog", for_update=True)
    revision = _read_revision(db, document, document.head_revision_number)
    parsed = _parse_or_422(revision.content)
    _admin_read_audit(
        db,
        active_user,
        project,
        action="admin.project.backlog_tasks.read",
        details={"revision_number": revision.revision_number, "task_count": len(parsed.tasks)},
    )
    db.rollback()
    return _document_view(
        revision.revision_number,
        revision.content,
        revision.content_sha256,
        parsed,
    )


@router.post("", response_model=BacklogTaskDocumentView, status_code=status.HTTP_201_CREATED)
def create_backlog_task(
    project_id: uuid.UUID,
    payload: BacklogTaskDraftRequest,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    settings: SettingsDependency,
) -> BacklogTaskDocumentView | JSONResponse:
    _get_project_and_actor(db, actor, project_id)
    document = _load_document(db, project_id, "backlog")
    base_revision = _expected_revision_content(db, document, payload.expected_revision)
    parsed = _parse_or_422(base_revision.content)
    if _find_task(parsed, payload.id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task ID already exists.")

    content = _append_draft(
        base_revision.content,
        task_id=payload.id,
        title=payload.title,
        body=payload.body,
    )
    return _save_task_change(
        project_id=project_id,
        request=request,
        db=db,
        actor=actor,
        settings=settings,
        expected_revision=payload.expected_revision,
        content=content,
    )


@router.put("/{task_id}", response_model=BacklogTaskDocumentView)
def update_backlog_task(
    project_id: uuid.UUID,
    task_id: Annotated[str, PathParameter(min_length=1, max_length=MAX_DOCUMENT_BYTES)],
    payload: BacklogTaskUpdateRequest,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    settings: SettingsDependency,
) -> BacklogTaskDocumentView | JSONResponse:
    _get_project_and_actor(db, actor, project_id)
    document = _load_document(db, project_id, "backlog")
    base_revision = _expected_revision_content(db, document, payload.expected_revision)
    parsed = _parse_or_422(base_revision.content)
    task = _find_task(parsed, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if task.status in EXECUTION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Runner execution tasks are read-only.",
        )

    source = base_revision.content
    line_ending = source[task.header_text_end : task.header_end]
    if not line_ending and payload.body and not payload.body.startswith(("\r", "\n")):
        # Imported Markdown can use a Unicode line separator that splitlines()
        # recognizes but the preserved CR/LF slice above does not.
        line_ending = _preferred_line_ending(source)
    new_header = f"## [{payload.status}] {task.id} — {payload.title}{line_ending}"
    new_body = payload.body
    external_dependency_value: str | None = None
    if "dependencies" in payload.model_fields_set:
        if payload.dependencies is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Task dependencies must be a list when provided.",
            )
        if task.dependency_value_start < task.body_end:
            try:
                new_body = replace_task_dependency_value(
                    new_body,
                    task.id,
                    tuple(payload.dependencies),
                )
            except BacklogValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
        else:
            external_dependency_value = (
                "None" if not payload.dependencies else ", ".join(payload.dependencies)
            )

    preserved_suffix = source[task.body_end :]
    suffix_replacement: tuple[int, int, int] | None = None
    if external_dependency_value is not None:
        suffix_value_start = task.dependency_value_start - task.body_end
        suffix_value_end = task.dependency_value_end - task.body_end
        preserved_suffix = (
            preserved_suffix[:suffix_value_start]
            + external_dependency_value
            + preserved_suffix[suffix_value_end:]
        )
        suffix_replacement = (
            task.dependency_value_start,
            task.dependency_value_end,
            len(external_dependency_value),
        )
    content_prefix = source[: task.header_start] + new_header + new_body
    content = content_prefix + preserved_suffix
    try:
        validate_task_edit_assembly(
            source,
            content,
            task,
            suffix_start=len(content_prefix),
            suffix_replacement=suffix_replacement,
        )
    except BacklogValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return _save_task_change(
        project_id=project_id,
        request=request,
        db=db,
        actor=actor,
        settings=settings,
        expected_revision=payload.expected_revision,
        content=content,
    )
