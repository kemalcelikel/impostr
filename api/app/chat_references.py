"""Authoritative original PDF capture/revalidation and transient inline dispatch.

Call under the existing actor/session/project authorization lock. Deletion takes
the same project lock, so references are captured atomically against removal.
The project turn reservation protects the transient resolved copy through stop.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from copy import deepcopy
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat_protocol import (
    NATIVE_INLINE_CONTEXT,
    NATIVE_PDF_REFERENCE,
    PDF_DATA_PREFIX,
    ChannelError,
    captured_payload,
    native_dispatch_context,
    native_occurrence_manifest,
    original_reference,
    reference_context,
)
from app.models import ChatTurn, ChatTurnPdfSelection, ProjectAttachment
from app.pdf_protocol import LABEL, PDFError, result


def selection_request(db: Session, turn: ChatTurn) -> list[dict[str, str]]:
    return [
        {
            "attachment_id": str(row.attachment_id),
            "expected_sha256": row.expected_sha256,
            "reference_kind": row.reference_kind,
        }
        for row in db.scalars(
            select(ChatTurnPdfSelection)
            .where(ChatTurnPdfSelection.turn_id == turn.id)
            .order_by(ChatTurnPdfSelection.position)
        )
    ]


def attachment_row(
    db: Session, project_id: uuid.UUID, conversation_id: uuid.UUID, attachment_id: str
) -> ProjectAttachment | None:
    return db.scalar(
        select(ProjectAttachment)
        .where(
            ProjectAttachment.id == uuid.UUID(attachment_id),
            ProjectAttachment.project_id == project_id,
            ProjectAttachment.conversation_id == conversation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def reference_metadata(row: ProjectAttachment) -> dict[str, Any]:
    """Snapshot only; no deferred blob loads for history availability views."""
    return {
        "kind": NATIVE_PDF_REFERENCE,
        "attachment_id": str(row.id),
        "filename": row.filename,
        "original_sha256": row.original_sha256,
        "original_size": row.original_size,
    }


def legacy_reference_metadata(row: ProjectAttachment) -> dict[str, Any]:
    """Preserved derivative identity, never converted into native submission proof."""
    provenance = {
        "policy": row.extraction_policy,
        "qpdf": row.qpdf_version,
        "pdftotext": row.pdftotext_version,
        "build_sha256": row.extractor_build_sha256,
    }
    return {
        "attachment_id": str(row.id),
        "filename": row.filename,
        "original_sha256": row.original_sha256,
        "original_size": row.original_size,
        "text_sha256": row.text_sha256,
        "text_size": row.text_size,
        "page_count": row.page_count,
        "missing_pages": deepcopy(row.missing_pages),
        "label": LABEL,
        "provenance": provenance,
    }


def derivative(row: ProjectAttachment) -> tuple[dict[str, Any], str]:
    if row.status != "ready":
        raise HTTPException(409, "PDF text is not ready; check attachment status before selecting")
    reference = legacy_reference_metadata(row)
    try:
        validated = result(
            {
                "v": 1,
                "status": "ready",
                "size": row.original_size,
                "sha256": row.original_sha256,
                "text": row.text_content,
                "text_sha256": row.text_sha256,
                "pages": row.page_count,
                "missing_pages": row.missing_pages,
                "label": LABEL,
                "provenance": reference["provenance"],
            }
        )
        if row.text_size != len(validated["text"].encode("utf-8")):
            raise PDFError()
    except PDFError as exc:
        raise HTTPException(
            409, "Stored PDF derivative is unavailable; remove or re-upload it"
        ) from exc
    return reference, str(validated["text"])


def original(row: ProjectAttachment) -> dict[str, Any]:
    if row.status != "stored":
        raise HTTPException(409, "Original PDF is unavailable for native selection")
    try:
        reference = original_reference(reference_metadata(row))
    except ChannelError as exc:
        raise HTTPException(409, "Original PDF must be less than 50,000,000 bytes") from exc
    content = row.original
    if (
        content is None
        or len(content) != reference["original_size"]
        or hashlib.sha256(content).hexdigest() != reference["original_sha256"]
        or not content.startswith(b"%PDF-")
    ):
        raise HTTPException(409, "Stored original PDF is unavailable or changed; re-upload it")
    return reference


def capture_references(
    db: Session,
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    selections: list[dict[str, str]],
) -> list[dict[str, Any]]:
    references = []
    for selection in selections:
        if selection.get("reference_kind", NATIVE_PDF_REFERENCE) != NATIVE_PDF_REFERENCE:
            raise HTTPException(409, "Legacy PDF text selection must be selected anew")
        row = attachment_row(db, project_id, conversation_id, selection["attachment_id"])
        if row is None:
            raise HTTPException(404, "Selected attachment not found in this conversation")
        reference = original(row)
        if reference["original_sha256"] != selection["expected_sha256"]:
            raise HTTPException(409, "Original PDF changed; refresh and select it again")
        references.append(reference)
    return references


def resolve_context(
    db: Session, project_id: uuid.UUID, conversation_id: uuid.UUID, captured: dict[str, Any]
) -> dict[str, Any]:
    """Binary-free availability context, freshly byte-revalidated at capture/dispatch.

    Missing historical rows are explicit unavailable references, never omitted.
    Missing CURRENT selections are errors. Legacy references retain their original
    text semantics but are unavailable for new inclusion, never upgraded in place.
    """
    captured_payload(captured)
    resolved = deepcopy(captured)

    def resolve(references: list[dict[str, Any]], *, historical: bool) -> list[dict[str, Any]]:
        entries = []
        for reference in references:
            if reference.get("kind") != NATIVE_PDF_REFERENCE:
                if not historical:
                    raise HTTPException(409, "Legacy PDF text selection must be selected anew")
                entries.append({"reference": reference, "availability": "unavailable"})
                continue
            row = attachment_row(db, project_id, conversation_id, reference["attachment_id"])
            if row is None or row.status != "stored":
                if not historical:
                    raise HTTPException(
                        409, "Selected original PDF is unavailable; remove it before retrying"
                    )
                entries.append({"reference": reference, "availability": "unavailable"})
                continue
            current = original(row)
            if current != reference:
                raise HTTPException(409, "Captured original PDF changed; start a new conversation")
            entries.append({"reference": reference, "availability": "available"})
        return entries

    for item in resolved["history"]:
        if "references" in item:
            item["references"] = resolve(item["references"], historical=True)
    if "references" in resolved:
        resolved["references"] = resolve(resolved["references"], historical=False)
    return reference_context(resolved)


def resolve_dispatch_context(
    db: Session, project_id: uuid.UUID, conversation_id: uuid.UUID, captured: dict[str, Any]
) -> dict[str, Any]:
    """Call under actor/session/project locks; originals never enter durable JSON.

    Repeated historical/current selections remain separate ordered file occurrences.
    No filesystem path or derivative is used; unavailable history remains in context.
    """
    context = resolve_context(db, project_id, conversation_id, captured)
    manifest = native_occurrence_manifest(context)
    if not manifest:
        return context
    files = []
    for occurrence in manifest:
        row = attachment_row(db, project_id, conversation_id, occurrence["attachment_id"])
        if row is None:
            raise HTTPException(409, "Selected original PDF is unavailable")
        reference = original(row)
        if any(reference[key] != occurrence[key] for key in ("original_sha256", "original_size")):
            raise HTTPException(409, "Captured original PDF changed")
        content = row.original
        if content is None:
            raise HTTPException(409, "Selected original PDF is unavailable")
        files.append(
            dict(
                manifest=occurrence, url=PDF_DATA_PREFIX + base64.b64encode(content).decode("ascii")
            )
        )
    return native_dispatch_context(dict(kind=NATIVE_INLINE_CONTEXT, context=context, files=files))


def reference_views(db: Session, turn: ChatTurn) -> list[dict[str, Any]]:
    # Never load either blob for history views or relabel historical text captures.
    views = []
    for reference in turn.payload.get("references", []):
        row = attachment_row(db, turn.project_id, turn.conversation_id, reference["attachment_id"])
        available = (
            reference.get("kind") == NATIVE_PDF_REFERENCE
            and row is not None
            and row.status == "stored"
            and reference_metadata(row) == reference
        )
        views.append(dict(reference, availability="available" if available else "unavailable"))
    return views
