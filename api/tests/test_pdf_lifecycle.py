"""Durable lifecycle regressions with synthetic clients; no parser/channel runtime."""

from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.orm import Session
from test_attachments import headers, setup_intake, upload
from test_attachments_migration import migrate, seed_history

from app import config
from app.config import AppSettings
from app.main import create_app
from app.models import Conversation, Project, ProjectAttachment, WebSession
from app.pdf_lifecycle import PDFProcessor
from app.pdf_lifecycle_policy import LEASE_SECONDS, MAX_ATTEMPTS, VERIFIED_BUILD_SHA256
from app.pdf_protocol import LABEL, POLICY, PDFError, rejected

BODY = b"%PDF-synthetic-lifecycle"


def ready(metadata, text="Synthetic café <script> reference\f\f"):
    return {
        **metadata,
        "status": "ready",
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "pages": 2,
        "missing_pages": [2],
        "label": LABEL,
        "provenance": {
            "policy": POLICY,
            "qpdf": "11.3.0",
            "pdftotext": "22.12.0",
            "build_sha256": VERIFIED_BUILD_SHA256,
        },
    }


def seed_attachment(engine, ids):
    owner, project, conversation = ids
    with Session(engine) as db, db.begin():
        row = ProjectAttachment(
            project_id=project,
            conversation_id=conversation,
            uploader_user_id=owner,
            filename="reference.pdf",
            original=BODY,
            original_size=len(BODY),
            original_sha256=hashlib.sha256(BODY).hexdigest(),
        )
        db.add(row)
        db.flush()
        return row.id


@pytest.fixture
def lifecycle_db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lifecycle.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    migrate(engine, "head")
    ids = seed_history(engine)
    yield engine, ids
    engine.dispose()


def test_claim_commit_before_io_ready_provenance_and_restart(lifecycle_db):
    engine, ids = lifecycle_db
    attachment = seed_attachment(engine, ids)
    calls = []

    def extract(metadata, chunks):
        # Independent connection sees committed processing. Can write while channel
        # is active: no long transaction/row lock is held during extraction.
        with Session(engine) as db, db.begin():
            row = db.get(ProjectAttachment, attachment)
            assert row.status == "processing" and row.lease_id is not None
            assert row.attempt_count == 1
            db.execute(
                update(Conversation).where(Conversation.id == ids[2]).values(title="changed")
            )
        assert b"".join(chunks) == BODY
        calls.append(metadata)
        return ready(metadata)

    processor = PDFProcessor(engine, Mock(extract=extract))
    processor.tick()
    assert len(calls) == 1
    with Session(engine) as db:
        row = db.get(ProjectAttachment, attachment)
        assert row.status == "ready" and row.original == BODY
        assert row.extractor_build_sha256 == VERIFIED_BUILD_SHA256
        assert row.missing_pages == [2] and row.lease_id is None
    restarted = PDFProcessor(engine, Mock())
    restarted.tick()
    restarted.extractor.extract.assert_not_called()


def test_shutdown_drains_inflight_job_and_leaves_next_pending(lifecycle_db):
    engine, ids = lifecycle_db
    first = seed_attachment(engine, ids)
    second = seed_attachment(engine, ids)
    entered, release = threading.Event(), threading.Event()

    def extract(metadata, chunks):
        entered.set()
        assert release.wait(5)
        return ready(metadata)

    processor = PDFProcessor(engine, Mock(extract=Mock(side_effect=extract)))
    processor.thread.start()
    assert entered.wait(5)
    closing = threading.Thread(target=processor.close)
    closing.start()
    assert processor.stop.wait(5)
    release.set()
    closing.join(10)
    assert not closing.is_alive() and not processor.thread.is_alive()
    with Session(engine) as db:
        states = [db.get(ProjectAttachment, key).status for key in (first, second)]
        assert sorted(states) == ["pending", "ready"]
    assert processor.extractor.extract.call_count == 1


def test_atomic_claim_concurrency_expiry_stale_completion_and_crash_budget(lifecycle_db):
    engine, ids = lifecycle_db
    attachment = seed_attachment(engine, ids)
    now = datetime.now(UTC)
    barrier = threading.Barrier(2)
    claims = []
    errors = []

    def contender():
        try:
            barrier.wait(timeout=5)
            claims.append(PDFProcessor(engine).claim(attachment, now=now))
        except Exception as exc:
            errors.append(type(exc))

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
    assert not errors
    assert len([claim for claim in claims if claim is not None]) == 1
    first = next(claim for claim in claims if claim is not None)
    restarted = PDFProcessor(engine)
    assert restarted.claim(attachment, now=now + timedelta(seconds=LEASE_SECONDS - 1)) is None
    expiry = now + timedelta(seconds=LEASE_SECONDS)
    assert restarted.complete(first, ready(first.metadata), now=expiry) is False
    second = restarted.claim(attachment, now=expiry)
    assert second is not None and second.lease_id != first.lease_id
    assert restarted.complete(first, ready(first.metadata), now=expiry) is False
    third = restarted.claim(attachment, now=expiry + timedelta(seconds=LEASE_SECONDS))
    assert third is not None
    assert restarted.claim(attachment, now=expiry + timedelta(seconds=2 * LEASE_SECONDS)) is None
    with Session(engine) as db:
        row = db.get(ProjectAttachment, attachment)
        assert row.status == "failed" and row.failure_code == "unavailable"
        assert row.attempt_count == MAX_ATTEMPTS and row.original is None
        assert row.text_content is None and row.lease_id is None


@pytest.mark.parametrize("code", ["busy", "unavailable"])
def test_transient_durable_backoff_recovery_and_exhaustion(lifecycle_db, code):
    engine, ids = lifecycle_db
    attachment = seed_attachment(engine, ids)
    now = datetime.now(UTC)
    processor = PDFProcessor(engine)
    first = processor.claim(attachment, now=now)
    assert processor.complete(first, rejected(code), now=now)
    restarted = PDFProcessor(engine)
    assert restarted.claim(attachment, now=now + timedelta(seconds=4)) is None
    with Session(engine) as db:
        row = db.get(ProjectAttachment, attachment)
        assert row.status == "pending" and row.last_error_code == code and row.original == BODY
        assert row.next_attempt_at is not None and row.lease_id is None
    second = restarted.claim(attachment, now=now + timedelta(seconds=5))
    assert restarted.complete(second, ready(second.metadata), now=now + timedelta(seconds=5))
    # A separate job exhausts three actual transient attempts, removing both blobs.
    attachment = seed_attachment(engine, ids)
    for delay in (0, 5, 20):
        claim = restarted.claim(attachment, now=now + timedelta(seconds=delay))
        assert claim is not None
        assert restarted.complete(claim, rejected(code), now=now + timedelta(seconds=delay))
    with Session(engine) as db:
        row = db.get(ProjectAttachment, attachment)
        assert row.status == "failed" and row.failure_code == code
        assert row.original is None and row.text_content is None and row.next_attempt_at is None


@pytest.mark.parametrize(
    "code", ["invalid", "encrypted", "active_content", "no_text", "limit", "timeout"]
)
def test_terminal_rejections_clear_blobs_without_retry(lifecycle_db, code):
    engine, ids = lifecycle_db
    attachment = seed_attachment(engine, ids)
    processor = PDFProcessor(engine, Mock(extract=Mock(side_effect=PDFError(code))))
    processor.tick()
    with Session(engine) as db:
        row = db.get(ProjectAttachment, attachment)
        assert row.status == "failed" and row.failure_code == code and row.attempt_count == 1
        assert row.original is None and row.text_content is None
        assert (
            row.original_size == len(BODY)
            and row.original_sha256 == hashlib.sha256(BODY).hexdigest()
        )
    processor.tick()
    assert processor.extractor.extract.call_count == 1


@pytest.mark.parametrize("scope", ["attachment", "conversation", "project"])
def test_delete_cascade_during_io_prevents_orphans_and_resurrection(lifecycle_db, scope):
    engine, ids = lifecycle_db
    attachment = seed_attachment(engine, ids)

    def extract(metadata, chunks):
        assert b"".join(chunks) == BODY
        with Session(engine) as db, db.begin():
            model, key = {
                "attachment": (ProjectAttachment, attachment),
                "conversation": (Conversation, ids[2]),
                "project": (Project, ids[1]),
            }[scope]
            db.execute(delete(model).where(model.id == key))
        return ready(metadata)

    PDFProcessor(engine, Mock(extract=extract)).tick()
    with Session(engine) as db:
        assert db.scalar(select(ProjectAttachment.id)) is None


def test_unverified_build_or_bad_result_is_never_persisted(lifecycle_db):
    engine, ids = lifecycle_db
    attachment = seed_attachment(engine, ids)

    def wrong_build(metadata, chunks):
        value = ready(metadata)
        value["provenance"]["build_sha256"] = "a" * 64
        return value

    PDFProcessor(engine, Mock(extract=wrong_build)).tick()
    with Session(engine) as db:
        row = db.get(ProjectAttachment, attachment)
        assert row.status == "pending" and row.last_error_code == "unavailable"
        assert row.text_content is None and row.extractor_build_sha256 is None


def test_revoked_session_cannot_read_or_delete_ready_and_processing_is_server_owned(
    client, engine, account_factory
):
    account_factory("pdf-owner", "synthetic PDF passphrase")
    _, _, base = setup_intake(client)
    attachment_id = upload(client, base).json()["id"]

    def extract(metadata, chunks):
        with Session(engine) as db, db.begin():
            db.execute(update(WebSession).values(revoked_at=datetime.now(UTC)))
        return ready(metadata)

    PDFProcessor(engine, Mock(extract=extract)).tick()
    with Session(engine) as db:
        assert db.get(ProjectAttachment, uuid.UUID(attachment_id)).status == "ready"
    for suffix in ("", "/raw", "/preview"):
        assert client.get(base + f"/{attachment_id}" + suffix).status_code == 401
    assert client.delete(base + f"/{attachment_id}", headers=headers(client)).status_code == 401


def test_lifespan_pdf_independent_of_chat_and_owned_shutdown(
    engine, settings, workspace_root, monkeypatch
):
    processor = Mock()
    monkeypatch.setattr("app.main.PDFProcessor", Mock(return_value=processor))
    app = create_app(engine, replace(settings, pdf_enabled=True), workspace_root=workspace_root)
    with TestClient(app):
        assert app.state.chat_dispatcher is None
        processor.thread.start.assert_called_once()
    processor.close.assert_called_once()
    stopped = PDFProcessor(engine)
    stopped.thread.start()
    stopped.close()
    assert not stopped.thread.is_alive()


def test_pdf_configuration_defaults_off_and_rejects_ambiguous_flag(monkeypatch):
    # Synthetic injected values only; no private environment/configuration reads.
    monkeypatch.setattr(
        "app.config.os.environ",
        {
            "IMPOSTR_RATE_LIMIT_KEY": "synthetic" * 8,
            "IMPOSTR_PUBLIC_ORIGIN": "http://127.0.0.1:8080",
        },
    )
    assert AppSettings.from_environment().pdf_enabled is False
    monkeypatch.setitem(config.os.environ, "IMPOSTR_PDF_ENABLED", "1")
    assert AppSettings.from_environment().pdf_enabled is True
    monkeypatch.setitem(config.os.environ, "IMPOSTR_PDF_ENABLED", "yes")
    with pytest.raises(ValueError, match="IMPOSTR_PDF_ENABLED"):
        AppSettings.from_environment()
