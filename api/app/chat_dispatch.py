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

from app.attachment_cleanup import cleanup, purge_scope
from app.chat_admission import TestScope, admission
from app.chat_broker import Broker
from app.chat_protocol import (
    MAX_EVENTS,
    MAX_TEXT,
    NATIVE_INLINE_CONTEXT,
    SEND_GATE_SECONDS,
    TURN_SECONDS,
    ChannelError,
    broker_start_payload,
    digest,
    escaped_size,
    manifest_digest,
    native_occurrence_manifest,
    native_prompt_text,
    original_manifest_digest,
    reference_manifest,
    require,
    resolved_prompt_text,
    send_authorization,
)
from app.chat_protocol import event as validate_event
from app.chat_receipts import reconcile
from app.chat_references import resolve_context, resolve_dispatch_context
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
from app.models import (
    AttachmentDeletion,
    ChatInteraction,
    ChatSendAuthorization,
    ChatTurn,
    Conversation,
    ProjectTurnReservation,
    WebSession,
)

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
    def __init__(
        self, engine: Engine, broker: Broker, *, test_scope: TestScope | None = None
    ) -> None:
        self.engine, self.broker = engine, broker
        self.test_scope = test_scope
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
                    failed = False
                    try:
                        self.advance(turn_id)
                    except Exception:
                        failed = True
                    # Leave the exception context (and its channel traceback/text
                    # frames) BEFORE confirming stop and releasing deletion locks.
                    if failed:
                        self.interrupt(turn_id)
                finally:
                    self.release_claim(turn_id, claim)
            # Submission facts outlive worker-event delivery, cancellation, revoked
            # initiators and the active project reservation. Never send from here.
            with Session(self.engine) as db:
                receipt_ids = list(
                    db.scalars(
                        select(ChatTurn.id).where(ChatTurn.receipt_pending.is_(True)).limit(8)
                    )
                )
                cleanup_ids = list(
                    db.scalars(
                        select(AttachmentDeletion.attachment_id)
                        .where(AttachmentDeletion.pending.is_(True))
                        .limit(8)
                    )
                )
            for turn_id in receipt_ids:
                try:
                    self.poll_receipts(turn_id)
                except Exception:
                    with Session(self.engine) as db:
                        current = db.get(ChatTurn, turn_id)
                        terminal = current is not None and current.state in TERMINAL
                    if terminal:
                        try:
                            # A terminal ledger lost to epoch replacement remains
                            # uncertain, but can close after exact-scope cleanup.
                            purge_scope(self.engine, self.broker, turn_id)
                        except Exception:
                            pass
            for attachment_id in cleanup_ids:
                try:
                    cleanup(self.engine, self.broker, attachment_id)
                except Exception:
                    pass  # Durable fence remains for a later bounded tick.

    def claim(self, turn_id: uuid.UUID) -> datetime | None:
        with Session(self.engine) as db, db.begin():
            turn = db.scalar(
                select(ChatTurn)
                .where(ChatTurn.id == turn_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
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
            never_dispatched = turn.broker_epoch is None
        stopped = False
        if abort:
            try:
                self.poll_receipts(turn_id)
            except Exception:
                pass
            try:
                result = self.broker.call(abort)
                stopped = result.get("stopped") is True and result.get("epoch") == abort["epoch"]
                try:
                    self.poll_receipts(turn_id)
                except Exception:
                    pass
            except Exception:
                # Replacement epoch needs an exact-scope tombstone plus old worker
                # lifetime proof, not merely a hello from a different listener.
                try:
                    purge_scope(self.engine, self.broker, turn_id)
                    stopped = True
                except Exception:
                    pass
        with Session(self.engine) as db, db.begin():
            turn = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
            if turn is None:
                return
            turn.stop_confirmed = turn.stop_confirmed or stopped or never_dispatched
            if turn.state not in TERMINAL:
                finish(db, turn, "interrupted", release=turn.stop_confirmed)
            elif turn.stop_confirmed:
                reservation = db.get(ProjectTurnReservation, turn.project_id)
                if reservation is not None and reservation.turn_id == turn.id:
                    db.delete(reservation)

    def persist_receipts(self, turn_id: uuid.UUID, result: dict[str, Any]) -> None:
        # Deliberately separate commit from authorization/event validation/import.
        with Session(self.engine) as db, db.begin():
            current = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
            if current is None:
                raise ChannelError()
            reconcile(db, current, result)

    def poll_receipts(self, turn_id: uuid.UUID) -> None:
        with Session(self.engine) as db:
            turn = db.get(ChatTurn, turn_id)
            if turn is None or turn.broker_epoch is None:
                return
            poll = dict(command(turn, "poll"), after=turn.broker_cursor)
        result = self.broker.call(poll)
        self.persist_receipts(turn_id, result)
        if result.get("known") is False:
            with Session(self.engine) as db, db.begin():
                current = db.scalar(
                    select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update()
                )
                if current is not None and current.stop_confirmed:
                    current.receipt_pending = False

    def authorize_send(self, turn_id: uuid.UUID, result: dict[str, Any]) -> None:
        """Fresh locked authorization is the revocation linearization point.

        Only advance() invokes this, never the receipt-only reconciler after stop.
        Commit a single-use scoped grant before channel I/O. A lost grant ACK/crash
        interrupts rather than renewing it. Already authorized input is not retractable.
        """
        pending = result.get("send_authorization")
        if pending is None:
            return
        pending = send_authorization(pending)
        require(result.get("known") is True and result.get("stopped") is False)
        require(pending["turn_id"] == str(turn_id) and result.get("epoch") == pending["epoch"])
        with Session(self.engine) as db, db.begin():
            initial = db.get(ChatTurn, turn_id)
            if initial is None:
                raise ChannelError()
            # Existing actor -> web session -> project -> turn -> attachment order.
            authorize(db, initiating_actor(db, initial), initial.project_id, lock=True)
            turn = db.scalar(
                select(ChatTurn)
                .where(ChatTurn.id == turn_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if turn is None or turn.broker_epoch is None:
                raise ChannelError()
            require(turn.state in ("dispatching", "running") and not turn.stop_confirmed)
            if turn.dispatch_deadline is None or utc(turn.dispatch_deadline) <= datetime.now(UTC):
                raise ChannelError()
            require(
                pending["project_id"] == str(turn.project_id)
                and pending["conversation_id"] == str(turn.conversation_id)
                and pending["epoch"] == str(turn.broker_epoch)
            )
            require(
                db.scalar(
                    select(Conversation.id).where(
                        Conversation.id == turn.conversation_id,
                        Conversation.project_id == turn.project_id,
                    )
                )
                is not None
            )
            reservation = db.get(ProjectTurnReservation, turn.project_id)
            require(reservation is not None and reservation.turn_id == turn.id)
            require(
                db.scalar(
                    select(AttachmentDeletion.attachment_id).where(
                        AttachmentDeletion.project_id == turn.project_id,
                        AttachmentDeletion.pending.is_(True),
                    )
                )
                is None
            )
            resolved = resolve_context(db, turn.project_id, turn.conversation_id, turn.payload)
            # original() rechecks actual bytes/hash under attachment locks. History
            # cannot silently become unavailable or available after dispatch capture.
            require(reference_manifest(resolved) == turn.dispatch_manifest)
            require(native_occurrence_manifest(resolved) == pending["original_manifest"])
            require(
                digest(native_prompt_text(resolved))
                == pending["rendered_sha256"]
                == turn.dispatch_rendered_sha256
            )
            require(
                manifest_digest(resolved)
                == pending["manifest_sha256"]
                == turn.dispatch_manifest_sha256
            )
            grants = list(
                db.scalars(
                    select(ChatSendAuthorization)
                    .where(ChatSendAuthorization.turn_id == turn_id)
                    .order_by(ChatSendAuthorization.call)
                )
            )
            require(pending["call"] == len(grants) + 1)
            capability = uuid.uuid4()
            db.add(
                ChatSendAuthorization(
                    turn_id=turn_id,
                    call=pending["call"],
                    epoch=turn.broker_epoch,
                    authorization_id=capability,
                    request_sha256=pending["request_sha256"],
                    request_size=pending["request_size"],
                    original_manifest_sha256=original_manifest_digest(pending["original_manifest"]),
                    expires_at=datetime.now(UTC) + timedelta(seconds=SEND_GATE_SECONDS),
                )
            )
            grant = dict(
                command(turn, "authorize-send"),
                authorization=dict(pending, authorization_id=str(capability)),
            )
        # No database/browser credentials cross this existing authenticated Unix seam.
        self.broker.call(grant)  # NEVER retry/renew a committed grant.

    def advance(self, turn_id: uuid.UUID) -> None:
        with Session(self.engine) as db:
            initial = db.get(ChatTurn, turn_id)
            if initial is None:
                return
            terminal = initial.state in TERMINAL
        if terminal:
            self.interrupt(turn_id)
            return
        hello = self.broker.call({"op": "hello"})
        start = None
        with Session(self.engine, expire_on_commit=False) as db:
            initial = db.get(ChatTurn, turn_id)
            if initial is None:
                return
            epoch = admission(
                hello,
                initial.project_id,
                initial.actor_user_id,
                self.test_scope,
                new=initial.state == "queued",
            )
            # Match application actor -> web-session -> project -> turn lock order.
            authorize(db, initiating_actor(db, initial), initial.project_id, lock=True)
            turn = db.scalar(
                select(ChatTurn)
                .where(ChatTurn.id == turn_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if turn is None:
                return
            require(turn.state not in TERMINAL)
            if turn.state == "queued":
                reservation = db.get(ProjectTurnReservation, turn.project_id)
                require(reservation is not None and reservation.turn_id == turn.id)
                require(
                    db.scalar(
                        select(AttachmentDeletion.attachment_id).where(
                            AttachmentDeletion.project_id == turn.project_id,
                            AttachmentDeletion.pending.is_(True),
                        )
                    )
                    is None
                )
                payload = resolve_dispatch_context(
                    db, turn.project_id, turn.conversation_id, turn.payload
                )
                native = payload.get("kind") == NATIVE_INLINE_CONTEXT
                resolved = payload["context"] if native else payload
                if not native:
                    broker_start_payload(resolved)
                turn.broker_epoch = epoch
                turn.dispatch_deadline = datetime.now(UTC) + timedelta(seconds=TURN_SECONDS)
                turn.state = "dispatching"
                turn.submission_state = "uncertain"
                turn.receipt_pending = True
                turn.dispatch_rendered_sha256 = digest(resolved_prompt_text(resolved))
                turn.dispatch_manifest_sha256 = manifest_digest(resolved)
                turn.dispatch_manifest = reference_manifest(resolved)
                start = dict(command(turn, "start"), payload=payload)
                if native:
                    start["deadline"] = turn.dispatch_deadline.timestamp()
                del resolved, payload  # No binary/context aliases survive channel I/O.
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
                    # Same-epoch retained scope can recover from a lost ACK, but
                    # ONLY by polling. Never start again, even with exact identity.
                    require(turn.dispatch_rendered_sha256 is not None)
                if turn.dispatch_deadline is None:
                    raise ChannelError()
                require(datetime.now(UTC) < utc(turn.dispatch_deadline))
            cancelling = turn.state == "cancelling"
            poll = dict(command(turn, "poll"), after=turn.broker_cursor)
            db.commit()
        if start is not None:
            try:
                self.broker.call(start)  # COMMITTED marker; never retry on failure.
            finally:
                start = None  # Release API text before stop/release/delete can complete.
            with Session(self.engine) as db, db.begin():
                turn = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
                if turn is None:
                    raise ChannelError()
                if turn.state == "dispatching":
                    turn.state = "running"
        elif cancelling:
            try:
                self.poll_receipts(turn_id)
            except Exception:
                pass  # Receipt outage must not prevent stopping the worker.
            stopped_result = self.broker.call(command(turn, "abort"))
            require(
                stopped_result.get("stopped") is True and stopped_result.get("epoch") == str(epoch)
            )
            try:
                self.poll_receipts(turn_id)
            except Exception:
                pass  # Independent reconciler will recover after cancellation.
            with Session(self.engine) as db, db.begin():
                current = db.scalar(
                    select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update()
                )
                if current is None:
                    raise ChannelError()
                if current.state not in TERMINAL:
                    current.stop_confirmed = True
                    finish(db, current, "cancelled")
            return
        elif turn.state == "running":
            self.send_reply(turn_id)
        result = self.broker.call(poll)
        self.persist_receipts(turn_id, result)
        require(result.get("known") is True and result.get("epoch") == str(epoch))
        self.authorize_send(turn_id, result)
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
            if current.state == "dispatching":
                current.state = "running"
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
                    current.stop_confirmed = result.get("stopped") is True
                    finish(db, current, "completed", release=current.stop_confirmed)
                else:
                    current.stop_confirmed = result.get("stopped") is True
                    finish(
                        db,
                        current,
                        "failed" if kind == "failed" else "cancelled",
                        data=data,
                        release=current.stop_confirmed,
                    )
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
