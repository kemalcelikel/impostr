"""One bounded API pump; DB reservations coordinate multiple processes/restarts.

Queued -> dispatching is committed before channel I/O. A dispatcher never retries
an uncertain start or reply. Running state can recover only from the same broker
epoch and exact retained turn; otherwise interrupt and stop the worker.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.chat_broker import Broker
from app.chat_protocol import (
    MAX_EVENTS,
    MAX_TEXT,
    TURN_SECONDS,
    ChannelError,
    escaped_size,
    opaque,
    require,
)
from app.chat_protocol import event as validate_event
from app.chat_state import (
    TERMINAL,
    authorize,
    event,
    finish,
    import_proposals,
    initiating_actor,
    utc,
)
from app.dependencies import AuthenticatedActor, load_active_actor
from app.models import ChatInteraction, ChatTurn, ProjectTurnReservation, WebSession

PUMP_LEASE_SECONDS = 20


def command(turn: ChatTurn, operation: str) -> dict[str, Any]:
    return {
        "op": operation,
        "epoch": str(turn.broker_epoch),
        "project_id": str(turn.project_id),
        "conversation_id": str(turn.conversation_id),
        "turn_id": str(turn.id),
    }


class Dispatcher:
    def __init__(self, engine: Engine, broker: Broker) -> None:
        self.engine, self.broker = engine, broker
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.guard = threading.Lock()

    def run(self) -> None:
        while not self.stop.wait(0.25):
            try:
                self.tick()
            except Exception:
                # No exception trace/raw channel data or transcripts in logs.
                self.stop.wait(0.5)

    def close(self) -> None:
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(80)

    def tick(self) -> None:
        with self.guard:
            with Session(self.engine) as db:
                ids = list(db.scalars(select(ProjectTurnReservation.turn_id).limit(8)))
            for turn_id in ids:
                if self.stop.is_set():
                    return
                claim = self.claim(turn_id)
                if claim is None:
                    continue
                try:
                    self.advance(turn_id)
                except Exception:
                    self.interrupt(turn_id)
                finally:
                    self.release_claim(turn_id, claim)

    def claim(self, turn_id: uuid.UUID) -> datetime | None:
        with Session(self.engine) as db, db.begin():
            turn = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
            if turn is None or (
                turn.pump_until is not None and utc(turn.pump_until) > datetime.now(UTC)
            ):
                return None
            turn.pump_until = datetime.now(UTC) + timedelta(seconds=PUMP_LEASE_SECONDS)
            return turn.pump_until

    def release_claim(self, turn_id: uuid.UUID, claim: datetime) -> None:
        with Session(self.engine) as db, db.begin():
            turn = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
            if turn is not None and turn.pump_until is not None and utc(turn.pump_until) == claim:
                turn.pump_until = None

    def interrupt(self, turn_id: uuid.UUID) -> None:
        with Session(self.engine, expire_on_commit=False) as db:
            turn = db.get(ChatTurn, turn_id)
            if turn is None:
                return
            abort = command(turn, "abort") if turn.broker_epoch else None
            deadline = turn.dispatch_deadline
        stopped = False
        if abort:
            try:
                result = self.broker.call(abort)
                stopped = result.get("stopped") is True
            except Exception:
                pass
        # No new agent writes until stop is confirmed or the mandatory worker
        # total lifetime has expired. Retain the reservation during a broker outage.
        expired = deadline is None or datetime.now(UTC) >= utc(deadline) + timedelta(seconds=5)
        with Session(self.engine) as db, db.begin():
            turn = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
            if turn is None:
                return
            if turn.state not in TERMINAL:
                finish(db, turn, "interrupted", release=stopped or expired)
            elif stopped or expired:
                reservation = db.get(ProjectTurnReservation, turn.project_id)
                if reservation is not None and reservation.turn_id == turn.id:
                    db.delete(reservation)

    def advance(self, turn_id: uuid.UUID) -> None:
        hello = self.broker.call({"op": "hello"})
        epoch = uuid.UUID(opaque(hello.get("epoch")))
        start = None
        with Session(self.engine, expire_on_commit=False) as db:
            initial = db.get(ChatTurn, turn_id)
            if initial is None:
                return
            # Match application actor -> web-session -> project -> turn lock order.
            authorize(db, initiating_actor(db, initial), initial.project_id, lock=True)
            turn = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
            if turn is None:
                return
            require(turn.state not in TERMINAL)
            if turn.state == "queued":
                turn.broker_epoch = epoch
                turn.dispatch_deadline = datetime.now(UTC) + timedelta(seconds=TURN_SECONDS)
                turn.state = "dispatching"
                start = dict(command(turn, "start"), payload=turn.payload)
            else:
                require(turn.broker_epoch == epoch)
                if turn.state == "dispatching":
                    # Another API pump may be between committed marker and channel
                    # ACK. Give the bounded call its window; never send a second start.
                    if turn.dispatch_deadline is None:
                        raise ChannelError()
                    if datetime.now(UTC) < utc(turn.dispatch_deadline) - timedelta(
                        seconds=TURN_SECONDS - 5
                    ):
                        return
                    require(False)  # unresolved dispatch is interrupted, not resubmitted
                if turn.dispatch_deadline is None:
                    raise ChannelError()
                require(datetime.now(UTC) < utc(turn.dispatch_deadline))
            cancelling = turn.state == "cancelling"
            poll = dict(command(turn, "poll"), after=turn.broker_cursor)
            db.commit()
        if start is not None:
            self.broker.call(start)  # COMMITTED dispatch marker; never retry on failure.
            with Session(self.engine) as db, db.begin():
                turn = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
                if turn is None:
                    raise ChannelError()
                if turn.state == "dispatching":
                    turn.state = "running"
        elif cancelling:
            require(self.broker.call(command(turn, "abort")).get("stopped") is True)
            with Session(self.engine) as db, db.begin():
                current = db.scalar(
                    select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update()
                )
                if current is None:
                    raise ChannelError()
                if current.state not in TERMINAL:
                    finish(db, current, "cancelled")
            return
        else:
            self.send_reply(turn_id)
        result = self.broker.call(poll)
        require(result.get("known") is True and result.get("epoch") == str(epoch))
        events = result.get("events")
        if not isinstance(events, list) or len(events) > 16:
            raise ChannelError()
        # Recheck initiator/project at the durable delivery/import boundary.
        with Session(self.engine) as db:
            initial = db.get(ChatTurn, turn_id)
            if initial is None:
                raise ChannelError()
            authorize(db, initiating_actor(db, initial), initial.project_id, lock=True)
            current = db.scalar(
                select(ChatTurn)
                .where(ChatTurn.id == turn_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if current is None:
                raise ChannelError()
            if current.state in TERMINAL or current.state == "cancelling":
                return
            for envelope in events:
                require(isinstance(envelope, dict) and set(envelope) == {"sequence", "event"})
                sequence = envelope["sequence"]
                require(type(sequence) is int)
                if sequence <= current.broker_cursor:
                    continue  # replay after an uncertain DB commit
                require(type(sequence) is int and sequence == current.broker_cursor + 1)
                require(current.event_count < MAX_EVENTS - 1)
                value = validate_event(envelope["event"])
                kind, data = value["type"], value["data"]
                require(
                    kind in ("started", "failed", "cancelled")
                    or current.native_session_id is not None
                )
                if kind == "started":
                    require(current.broker_cursor == 0)
                    current.native_session_id = data["native_session_id"]
                    event(
                        db,
                        current,
                        "started",
                        {"context_reconstructed": data["context_reconstructed"]},
                    )
                elif kind == "delta":
                    # Escaped text budget is additive across deltas and implies
                    # the raw cap too. A maximum accepted user/assistant pair can
                    # be quoted on continuation without a doomed 64 KiB envelope.
                    current.output_bytes += escaped_size(data["text"])
                    require(current.output_bytes <= MAX_TEXT)
                    event(db, current, kind, data)
                elif kind == "tool":
                    event(db, current, kind, data)
                elif kind in ("question", "permission"):
                    interaction = ChatInteraction(
                        turn_id=current.id,
                        native_id=data["id"],
                        kind=kind,
                        data=data,
                        state="pending",
                    )
                    db.add(interaction)
                    db.flush()
                    public = {key: value for key, value in data.items() if key != "id"}
                    event(db, current, kind, dict(public, interaction_id=str(interaction.id)))
                elif kind == "completed":
                    require(current.event_count <= MAX_EVENTS - 2)
                    require(
                        not db.scalar(
                            select(ChatInteraction.id).where(
                                ChatInteraction.turn_id == current.id,
                                ChatInteraction.state.in_(("pending", "replying")),
                            )
                        )
                    )
                    imported = import_proposals(db, current, data["proposals"])
                    if imported:
                        event(db, current, "proposals", {"items": imported})
                    finish(db, current, "completed")
                else:
                    finish(db, current, "failed" if kind == "failed" else "cancelled", data=data)
                current.broker_cursor = sequence
                require(current.state not in TERMINAL or envelope is events[-1])
            db.commit()  # only committed DB events are ever visible to browser streams

    def send_reply(self, turn_id: uuid.UUID) -> None:
        reply = None
        interaction_id = None
        with Session(self.engine) as db:
            turn = db.get(ChatTurn, turn_id)
            if turn is None:
                raise ChannelError()
            queued_reply = db.scalar(
                select(ChatInteraction).where(
                    ChatInteraction.turn_id == turn_id, ChatInteraction.state == "replying"
                )
            )
            if queued_reply is not None and queued_reply.reply_actor_user_id is not None:
                if queued_reply.reply_session_hash is None:
                    raise ChannelError()
                sender = AuthenticatedActor(
                    id=queued_reply.reply_actor_user_id,
                    username="",
                    role="",
                    created_at=turn.created_at,
                    session_token_hash=queued_reply.reply_session_hash,
                    csrf_token_hash=b"",
                )
                # Acquire user locks in ID order before project/turn locks, so
                # reply revocation serializes without cross-admin deadlocks.
                initiator = initiating_actor(db, turn)
                for actor in sorted((initiator, sender), key=lambda item: item.id):
                    load_active_actor(db, actor, for_update=True)
                    db.scalar(
                        select(WebSession)
                        .where(WebSession.token_hash == actor.session_token_hash)
                        .with_for_update()
                    )
            authorize(db, initiating_actor(db, turn), turn.project_id, lock=True)
            turn = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
            if turn is None:
                raise ChannelError()
            require(turn.state == "running")
            interaction = db.scalar(
                select(ChatInteraction)
                .where(ChatInteraction.turn_id == turn_id, ChatInteraction.state == "replying")
                .with_for_update()
            )
            if interaction is not None:
                require(not interaction.reply_dispatched)
                if (
                    interaction.reply_actor_user_id is None
                    or interaction.reply_session_hash is None
                ):
                    raise ChannelError()
                sender = AuthenticatedActor(
                    id=interaction.reply_actor_user_id,
                    username="",
                    role="",
                    created_at=turn.created_at,
                    session_token_hash=interaction.reply_session_hash,
                    csrf_token_hash=b"",
                )
                # A relogin/admin reply uses its own live session; revocation before
                # dispatch must not inherit authorization from the turn initiator.
                authorize(db, sender, turn.project_id)
                interaction.reply_dispatched = True
                interaction_id = interaction.id
                reply = dict(
                    command(turn, "reply"),
                    interaction_id=interaction.native_id,
                    answer=interaction.reply,
                )
            db.commit()
        if reply is not None:
            self.broker.call(reply)
            with Session(self.engine) as db, db.begin():
                turn = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
                if turn is None:
                    raise ChannelError()
                interaction = db.get(ChatInteraction, interaction_id)
                if interaction is None:
                    raise ChannelError()
                if interaction.state == "replying" and turn.state == "running":
                    interaction.state = "replied"
                    event(db, turn, "replied", {"interaction_id": str(interaction_id)})
