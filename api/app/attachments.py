"""Private durable PDF intake/status/preview. No parser or model inclusion here.

POST .../attachments/upload?filename=reference.pdf with a raw application/pdf body.
An accepted envelope is durably pending, NOT a validated PDF or ready to send.
"""

from __future__ import annotations

import html
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from app.audit import record_audit
from app.chat_state import authorize, conversation
from app.dependencies import CurrentActor, DbSession
from app.models import ProjectAttachment
from app.pdf_intake import IntakeError, filename_metadata, original_body
from app.pdf_protocol import LABEL, PDFError, result

router = APIRouter(
    prefix="/projects/{project_id}/chat/{conversation_id}/attachments", tags=["attachments"]
)


def view(row: ProjectAttachment, processing_available: bool = False) -> dict[str, Any]:
    # Deliberately excludes both deferred blobs. No implicit parser or ready claim.
    return {
        "id": str(row.id),
        "filename": row.filename,
        "status": row.status,
        "failure_code": row.failure_code,
        "original_size": row.original_size,
        "original_sha256": row.original_sha256,
        "text_size": row.text_size,
        "text_sha256": row.text_sha256,
        "page_count": row.page_count,
        "missing_pages": row.missing_pages,
        "label": LABEL,
        "provenance": (
            {
                "policy": row.extraction_policy,
                "qpdf": row.qpdf_version,
                "pdftotext": row.pdftotext_version,
                "build_sha256": row.extractor_build_sha256,
            }
            if row.status == "ready"
            else None
        ),
        "processing_available": processing_available,
        "attempt_count": row.attempt_count,
        "last_error_code": row.last_error_code,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "included_in_model": False,
        "created_at": row.created_at.isoformat(),
    }


def audit_access(db: Session, actor: CurrentActor, project_id: uuid.UUID) -> None:
    if actor.role == "admin":
        record_audit(
            db,
            action="admin.project.attachment.read",
            actor_user_id=actor.id,
            project_id=project_id,
        )


def load(
    db: Session, project_id: uuid.UUID, conversation_id: uuid.UUID, attachment_id: uuid.UUID
) -> ProjectAttachment:
    row = db.scalar(
        select(ProjectAttachment)
        .where(
            ProjectAttachment.id == attachment_id,
            ProjectAttachment.project_id == project_id,
            ProjectAttachment.conversation_id == conversation_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Attachment not found")
    return row


@router.post("/upload", status_code=201)
async def upload(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    filename: str = Query(..., min_length=1, max_length=180),
) -> JSONResponse:
    authorize(db, actor, project_id)
    conversation(db, project_id, conversation_id)
    try:
        filename = filename_metadata(filename)
    except IntakeError as exc:
        raise HTTPException(
            422, "Use a plain PDF filename without paths or control characters"
        ) from exc
    # No locks, open DB transaction, disk spool or durable blob while awaiting body.
    db.rollback()
    data: bytes | None = None
    digest: str | None = None
    failure: tuple[int, str, str] | None = None
    if request.headers.get("content-type", "").strip().lower() != "application/pdf" or (
        request.headers.get("content-encoding", "identity").lower() != "identity"
    ):
        failure = (415, "invalid", "Upload a raw application/pdf body without content encoding")
    else:
        try:
            data, digest = await original_body(request.stream())
        except IntakeError as exc:
            failure = (
                (413, "limit", "PDF original exceeds 50,000,000 bytes")
                if exc.code == "limit"
                else (422, "invalid", "Body does not have a PDF envelope")
            )
        except ClientDisconnect:
            failure = (400, "upload_interrupted", "PDF upload was interrupted")
    # Recheck revocation and current ownership after the potentially slow body.
    authorize(db, actor, project_id, lock=True)
    conversation(db, project_id, conversation_id)
    row = ProjectAttachment(
        project_id=project_id,
        conversation_id=conversation_id,
        uploader_user_id=actor.id,
        filename=filename,
        status="failed" if failure else "pending",
        failure_code=failure[1] if failure else None,
        original=data,
        original_size=len(data) if data is not None else None,
        original_sha256=digest,
    )
    db.add(row)
    record_audit(
        db, action="project.attachment.upload", actor_user_id=actor.id, project_id=project_id
    )
    db.commit()  # Before the background worker can claim this upload.
    metadata = view(row, request.app.state.settings.pdf_enabled)
    if failure:
        return JSONResponse({"detail": failure[2], "attachment": metadata}, status_code=failure[0])
    return JSONResponse(metadata, status_code=201)


@router.get("")
def listing(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    after: uuid.UUID | None = None,
) -> dict[str, Any]:
    authorize(db, actor, project_id, lock=True)
    conversation(db, project_id, conversation_id)
    statement = select(ProjectAttachment).where(
        ProjectAttachment.project_id == project_id,
        ProjectAttachment.conversation_id == conversation_id,
    )
    if after is not None:
        statement = statement.where(ProjectAttachment.id > after)
    rows = list(db.scalars(statement.order_by(ProjectAttachment.id).limit(101)))
    items = [view(row, request.app.state.settings.pdf_enabled) for row in rows[:100]]
    audit_access(db, actor, project_id)
    db.commit()
    return {"attachments": items, "next_after": items[-1]["id"] if len(rows) > 100 else None}


@router.get("/{attachment_id}")
def status(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    attachment_id: uuid.UUID,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
) -> dict[str, Any]:
    authorize(db, actor, project_id, lock=True)
    conversation(db, project_id, conversation_id)
    metadata = view(
        load(db, project_id, conversation_id, attachment_id), request.app.state.settings.pdf_enabled
    )
    audit_access(db, actor, project_id)
    db.commit()
    return metadata


@router.get("/{attachment_id}/raw")
def raw(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
) -> Response:
    authorize(db, actor, project_id, lock=True)
    conversation(db, project_id, conversation_id)
    row = load(db, project_id, conversation_id, attachment_id)
    if row.status == "failed" or row.original is None:
        raise HTTPException(404, "Original is not retained")
    content = row.original
    audit_access(db, actor, project_id)
    db.commit()
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="attachment-{attachment_id}.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{attachment_id}/preview")
def preview(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
) -> HTMLResponse:
    authorize(db, actor, project_id, lock=True)
    conversation(db, project_id, conversation_id)
    row = load(db, project_id, conversation_id, attachment_id)
    if row.status != "ready":
        raise HTTPException(409, "PDF text is not ready; check attachment status")
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
                "provenance": view(row)["provenance"],
            }
        )
    except PDFError as exc:
        raise HTTPException(409, "Stored PDF derivative is unavailable") from exc
    content = f"<!doctype html><meta charset=utf-8><p>{html.escape(LABEL)}</p>"
    content += f"<pre>{html.escape(validated['text'])}</pre>"
    audit_access(db, actor, project_id)
    db.commit()
    return HTMLResponse(
        content,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'; frame-ancestors 'none'",
        },
    )


@router.delete("/{attachment_id}", status_code=204)
def remove(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
) -> Response:
    authorize(db, actor, project_id, lock=True)
    conversation(db, project_id, conversation_id)
    db.delete(load(db, project_id, conversation_id, attachment_id))
    record_audit(
        db, action="project.attachment.delete", actor_user_id=actor.id, project_id=project_id
    )
    db.commit()
    return Response(status_code=204)
