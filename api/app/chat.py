"""Authenticated conversation, committed turn, interaction and DB replay endpoints."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.chat_protocol import ChannelError, answer, encode, message_text
from app.chat_state import TERMINAL, authorize, context, conversation, event, finish
from app.dependencies import CurrentActor, DbSession, SettingsDependency
from app.models import (
    AgentDocumentProposal,
    ChatEvent,
    ChatInteraction,
    ChatTurn,
    Conversation,
    ConversationPreference,
    ProjectTurnReservation,
)
from app.rate_limit import consume_rate_bucket

router = APIRouter(prefix="/projects/{project_id}/chat", tags=["chat"])


class ConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(min_length=1, max_length=120)]


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    prompt: str

    @field_validator("prompt")
    @classmethod
    def bounded_prompt(cls, value: str) -> str:
        return message_text(value)


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    answer: dict[str, Any]

    @field_validator("answer")
    @classmethod
    def bounded_answer(cls, value: dict[str, Any]) -> dict[str, Any]:
        encode(value)
        return value


def turn_view(turn: ChatTurn) -> dict[str, Any]:
    return {
        "id": str(turn.id),
        "request_id": str(turn.request_id),
        "prompt": turn.prompt,
        "state": turn.state,
        "created_at": turn.created_at.isoformat(),
    }


def audit_admin(db: Session, actor: CurrentActor, project_id: uuid.UUID) -> None:
    if actor.role == "admin":
        record_audit(
            db, action="admin.project.chat.read", actor_user_id=actor.id, project_id=project_id
        )


def load_turn(
    db: Session, project_id: uuid.UUID, conversation_id: uuid.UUID, turn_id: uuid.UUID
) -> ChatTurn:
    conversation(db, project_id, conversation_id)
    turn = db.scalar(
        select(ChatTurn)
        .where(ChatTurn.id == turn_id, ChatTurn.conversation_id == conversation_id)
        .with_for_update()
    )
    if turn is None:
        raise HTTPException(404, "Turn not found")
    return turn


@router.get("")
def list_conversations(project_id: uuid.UUID, db: DbSession, actor: CurrentActor) -> dict[str, Any]:
    authorize(db, actor, project_id)
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.project_id == project_id)
        .order_by(Conversation.created_at, Conversation.id)
    )
    items = [{"id": str(row.id), "title": row.title} for row in rows]
    preference = db.get(ConversationPreference, (actor.id, project_id))
    last = str(preference.conversation_id) if preference else None
    audit_admin(db, actor, project_id)
    db.commit()
    return {"conversations": items, "last_conversation_id": last}


@router.post("", status_code=201)
def new_conversation(
    project_id: uuid.UUID, payload: ConversationRequest, db: DbSession, actor: CurrentActor
) -> dict[str, str]:
    authorize(db, actor, project_id, lock=True)
    count = len(
        list(db.scalars(select(Conversation.id).where(Conversation.project_id == project_id)))
    )
    if count >= 32:
        raise HTTPException(409, "Conversation limit reached")
    row = Conversation(project_id=project_id, creator_user_id=actor.id, title=payload.title)
    db.add(row)
    db.flush()
    preference = db.get(ConversationPreference, (actor.id, project_id))
    if preference is None:
        db.add(
            ConversationPreference(user_id=actor.id, project_id=project_id, conversation_id=row.id)
        )
    else:
        preference.conversation_id = row.id
    db.commit()
    return {"id": str(row.id), "title": row.title}


@router.put("/{conversation_id}/last-used")
def last_used(
    project_id: uuid.UUID, conversation_id: uuid.UUID, db: DbSession, actor: CurrentActor
) -> dict[str, str]:
    authorize(db, actor, project_id, lock=True)
    conversation(db, project_id, conversation_id)
    preference = db.get(ConversationPreference, (actor.id, project_id))
    if preference is None:
        db.add(
            ConversationPreference(
                user_id=actor.id, project_id=project_id, conversation_id=conversation_id
            )
        )
    else:
        preference.conversation_id = conversation_id
    db.commit()
    return {"last_conversation_id": str(conversation_id)}


@router.get("/{conversation_id}")
def history(
    project_id: uuid.UUID, conversation_id: uuid.UUID, db: DbSession, actor: CurrentActor
) -> dict[str, Any]:
    authorize(db, actor, project_id)
    conversation(db, project_id, conversation_id)
    turns = [
        turn_view(row)
        for row in db.scalars(
            select(ChatTurn)
            .where(ChatTurn.conversation_id == conversation_id)
            .order_by(ChatTurn.created_at, ChatTurn.id)
        )
    ]
    interactions = [
        {
            "id": str(row.id),
            "turn_id": str(row.turn_id),
            "kind": row.kind,
            "state": row.state,
            "data": {k: v for k, v in row.data.items() if k != "id"},
        }
        for row in db.scalars(
            select(ChatInteraction)
            .join(ChatTurn)
            .where(ChatTurn.conversation_id == conversation_id)
        )
    ]
    audit_admin(db, actor, project_id)
    db.commit()
    return {"turns": turns, "interactions": interactions}


@router.post("/{conversation_id}/turns", status_code=202)
def submit(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    payload: TurnRequest,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    settings: SettingsDependency,
) -> dict[str, Any]:
    authorize(db, actor, project_id, lock=True)
    conversation(db, project_id, conversation_id)
    existing = db.scalar(
        select(ChatTurn).where(
            ChatTurn.conversation_id == conversation_id, ChatTurn.request_id == payload.request_id
        )
    )
    if existing:
        if existing.prompt != payload.prompt or existing.actor_user_id != actor.id:
            raise HTTPException(409, "Idempotency key already used")
        return turn_view(existing)
    if not settings.chat_enabled or request.app.state.chat_dispatcher is None:
        raise HTTPException(503, "Chat is disabled or broker unavailable")
    if db.get(ProjectTurnReservation, project_id) is not None:
        raise HTTPException(409, "Another project turn is active; retry after it finishes")
    decision = consume_rate_bucket(
        db,
        settings=settings,
        scope="chat-turn",
        subject=str(actor.id),
        limit=30,
        window_seconds=3600,
    )
    if not decision.allowed:
        db.commit()
        raise HTTPException(
            429, "Too many chat turns", headers={"Retry-After": str(decision.retry_after_seconds)}
        )
    try:
        captured = context(db, project_id, conversation_id, payload.prompt)
    except ChannelError as exc:
        raise HTTPException(
            422, "Chat context exceeds supported bounds; no turn dispatched"
        ) from exc
    turn = ChatTurn(
        project_id=project_id,
        conversation_id=conversation_id,
        request_id=payload.request_id,
        actor_user_id=actor.id,
        web_session_hash=actor.session_token_hash,
        prompt=payload.prompt,
        payload=captured,
        state="queued",
    )
    db.add(turn)
    db.flush()
    db.add(ProjectTurnReservation(project_id=project_id, turn_id=turn.id))
    event(db, turn, "queued", {})
    db.commit()
    return turn_view(turn)


@router.post("/{conversation_id}/turns/{turn_id}/abort")
def abort(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
) -> dict[str, Any]:
    authorize(db, actor, project_id, lock=True)
    turn = load_turn(db, project_id, conversation_id, turn_id)
    if turn.state == "queued":
        finish(db, turn, "cancelled")
    elif turn.state not in TERMINAL:
        turn.state = "cancelling"
        for row in db.scalars(
            select(ChatInteraction).where(
                ChatInteraction.turn_id == turn.id,
                ChatInteraction.state.in_(("pending", "replying")),
            )
        ):
            row.state = "interrupted"
    db.commit()
    return turn_view(turn)


@router.post(
    "/{conversation_id}/turns/{turn_id}/interactions/{interaction_id}/reply", status_code=202
)
def reply(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
    interaction_id: uuid.UUID,
    payload: ReplyRequest,
    db: DbSession,
    actor: CurrentActor,
) -> dict[str, str]:
    authorize(db, actor, project_id, lock=True)
    turn = load_turn(db, project_id, conversation_id, turn_id)
    interaction = db.scalar(
        select(ChatInteraction)
        .where(ChatInteraction.id == interaction_id, ChatInteraction.turn_id == turn.id)
        .with_for_update()
    )
    if interaction is None:
        raise HTTPException(404, "Interaction not found")
    if interaction.reply_request_id == payload.request_id and interaction.reply == payload.answer:
        return {"state": interaction.state}
    if interaction.state != "pending" or turn.state != "running":
        raise HTTPException(409, "Interaction is no longer pending")
    try:
        validated = answer(interaction.kind, interaction.data, payload.answer)
    except (ChannelError, ValueError) as exc:
        raise HTTPException(422, "Reply is not allowed by the planning policy") from exc
    interaction.reply = validated
    interaction.reply_request_id = payload.request_id
    interaction.reply_actor_user_id = actor.id
    interaction.reply_session_hash = actor.session_token_hash
    interaction.state = "replying"
    db.commit()
    return {"state": "replying"}


def event_page(db: Session, conversation_id: uuid.UUID, after: int) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ChatEvent)
        .where(ChatEvent.conversation_id == conversation_id, ChatEvent.id > after)
        .order_by(ChatEvent.id)
        .limit(64)
    )
    return [
        {
            "id": row.id,
            "turn_id": str(row.turn_id),
            "sequence": row.sequence,
            "type": row.kind,
            "data": row.data,
        }
        for row in rows
    ]


@router.get("/{conversation_id}/events")
def events(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
    after: int = Query(0, ge=0),
) -> dict[str, Any]:
    authorize(db, actor, project_id)
    conversation(db, project_id, conversation_id)
    page = event_page(db, conversation_id, after)
    audit_admin(db, actor, project_id)
    db.commit()
    return {"events": page, "after": page[-1]["id"] if page else after}


@router.get("/{conversation_id}/stream")
def stream(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    after: int = Query(0, ge=0),
) -> StreamingResponse:
    authorize(db, actor, project_id)
    conversation(db, project_id, conversation_id)
    audit_admin(db, actor, project_id)
    db.commit()
    engine = db.get_bind()

    async def replay() -> AsyncIterator[str]:
        cursor = after
        # Bounded connection; browser reconnects with last committed event ID.
        for _ in range(120):
            if await request.is_disconnected():
                return
            try:
                with Session(engine) as fresh:
                    authorize(fresh, actor, project_id)
                    conversation(fresh, project_id, conversation_id)
                    page = event_page(fresh, conversation_id, cursor)
            except Exception:
                yield "event: unavailable\ndata: {}\n\n"
                return
            for value in page:
                # Revalidate before each delivered event too, not only once for
                # an entire page that may outlive session revocation.
                try:
                    with Session(engine) as fresh:
                        authorize(fresh, actor, project_id)
                except Exception:
                    yield "event: unavailable\ndata: {}\n\n"
                    return
                cursor = value["id"]
                yield f"id: {cursor}\nevent: chat\ndata: {json.dumps(value)}\n\n"
            if not page:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        replay(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/proposals/{proposal_id}")
def proposal(
    project_id: uuid.UUID, proposal_id: uuid.UUID, db: DbSession, actor: CurrentActor
) -> dict[str, Any]:
    authorize(db, actor, project_id)
    row = db.scalar(
        select(AgentDocumentProposal)
        .join(ChatTurn)
        .where(AgentDocumentProposal.id == proposal_id, ChatTurn.project_id == project_id)
    )
    if row is None:
        raise HTTPException(404, "Proposal not found")
    result = {
        "id": str(row.id),
        "turn_id": str(row.turn_id),
        "state": row.state,
        "content": row.content,
        "content_sha256": row.content_sha256,
        "base_revision_id": str(row.base_revision_id),
        "observed_revision_id": str(row.observed_revision_id),
        "imported_revision_id": str(row.imported_revision_id) if row.imported_revision_id else None,
        "conflict_proposal_id": str(row.conflict_proposal_id) if row.conflict_proposal_id else None,
        "origin": "agent",
        "agent_version": row.agent_version,
        "approved": False,
    }
    audit_admin(db, actor, project_id)
    db.commit()
    return result
