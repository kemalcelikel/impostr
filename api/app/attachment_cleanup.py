"""Durable, retryable stopped-broker cleanup; never retries inference.

Removal is unavailable immediately in the DB but remains pending until every
captured scope has a purge/tombstone proof. New project turns are fenced meanwhile.
An epoch change alone is insufficient: fence the exact scope in the replacement
and wait out the old worker's mandatory total lifetime before accepting its proof.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.chat_broker import Broker
from app.chat_protocol import STOP_SECONDS, opaque, require
from app.chat_receipts import reconcile
from app.chat_state import utc
from app.models import AttachmentDeletion, AttachmentPurge, ChatTurn, Project


def scoped(turn: ChatTurn, epoch: uuid.UUID, operation: str) -> dict[str, Any]:
    return {
        "op": operation,
        "epoch": str(epoch),
        "project_id": str(turn.project_id),
        "conversation_id": str(turn.conversation_id),
        "turn_id": str(turn.id),
    }


def purge_scope(engine: Engine, broker: Broker, turn_id: uuid.UUID) -> uuid.UUID:
    with Session(engine, expire_on_commit=False) as db:
        turn = db.get(ChatTurn, turn_id)
        if turn is None or turn.broker_epoch is None:
            raise ValueError("Dispatch scope unavailable")
        old_epoch, deadline = turn.broker_epoch, turn.dispatch_deadline
    hello = broker.call({"op": "hello"})
    epoch = uuid.UUID(opaque(hello.get("epoch")))
    cmd = scoped(turn, epoch, "purge")
    if epoch == old_epoch:
        # Poll receipt facts BEFORE discarding worker events/payload; also safe on
        # replay after a lost purge ACK (the host keeps metadata-only receipts).
        response = broker.call(dict(cmd, op="poll", after=0))
        with Session(engine) as db, db.begin():
            current = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
            if current is None:
                raise ValueError("Dispatch scope unavailable")
            reconcile(db, current, response)
    response = broker.call(cmd)
    require(response.get("epoch") == str(epoch) and response.get("stopped") is True)
    require(response.get("purged") is True or response.get("known") is False)
    if epoch != old_epoch:
        # Native starts carry this exact absolute deadline; the host does not
        # renew it after binary transfer. Include bounded reap/relay teardown too.
        require(
            deadline is not None
            and datetime.now(UTC) >= utc(deadline) + timedelta(seconds=STOP_SECONDS)
        )
    if epoch != old_epoch or response.get("known") is False:
        with Session(engine) as db, db.begin():
            current = db.scalar(select(ChatTurn).where(ChatTurn.id == turn_id).with_for_update())
            if current is not None:
                # The ledger is gone/unknown; keep honest durable uncertainty (or
                # previously observed sent), but there is nothing left to poll.
                current.receipt_pending = False
    return epoch


def cleanup(engine: Engine, broker: Broker, attachment_id: uuid.UUID) -> bool:
    with Session(engine) as db:
        deletion = db.get(AttachmentDeletion, attachment_id)
        if deletion is None:
            return False
        if not deletion.pending:
            return True
        project_id = deletion.project_id
        ids = list(
            db.scalars(
                select(AttachmentPurge.turn_id).where(
                    AttachmentPurge.attachment_id == attachment_id,
                    AttachmentPurge.confirmed_epoch.is_(None),
                )
            )
        )
    for turn_id in ids:
        try:
            epoch = purge_scope(engine, broker, turn_id)
        except Exception:
            return False  # Fence remains durable; no pretend deletion on outage.
        with Session(engine) as db, db.begin():
            db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            proof = db.get(AttachmentPurge, (attachment_id, turn_id))
            if proof is not None:
                proof.confirmed_epoch = epoch
    with Session(engine) as db, db.begin():
        db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        deletion = db.get(AttachmentDeletion, attachment_id)
        if deletion is None:
            return False
        pending = db.scalar(
            select(AttachmentPurge.turn_id).where(
                AttachmentPurge.attachment_id == attachment_id,
                AttachmentPurge.confirmed_epoch.is_(None),
            )
        )
        if pending is None:
            deletion.pending = False
        return not deletion.pending
