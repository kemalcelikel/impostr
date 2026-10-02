"""Owned API PDF pump: short CAS transactions, then the private extractor channel.

Conversion is side-effect-free and may be retried after an expired process lease.
No parsing, paths, credentials or workspace copies in this process. PostgreSQL is
the only durable queue/blob authority; deletion/cascade never creates a new row.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, and_, or_, select, text, update
from sqlalchemy.orm import Session

from app.models import ProjectAttachment
from app.pdf_extractor import UnixPDFExtractor
from app.pdf_lifecycle_policy import (
    LEASE_SECONDS,
    MAX_ATTEMPTS,
    VERIFIED_BUILD_SHA256,
    retry_delay,
)
from app.pdf_protocol import JOB_SECONDS, PDFError, rejected, require, result


@dataclass(frozen=True)
class Claim:
    attachment_id: uuid.UUID
    lease_id: uuid.UUID
    original: bytes
    metadata: dict[str, Any]


def failed_values(code: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_code": code,
        "original": None,
        "text_content": None,
        "text_size": None,
        "text_sha256": None,
        "page_count": None,
        "missing_pages": None,
        "extraction_policy": None,
        "qpdf_version": None,
        "pdftotext_version": None,
        "extractor_build_sha256": None,
        "lease_id": None,
        "lease_until": None,
        "next_attempt_at": None,
        "last_error_code": None,
    }


class PDFProcessor:
    def __init__(self, engine: Engine, extractor: UnixPDFExtractor | None = None) -> None:
        self.engine = engine
        self.extractor = extractor if extractor is not None else UnixPDFExtractor()
        self.stop = threading.Event()
        self.guard = threading.Lock()
        self.thread = threading.Thread(target=self.run, name="impostr-pdf", daemon=True)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with Session(self.engine) as db, db.begin():
            if self.engine.dialect.name == "postgresql":
                # Bound shutdown even if a concurrent delete/admin transaction holds a lock.
                db.execute(text("SET LOCAL statement_timeout = '5000ms'"))
                db.execute(text("SET LOCAL lock_timeout = '3000ms'"))
            yield db

    def run(self) -> None:
        while not self.stop.wait(0.5):
            try:
                self.tick()
            except Exception:
                # No SQL, raw channel bytes, exception strings or PDF text in logs.
                # A committed lease survives outages; restart recovers it after expiry.
                self.stop.wait(1)

    def close(self) -> None:
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(JOB_SECONDS + 20)
        if self.thread.is_alive():
            raise RuntimeError("PDF processor did not stop within its bounded lifetime")

    def eligible(self, now: datetime) -> Any:
        return or_(
            and_(
                ProjectAttachment.status == "pending",
                or_(
                    ProjectAttachment.next_attempt_at.is_(None),
                    ProjectAttachment.next_attempt_at <= now,
                ),
            ),
            and_(ProjectAttachment.status == "processing", ProjectAttachment.lease_until <= now),
        )

    def claim(self, attachment_id: uuid.UUID, *, now: datetime | None = None) -> Claim | None:
        now = now or datetime.now(UTC)
        token = uuid.uuid4()
        with self.transaction() as db:
            # Exhausted crash/restart leases cannot retain blobs indefinitely.
            db.execute(
                update(ProjectAttachment)
                .where(
                    ProjectAttachment.id == attachment_id,
                    self.eligible(now),
                    ProjectAttachment.attempt_count >= MAX_ATTEMPTS,
                )
                .values(**failed_values("unavailable"))
            )
            claimed = db.scalar(
                update(ProjectAttachment)
                .where(
                    ProjectAttachment.id == attachment_id,
                    self.eligible(now),
                    ProjectAttachment.attempt_count < MAX_ATTEMPTS,
                )
                .values(
                    status="processing",
                    lease_id=token,
                    lease_until=now + timedelta(seconds=LEASE_SECONDS),
                    attempt_count=ProjectAttachment.attempt_count + 1,
                    next_attempt_at=None,
                    last_error_code=None,
                )
                .returning(ProjectAttachment.id)
            )
            if claimed is None:
                return None
            row = db.get(ProjectAttachment, attachment_id)
            assert row is not None and row.original is not None
            value = Claim(
                attachment_id,
                token,
                row.original,
                {"v": 1, "size": row.original_size, "sha256": row.original_sha256},
            )
        return value  # Claim and bytes committed; DB session CLOSED before channel I/O.

    def complete(self, claim: Claim, value: dict[str, Any], *, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        value = result(value, claim.metadata)
        if value["status"] == "ready":
            require(value["provenance"]["build_sha256"] == VERIFIED_BUILD_SHA256, "unavailable")
        with self.transaction() as db:
            fence = (
                ProjectAttachment.id == claim.attachment_id,
                ProjectAttachment.status == "processing",
                ProjectAttachment.lease_id == claim.lease_id,
                ProjectAttachment.lease_until > now,
            )
            attempt = db.scalar(select(ProjectAttachment.attempt_count).where(*fence))
            if attempt is None:
                return False  # Deleted, expired, or reclaimed: never resurrect/overwrite.
            if value["status"] == "rejected":
                delay = retry_delay(value["code"], attempt)
                changes = (
                    failed_values(value["code"])
                    if delay is None
                    else {
                        "status": "pending",
                        "lease_id": None,
                        "lease_until": None,
                        "next_attempt_at": now + timedelta(seconds=delay),
                        "last_error_code": value["code"],
                    }
                )
            else:
                provenance = value["provenance"]
                changes = {
                    "status": "ready",
                    "lease_id": None,
                    "lease_until": None,
                    "next_attempt_at": None,
                    "last_error_code": None,
                    "text_content": value["text"],
                    "text_size": len(value["text"].encode()),
                    "text_sha256": value["text_sha256"],
                    "page_count": value["pages"],
                    "missing_pages": value["missing_pages"],
                    "extraction_policy": provenance["policy"],
                    "qpdf_version": provenance["qpdf"],
                    "pdftotext_version": provenance["pdftotext"],
                    "extractor_build_sha256": provenance["build_sha256"],
                }
            # Atomic write fence as well as read fence: a concurrent reclaim/delete
            # between statements cannot be overwritten (including the SQLite seam).
            completed = db.scalar(
                update(ProjectAttachment)
                .where(*fence)
                .values(**changes)
                .returning(ProjectAttachment.id)
            )
        return completed is not None

    def process(self, claim: Claim) -> None:
        try:
            value = result(
                self.extractor.extract(
                    claim.metadata,
                    (claim.original[i : i + 65536] for i in range(0, len(claim.original), 65536)),
                ),
                claim.metadata,
            )
            if value["status"] == "ready":
                require(value["provenance"]["build_sha256"] == VERIFIED_BUILD_SHA256, "unavailable")
        except PDFError as exc:
            value = rejected(exc.code)
        except Exception:
            value = rejected("unavailable")
        self.complete(claim, value)

    def tick(self) -> None:
        with self.guard:
            if self.stop.is_set():
                return
            with self.transaction() as db:
                ids = list(
                    db.scalars(
                        select(ProjectAttachment.id)
                        .where(self.eligible(datetime.now(UTC)))
                        .order_by(ProjectAttachment.created_at, ProjectAttachment.id)
                        .limit(8)
                    )
                )
            for attachment_id in ids:
                if self.stop.is_set():
                    return
                claim = self.claim(attachment_id)
                if claim is not None:
                    self.process(claim)
                    return  # One whole job per tick/process; converter enforces global admission.
