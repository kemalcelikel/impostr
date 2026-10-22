"""Persist trusted poll receipts independently of worker events and actor revocation.

No raw request is retained. The dispatch transaction stores exact rendering and
ordered metadata/coverage hashes before channel I/O; only the trusted host ledger
can supply full native request hashes and submission facts. Sent is not provider
acceptance/comprehension, and later cancellation/deletion cannot retract it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat_protocol import (
    LEGACY_PDF_REFERENCE,
    MAX_PDF_FRAME,
    NATIVE_PDF_REFERENCE,
    ChannelError,
    opaque,
    original_manifest_digest,
    reference_lists,
    require,
    sha256_hex,
)
from app.models import ChatSendAuthorization, ChatSubmissionReceipt, ChatTurn

MAX_INFERENCE_CALLS = 8  # Pinned imp024_protocol.MAX_CALLS; no arbitrary ledger growth.


def reconcile(db: Session, turn: ChatTurn, result: dict[str, Any]) -> None:
    require(result.get("epoch") == str(turn.broker_epoch))
    rows = result.get("receipts", [])
    require(isinstance(rows, list) and len(rows) <= MAX_INFERENCE_CALLS)
    existing = {
        row.call: row
        for row in db.scalars(
            select(ChatSubmissionReceipt).where(ChatSubmissionReceipt.turn_id == turn.id)
        )
    }
    for index, row in enumerate(rows, 1):
        native = isinstance(row, dict) and row.get("reference_kind") == NATIVE_PDF_REFERENCE
        native_fields = {
            "reference_kind",
            "request_size",
            "authorization_id",
            "original_manifest_sha256",
        }
        require(
            isinstance(row, dict)
            and set(row)
            == (
                {
                    "project_id",
                    "conversation_id",
                    "turn_id",
                    "epoch",
                    "call",
                    "rendered_sha256",
                    "manifest_sha256",
                    "request_sha256",
                    "status",
                }
                | (native_fields if native else set())
            )
        )
        require(type(row["call"]) is int and row["call"] == index)
        require(
            row["project_id"] == str(turn.project_id)
            and row["conversation_id"] == str(turn.conversation_id)
            and row["turn_id"] == str(turn.id)
            and row["epoch"] == str(turn.broker_epoch)
            and row["rendered_sha256"] == turn.dispatch_rendered_sha256
            and row["manifest_sha256"] == turn.dispatch_manifest_sha256
        )
        status, request_hash = row["status"], row["request_sha256"]
        require(status in ("sent", "uncertain", "failed-before-send"))
        if request_hash is not None:
            sha256_hex(request_hash)
        require(request_hash is not None or status == "failed-before-send")
        if native:
            manifest: list[dict[str, Any]] = []
            if turn.dispatch_manifest is None:
                raise ChannelError()
            for message_index, entries in enumerate(turn.dispatch_manifest):
                for selection_index, entry in enumerate(entries):
                    if entry["availability"] == "available":
                        reference = entry["reference"]
                        require(reference.get("kind") == NATIVE_PDF_REFERENCE)
                        manifest.append(
                            dict(
                                occurrence=len(manifest),
                                message_index=message_index,
                                selection_index=selection_index,
                                attachment_id=reference["attachment_id"],
                                original_sha256=reference["original_sha256"],
                                original_size=reference["original_size"],
                            )
                        )
            require(
                bool(manifest)
                and row["original_manifest_sha256"] == original_manifest_digest(manifest)
            )
            size, capability = row["request_size"], row["authorization_id"]
            require(
                (size is None and request_hash is None)
                or (type(size) is int and 0 < size <= MAX_PDF_FRAME and request_hash is not None)
            )
            require(status == "failed-before-send" or capability is not None)
            if capability is not None:
                opaque(capability)
                grant = db.get(ChatSendAuthorization, (turn.id, index))
                require(
                    grant is not None
                    and str(grant.authorization_id) == capability
                    and str(grant.epoch) == str(turn.broker_epoch)
                    and grant.request_sha256 == request_hash
                    and grant.request_size == size
                    and grant.original_manifest_sha256 == row["original_manifest_sha256"]
                )
        else:
            size = capability = None
            # Native dispatch cannot acquire legacy-text receipts by dropping fields.
            require(
                not any(
                    entry["availability"] == "available"
                    and entry["reference"].get("kind") == NATIVE_PDF_REFERENCE
                    for entries in (turn.dispatch_manifest or [])
                    for entry in entries
                )
            )
        prior = existing.get(index)
        if prior is not None:
            require(prior.request_sha256 == request_hash)
            require(
                prior.reference_kind == (NATIVE_PDF_REFERENCE if native else LEGACY_PDF_REFERENCE)
                and prior.request_size == size
                and (str(prior.authorization_id) if prior.authorization_id is not None else None)
                == capability
            )
            # A late snapshot may be older than our durable sent observation.
            require(prior.status == status or {prior.status, status} <= {"uncertain", "sent"})
            if status == "sent":
                prior.status = status
        else:
            prior = ChatSubmissionReceipt(
                turn_id=turn.id,
                call=index,
                request_sha256=request_hash,
                status=status,
                reference_kind=NATIVE_PDF_REFERENCE if native else LEGACY_PDF_REFERENCE,
                request_size=size,
                authorization_id=uuid.UUID(capability) if capability else None,
            )
            db.add(prior)
            existing[index] = prior
    statuses = {row.status for row in existing.values()}
    if "sent" in statuses:
        turn.submission_state = "sent"
    elif "uncertain" in statuses:
        turn.submission_state = "uncertain"
    elif result.get("known") is True and result.get("stopped") is True and statuses:
        turn.submission_state = "failed-before-send"
    # Stop closes the ledger. Unknown scopes are NOT definite never-sent evidence.
    if result.get("known") is True and result.get("stopped") is True:
        require(bool(rows) and len(rows) >= len(existing))
        turn.receipt_pending = False


def receipt_view(db: Session, turn: ChatTurn) -> dict[str, Any]:
    kinds = {
        reference.get("kind", LEGACY_PDF_REFERENCE)
        for references in reference_lists(turn.payload)
        for reference in references
    }
    return {
        "reference_kind": "mixed" if len(kinds) > 1 else next(iter(kinds), "none"),
        "status": turn.submission_state,
        "epoch": str(turn.broker_epoch) if turn.broker_epoch is not None else None,
        "reconciliation_pending": turn.receipt_pending,
        "rendered_sha256": turn.dispatch_rendered_sha256,
        "manifest_sha256": turn.dispatch_manifest_sha256,
        "manifest": turn.dispatch_manifest,
        "calls": [
            dict(
                {"call": row.call, "status": row.status, "request_sha256": row.request_sha256},
                **(
                    {
                        "reference_kind": row.reference_kind,
                        "request_size": row.request_size,
                        "authorization_id": (
                            str(row.authorization_id) if row.authorization_id else None
                        ),
                    }
                    if row.reference_kind == NATIVE_PDF_REFERENCE
                    else {}
                ),
            )
            for row in db.scalars(
                select(ChatSubmissionReceipt)
                .where(ChatSubmissionReceipt.turn_id == turn.id)
                .order_by(ChatSubmissionReceipt.call)
            )
        ],
        "meaning": "Submission only, not provider acceptance or comprehension; "
        "cannot retract prior sends",
    }
