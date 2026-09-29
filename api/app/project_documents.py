"""Private, optimistic-concurrency document drafts and immutable history."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi import Path as PathParameter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.dependencies import CurrentActor, DbSession, SettingsDependency, load_active_actor
from app.document_contract import (
    DOCUMENT_FILENAMES,
    DOCUMENT_KINDS,
    HISTORY_PAGE_SIZE,
    MAX_DOCUMENT_BYTES,
    MAX_REVISION_NUMBER,
    DocumentKind,
)
from app.models import (
    DocumentConflictProposal,
    Project,
    ProjectDocument,
    ProjectDocumentRevision,
    User,
)
from app.project_templates import ProjectTemplate
from app.rate_limit import consume_rate_bucket
from app.workspaces import WorkspaceError, WorkspaceStore

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["project documents"])
logger = logging.getLogger(__name__)


class DocumentWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[
        int,
        Field(strict=True, ge=1, le=MAX_REVISION_NUMBER),
    ]
    content: str

    @field_validator("content")
    @classmethod
    def validate_content_size(cls, content: str) -> str:
        if "\x00" in content:
            raise ValueError("Markdown drafts cannot contain a NUL character.")
        try:
            content_size = len(content.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as exc:
            raise ValueError("Markdown drafts must contain valid UTF-8 text.") from exc
        if content_size > MAX_DOCUMENT_BYTES:
            raise ValueError("Markdown drafts may not exceed 128 KiB.")
        return content


class ProjectDocumentView(BaseModel):
    id: uuid.UUID
    kind: DocumentKind
    filename: str
    revision_number: int
    content: str
    content_sha256: str
    origin: Literal["template", "human"]
    author_user_id: uuid.UUID | None
    created_at: datetime
    template_source: str | None
    template_sha256: str | None


class RevisionSummary(BaseModel):
    revision_number: int
    content_sha256: str
    origin: Literal["template", "human"]
    author_user_id: uuid.UUID | None
    created_at: datetime
    template_source: str | None
    template_sha256: str | None


class DocumentRevisionView(RevisionSummary):
    content: str


class ConflictProposalSummary(BaseModel):
    id: uuid.UUID
    expected_revision_number: int
    observed_revision_number: int
    content_sha256: str
    author_user_id: uuid.UUID
    created_at: datetime


class ConflictProposalView(ConflictProposalSummary):
    content: str


class DocumentHistoryView(BaseModel):
    kind: DocumentKind
    current_revision_number: int
    revisions: list[RevisionSummary]
    proposals: list[ConflictProposalSummary]
    revision_offset: int
    proposal_cursor: uuid.UUID | None
    proposal_next_cursor: uuid.UUID | None
    revision_has_more: bool
    proposal_has_more: bool


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _kind(value: str) -> DocumentKind:
    return cast(DocumentKind, value)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="strict")).hexdigest()


def _revision_summary(revision: ProjectDocumentRevision) -> RevisionSummary:
    return RevisionSummary(
        revision_number=revision.revision_number,
        content_sha256=revision.content_sha256,
        origin=cast(Literal["template", "human"], revision.origin),
        author_user_id=revision.author_user_id,
        created_at=_utc(revision.created_at),
        template_source=revision.template_source,
        template_sha256=revision.template_sha256,
    )


def _proposal_summary(proposal: DocumentConflictProposal) -> ConflictProposalSummary:
    return ConflictProposalSummary(
        id=proposal.id,
        expected_revision_number=proposal.expected_revision_number,
        observed_revision_number=proposal.observed_revision_number,
        content_sha256=proposal.content_sha256,
        author_user_id=proposal.author_user_id,
        created_at=_utc(proposal.created_at),
    )


def _document_view(
    document: ProjectDocument,
    revision: ProjectDocumentRevision,
) -> ProjectDocumentView:
    kind = _kind(document.kind)
    return ProjectDocumentView(
        id=document.id,
        kind=kind,
        filename=DOCUMENT_FILENAMES[kind],
        revision_number=revision.revision_number,
        content=revision.content,
        content_sha256=revision.content_sha256,
        origin=cast(Literal["template", "human"], revision.origin),
        author_user_id=revision.author_user_id,
        created_at=_utc(revision.created_at),
        template_source=revision.template_source,
        template_sha256=revision.template_sha256,
    )


def add_template_documents(
    db: Session,
    project_id: uuid.UUID,
    templates: dict[DocumentKind, ProjectTemplate],
    *,
    created_at: datetime | None = None,
) -> dict[DocumentKind, ProjectDocumentRevision]:
    """Insert missing template heads and their immutable revision-one snapshots."""
    timestamp = created_at or datetime.now(UTC)
    existing = set(
        db.scalars(
            select(ProjectDocument.kind).where(ProjectDocument.project_id == project_id)
        ).all()
    )
    inserted: dict[DocumentKind, ProjectDocumentRevision] = {}
    for kind in DOCUMENT_KINDS:
        if kind in existing:
            continue
        template = templates[kind]
        document = ProjectDocument(
            project_id=project_id,
            kind=kind,
            head_revision_number=1,
            created_at=timestamp,
        )
        db.add(document)
        db.flush()
        revision = ProjectDocumentRevision(
            document_id=document.id,
            revision_number=1,
            content=template.content,
            content_sha256=template.sha256,
            origin="template",
            author_user_id=None,
            template_source=template.source,
            template_sha256=template.sha256,
            created_at=timestamp,
        )
        db.add(revision)
        inserted[kind] = revision
    db.flush()
    return inserted


def seed_legacy_project_documents(
    engine: Engine, templates: dict[DocumentKind, ProjectTemplate]
) -> None:
    """Backfill metadata-only projects without changing their identity or old data."""
    with Session(engine) as db:
        project_ids = list(db.scalars(select(Project.id).order_by(Project.id)).all())

    for project_id in project_ids:
        with Session(engine) as db:
            project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            if project is None:
                db.rollback()
                continue
            add_template_documents(db, project.id, templates)
            db.commit()


def _discard_workspace_cache(store: WorkspaceStore, project_id: uuid.UUID) -> None:
    try:
        store.discard_project(project_id)
    except WorkspaceError:
        logger.warning("The temporary project workspace cache could not be invalidated safely.")


def _mirror_project_documents(
    store: WorkspaceStore,
    project_id: uuid.UUID,
    documents: dict[DocumentKind, str],
) -> None:
    try:
        store.write_project(project_id, documents)
    except WorkspaceError:
        _discard_workspace_cache(store, project_id)
        logger.warning(
            "The project workspace mirror is unavailable; PostgreSQL remains authoritative."
        )


def _locked_project_views(db: Session, project_id: uuid.UUID) -> list[ProjectDocumentView]:
    # All mirror writers use the same ordered PostgreSQL row locks. A read that
    # started before a save can never publish an older cache head after that save.
    documents = list(
        db.scalars(
            select(ProjectDocument)
            .where(ProjectDocument.project_id == project_id)
            .order_by(ProjectDocument.kind)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    views = [
        _document_view(document, _read_revision(db, document, document.head_revision_number))
        for document in documents
    ]
    views.sort(key=lambda item: DOCUMENT_KINDS.index(item.kind))
    if len(views) != len(DOCUMENT_KINDS):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project drafts are not fully initialized.",
        )
    return views


def _mirror_locked_views(
    db: Session, store: WorkspaceStore, project_id: uuid.UUID
) -> list[ProjectDocumentView]:
    views = _locked_project_views(db, project_id)
    _mirror_project_documents(store, project_id, {item.kind: item.content for item in views})
    return views


def _admin_read_audit(
    db: Session,
    actor: User,
    project: Project,
    *,
    action: str,
    details: dict[str, object] | None = None,
) -> None:
    if actor.role == "admin":
        record_audit(
            db,
            action=action,
            actor_user_id=actor.id,
            project_id=project.id,
            details=details,
        )
        db.commit()


def _get_project_and_actor(
    db: Session,
    actor: CurrentActor,
    project_id: uuid.UUID,
) -> tuple[User, Project]:
    active_user = load_active_actor(db, actor)
    project = db.scalar(select(Project).where(Project.id == project_id))
    if project is None or (active_user.role != "admin" and project.owner_user_id != active_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return active_user, project


def _read_revision(
    db: Session,
    document: ProjectDocument,
    revision_number: int,
) -> ProjectDocumentRevision:
    revision = db.scalar(
        select(ProjectDocumentRevision).where(
            ProjectDocumentRevision.document_id == document.id,
            ProjectDocumentRevision.revision_number == revision_number,
        )
    )
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document revision not found"
        )
    return revision


def _load_document(
    db: Session,
    project_id: uuid.UUID,
    kind: DocumentKind,
    *,
    for_update: bool = False,
) -> ProjectDocument:
    statement = select(ProjectDocument).where(
        ProjectDocument.project_id == project_id,
        ProjectDocument.kind == kind,
    )
    if for_update:
        # Serialize head and history reads against writers. Under READ COMMITTED,
        # the later revision/proposal queries then see a head no older than their rows.
        statement = statement.with_for_update().execution_options(populate_existing=True)
    document = db.scalar(statement)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project document not found"
        )
    return document


@router.get("", response_model=list[ProjectDocumentView])
def list_project_documents(
    project_id: uuid.UUID,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
) -> list[ProjectDocumentView]:
    active_user, _project = _get_project_and_actor(db, actor, project_id)
    views = _mirror_locked_views(
        db, cast(WorkspaceStore, request.app.state.workspace_store), project_id
    )
    _admin_read_audit(
        db,
        active_user,
        _project,
        action="admin.project.documents.read",
        details={"document_kinds": list(DOCUMENT_KINDS)},
    )
    db.rollback()  # release read locks (admin audit may have committed already)
    return views


@router.get("/{kind}", response_model=ProjectDocumentView)
def get_project_document(
    project_id: uuid.UUID,
    kind: DocumentKind,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
) -> ProjectDocumentView:
    active_user, project = _get_project_and_actor(db, actor, project_id)
    views = _mirror_locked_views(
        db, cast(WorkspaceStore, request.app.state.workspace_store), project_id
    )
    view = next(item for item in views if item.kind == kind)
    _admin_read_audit(
        db,
        active_user,
        project,
        action="admin.project.document.read",
        details={"kind": kind, "revision_number": view.revision_number},
    )
    db.rollback()
    return view


@router.put("/{kind}", response_model=ProjectDocumentView)
def save_project_document(
    project_id: uuid.UUID,
    kind: DocumentKind,
    payload: DocumentWriteRequest,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    settings: SettingsDependency,
) -> ProjectDocumentView | JSONResponse:
    active_user, project = _get_project_and_actor(db, actor, project_id)
    rate_limit = consume_rate_bucket(
        db,
        settings=settings,
        scope="project-document-write",
        subject=str(active_user.id),
        limit=60,
        window_seconds=60 * 60,
    )
    db.commit()
    if not rate_limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many document saves. Try again later.",
            headers={"Retry-After": str(rate_limit.retry_after_seconds)},
        )
    # The rate-limit commit ended the authentication transaction. Lock and
    # revalidate the actor through the write commit to serialize deactivation.
    active_user = load_active_actor(db, actor, for_update=True)
    document = _load_document(db, project_id, kind, for_update=True)
    observed = _read_revision(db, document, document.head_revision_number)
    if payload.expected_revision != document.head_revision_number:
        proposal = DocumentConflictProposal(
            document_id=document.id,
            expected_revision_number=payload.expected_revision,
            observed_revision_number=document.head_revision_number,
            content=payload.content,
            content_sha256=_sha256(payload.content),
            author_user_id=active_user.id,
            created_at=datetime.now(UTC),
        )
        db.add(proposal)
        db.flush()
        if active_user.role == "admin":
            record_audit(
                db,
                action="admin.project.document.conflict",
                actor_user_id=active_user.id,
                project_id=project.id,
                details={
                    "kind": kind,
                    "expected_revision_number": payload.expected_revision,
                    "observed_revision_number": document.head_revision_number,
                },
            )
        db.commit()
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": (
                    "A newer draft already exists. Your attempted text was saved "
                    "as a conflict proposal."
                ),
                "latest": _document_view(document, observed).model_dump(mode="json"),
                "proposal_id": str(proposal.id),
            },
        )

    if document.head_revision_number >= MAX_REVISION_NUMBER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This draft reached the supported revision limit.",
        )

    revision_number = document.head_revision_number + 1
    revision = ProjectDocumentRevision(
        document_id=document.id,
        revision_number=revision_number,
        content=payload.content,
        content_sha256=_sha256(payload.content),
        origin="human",
        author_user_id=active_user.id,
        template_source=None,
        template_sha256=None,
        created_at=datetime.now(UTC),
    )
    document.head_revision_number = revision_number
    db.add(revision)
    db.flush()

    if active_user.role == "admin":
        record_audit(
            db,
            action="admin.project.document.write",
            actor_user_id=active_user.id,
            project_id=project.id,
            details={"kind": kind, "revision_number": revision_number},
        )
    store = cast(WorkspaceStore, request.app.state.workspace_store)
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        finally:
            # The commit may have reached PostgreSQL despite an error reaching us.
            # Drop the disposable mirror; the next authorized read rebuilds it from
            # whichever revision the database actually committed.
            _discard_workspace_cache(store, project_id)
        raise

    try:
        # Use a new transaction and reread all heads: another writer can commit
        # between our commit and mirror. Never put submitted text over a newer head.
        _mirror_locked_views(db, store, project_id)
    finally:
        db.rollback()
    return _document_view(document, revision)


@router.get("/{kind}/history", response_model=DocumentHistoryView)
def get_project_document_history(
    project_id: uuid.UUID,
    kind: DocumentKind,
    db: DbSession,
    actor: CurrentActor,
    limit: int = Query(default=HISTORY_PAGE_SIZE, ge=1, le=HISTORY_PAGE_SIZE),
    revision_offset: int = Query(default=0, ge=0, le=1_000_000),
    proposal_cursor: Annotated[uuid.UUID | None, Query()] = None,
) -> DocumentHistoryView:
    active_user, project = _get_project_and_actor(db, actor, project_id)
    document = _load_document(db, project_id, kind, for_update=True)
    revision_rows = list(
        db.scalars(
            select(ProjectDocumentRevision)
            .where(ProjectDocumentRevision.document_id == document.id)
            .order_by(ProjectDocumentRevision.revision_number.desc())
            .offset(revision_offset)
            .limit(limit + 1)
        ).all()
    )
    proposal_statement = select(DocumentConflictProposal).where(
        DocumentConflictProposal.document_id == document.id
    )
    if proposal_cursor is not None:
        cursor_row = db.scalar(
            select(DocumentConflictProposal).where(
                DocumentConflictProposal.id == proposal_cursor,
                DocumentConflictProposal.document_id == document.id,
            )
        )
        if cursor_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conflict proposal cursor not found",
            )
        # Offset pages shift when another stale writer adds a proposal. Continue
        # after an immutable row's total ordering instead, so earlier rows cannot
        # move across the page boundary. A fresh request without a cursor starts
        # at the newest proposal and can see concurrent inserts.
        proposal_statement = proposal_statement.where(
            or_(
                DocumentConflictProposal.created_at < cursor_row.created_at,
                and_(
                    DocumentConflictProposal.created_at == cursor_row.created_at,
                    DocumentConflictProposal.id > cursor_row.id,
                ),
            )
        )
    proposal_rows = list(
        db.scalars(
            proposal_statement.order_by(
                DocumentConflictProposal.created_at.desc(),
                DocumentConflictProposal.id.asc(),
            ).limit(limit + 1)
        ).all()
    )
    proposal_page = proposal_rows[:limit]
    proposal_has_more = len(proposal_rows) > limit
    _admin_read_audit(
        db,
        active_user,
        project,
        action="admin.project.document_history.read",
        details={"kind": kind},
    )
    return DocumentHistoryView(
        kind=kind,
        current_revision_number=document.head_revision_number,
        revisions=[_revision_summary(item) for item in revision_rows[:limit]],
        proposals=[_proposal_summary(item) for item in proposal_page],
        revision_offset=revision_offset,
        proposal_cursor=proposal_cursor,
        proposal_next_cursor=proposal_page[-1].id if proposal_has_more else None,
        revision_has_more=len(revision_rows) > limit,
        proposal_has_more=proposal_has_more,
    )


@router.get("/{kind}/revisions/{revision_number}", response_model=DocumentRevisionView)
def get_project_document_revision(
    project_id: uuid.UUID,
    kind: DocumentKind,
    revision_number: Annotated[
        int,
        PathParameter(ge=1, le=MAX_REVISION_NUMBER),
    ],
    db: DbSession,
    actor: CurrentActor,
) -> DocumentRevisionView:
    active_user, project = _get_project_and_actor(db, actor, project_id)
    document = _load_document(db, project_id, kind)
    revision = _read_revision(db, document, revision_number)
    _admin_read_audit(
        db,
        active_user,
        project,
        action="admin.project.document_revision.read",
        details={"kind": kind, "revision_number": revision_number},
    )
    return DocumentRevisionView(
        **_revision_summary(revision).model_dump(), content=revision.content
    )


@router.get("/{kind}/proposals/{proposal_id}", response_model=ConflictProposalView)
def get_project_document_proposal(
    project_id: uuid.UUID,
    kind: DocumentKind,
    proposal_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
) -> ConflictProposalView:
    active_user, project = _get_project_and_actor(db, actor, project_id)
    document = _load_document(db, project_id, kind)
    proposal = db.scalar(
        select(DocumentConflictProposal).where(
            DocumentConflictProposal.id == proposal_id,
            DocumentConflictProposal.document_id == document.id,
        )
    )
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conflict proposal not found",
        )
    _admin_read_audit(
        db,
        active_user,
        project,
        action="admin.project.document_proposal.read",
        details={"kind": kind, "proposal_id": str(proposal.id)},
    )
    return ConflictProposalView(
        **_proposal_summary(proposal).model_dump(), content=proposal.content
    )
