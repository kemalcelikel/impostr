"""Short durable chat transactions. No inference or channel I/O under DB locks."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.backlog_markdown import BacklogValidationError, parse_backlog, validate_backlog_write
from app.chat_protocol import MAX_EVENTS, MAX_PRIOR_TURNS, digest, require
from app.chat_references import capture_references, resolve_context
from app.dependencies import AuthenticatedActor, load_active_actor
from app.document_contract import DOCUMENT_FILENAMES, MAX_REVISION_NUMBER, DocumentKind
from app.models import (
    AgentDocumentProposal,
    ChatEvent,
    ChatInteraction,
    ChatTurn,
    Conversation,
    DocumentConflictProposal,
    Project,
    ProjectDocument,
    ProjectDocumentRevision,
    ProjectTurnReservation,
    User,
    WebSession,
)
from app.project_documents import _read_revision

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def authorize(
    db: Session, actor: AuthenticatedActor, project_id: uuid.UUID, *, lock: bool = False
) -> User:
    user = load_active_actor(db, actor, for_update=lock)
    # Serialize logout/password-reset too, not just account deactivation.
    statement = select(WebSession).where(WebSession.token_hash == actor.session_token_hash)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    session = db.scalar(statement)
    if (
        session is None
        or session.revoked_at is not None
        or utc(session.expires_at) <= datetime.now(UTC)
    ):
        raise HTTPException(401, "Authentication required")
    statement_project = select(Project).where(Project.id == project_id)
    if lock:
        statement_project = statement_project.with_for_update().execution_options(
            populate_existing=True
        )
    project = db.scalar(statement_project)
    if project is None or (user.role != "admin" and project.owner_user_id != user.id):
        raise HTTPException(404, "Project not found")
    return user


def conversation(db: Session, project_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
    value = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.project_id == project_id
        )
    )
    if value is None:
        raise HTTPException(404, "Conversation not found")
    return value


def event(db: Session, turn: ChatTurn, kind: str, data: dict[str, Any]) -> ChatEvent:
    require(turn.event_count < MAX_EVENTS)
    turn.event_count += 1
    value = ChatEvent(
        conversation_id=turn.conversation_id,
        turn_id=turn.id,
        sequence=turn.event_count,
        kind=kind,
        data=data,
    )
    db.add(value)
    db.flush()
    return value


def finish(
    db: Session,
    turn: ChatTurn,
    state: str,
    *,
    release: bool = True,
    data: dict[str, Any] | None = None,
) -> None:
    turn.state = state
    if turn.broker_epoch is None:
        turn.submission_state = "failed-before-send"
    for interaction in db.scalars(
        select(ChatInteraction).where(
            ChatInteraction.turn_id == turn.id,
            ChatInteraction.state.in_(("pending", "replying")),
        )
    ):
        interaction.state = "interrupted"
    if release:
        db.execute(delete(ProjectTurnReservation).where(ProjectTurnReservation.turn_id == turn.id))
    event(db, turn, state, data if data is not None else {})


def context(
    db: Session,
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    prompt: str,
    selections: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    references = capture_references(db, project_id, conversation_id, selections or [])
    documents = list(
        db.scalars(
            select(ProjectDocument)
            .where(ProjectDocument.project_id == project_id)
            .order_by(ProjectDocument.kind)
            .with_for_update()
        )
    )
    require(len(documents) == 3)
    captured = {}
    for document in documents:
        head = _read_revision(db, document, document.head_revision_number)
        captured[DOCUMENT_FILENAMES[cast(DocumentKind, document.kind)]] = {
            "revision_id": str(head.id),
            "content": head.content,
            "sha256": head.content_sha256,
        }
    turns = list(
        db.scalars(
            select(ChatTurn)
            .where(ChatTurn.conversation_id == conversation_id)
            .order_by(ChatTurn.created_at, ChatTurn.id)
            .limit(MAX_PRIOR_TURNS + 1)
        )
    )
    # Explicit practical context ceiling. Never omit older turns and claim resume.
    require(len(turns) <= MAX_PRIOR_TURNS)
    history = []
    for turn in turns:
        interactions = [
            {"kind": row.kind, "data": row.data, "reply": row.reply, "state": row.state}
            for row in db.scalars(
                select(ChatInteraction)
                .where(ChatInteraction.turn_id == turn.id)
                .order_by(ChatInteraction.id)
            )
        ]
        user_text = turn.prompt
        if interactions:
            user_text += "\nRecorded planning interactions (data):\n" + json.dumps(interactions)
        tools = [
            piece.data
            for piece in db.scalars(
                select(ChatEvent)
                .where(ChatEvent.turn_id == turn.id, ChatEvent.kind == "tool")
                .order_by(ChatEvent.sequence)
            )
        ]
        if tools:
            user_text += "\nRecorded planning tool states (data):\n" + json.dumps(tools)
        user_entry: dict[str, Any] = {"role": "user", "text": user_text}
        if turn.payload.get("references"):
            user_entry["references"] = turn.payload["references"]
        history.append(user_entry)
        pieces = db.scalars(
            select(ChatEvent)
            .where(ChatEvent.turn_id == turn.id, ChatEvent.kind == "delta")
            .order_by(ChatEvent.sequence)
        )
        output = "".join(piece.data["text"] for piece in pieces)
        history.append(
            {"role": "assistant", "text": output + "\nRecorded turn state: " + turn.state}
        )
    payload: dict[str, Any] = {"prompt": prompt, "documents": captured, "history": history}
    if references:
        payload["references"] = references
    # Revalidate original bytes and charge ALL included historical occurrences.
    # Persist ONLY versioned metadata, never original/base64 or derivative copies.
    resolve_context(db, project_id, conversation_id, payload)
    return payload


def import_proposals(
    db: Session, turn: ChatTurn, proposals: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """All proposals validated before changing any head; caller owns one transaction."""
    documents = list(
        db.scalars(
            select(ProjectDocument)
            .where(ProjectDocument.project_id == turn.project_id)
            .order_by(ProjectDocument.kind)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    by_name = {DOCUMENT_FILENAMES[cast(DocumentKind, item.kind)]: item for item in documents}
    prepared = []
    for proposal in proposals:
        document = by_name[proposal["filename"]]
        capture = turn.payload["documents"][proposal["filename"]]
        base = db.get(ProjectDocumentRevision, uuid.UUID(capture["revision_id"]))
        if base is None:
            raise ValueError("Captured revision unavailable")
        require(
            base.document_id == document.id
            and base.content_sha256 == proposal["base_sha256"] == capture["sha256"]
        )
        observed = _read_revision(db, document, document.head_revision_number)
        content = proposal["content"]
        if document.kind == "backlog":
            validate_backlog_write(base.content, content, current_content=observed.content)
            base_tasks = {item.id.casefold(): item for item in parse_backlog(base.content).tasks}
            for item in parse_backlog(content).tasks:
                prior = base_tasks.get(item.id.casefold())
                if prior is not None and prior.status != item.status:
                    raise BacklogValidationError("Agent proposals cannot change human readiness.")
        require(document.head_revision_number < MAX_REVISION_NUMBER or observed.id != base.id)
        prepared.append((document, base, observed, content))
    result = []
    for document, base, observed, content in prepared:
        generated = AgentDocumentProposal(
            turn_id=turn.id,
            document_id=document.id,
            base_revision_id=base.id,
            observed_revision_id=observed.id,
            content=content,
            content_sha256=digest(content),
            state="conflict" if observed.id != base.id else "imported",
        )
        if observed.id != base.id:
            conflict = DocumentConflictProposal(
                document_id=document.id,
                expected_revision_number=base.revision_number,
                observed_revision_number=observed.revision_number,
                content=content,
                content_sha256=digest(content),
                author_user_id=turn.actor_user_id,
            )
            db.add(conflict)
            db.flush()
            generated.conflict_proposal_id = conflict.id
        else:
            revision = ProjectDocumentRevision(
                document_id=document.id,
                revision_number=observed.revision_number + 1,
                content=content,
                content_sha256=digest(content),
                origin="agent",
                author_user_id=turn.actor_user_id,
            )
            db.add(revision)
            db.flush()
            document.head_revision_number = revision.revision_number
            generated.imported_revision_id = revision.id
        db.add(generated)
        db.flush()
        record_audit(
            db,
            action="project.agent.proposal." + generated.state,
            actor_user_id=turn.actor_user_id,
            project_id=turn.project_id,
            details={
                "turn_id": str(turn.id),
                "proposal_id": str(generated.id),
                "agent_version": generated.agent_version,
                "base_revision_id": str(base.id),
                "observed_revision_id": str(observed.id),
            },
        )
        result.append(
            {
                "id": str(generated.id),
                "state": generated.state,
                "filename": DOCUMENT_FILENAMES[cast(DocumentKind, document.kind)],
            }
        )
    return result


def initiating_actor(db: Session, turn: ChatTurn) -> AuthenticatedActor:
    user = db.get(User, turn.actor_user_id)
    if user is None:
        raise ValueError("Initiator unavailable")
    return AuthenticatedActor(
        id=user.id,
        username=user.username,
        role=user.role,
        created_at=user.created_at,
        session_token_hash=turn.web_session_hash,
        csrf_token_hash=b"",
    )


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
