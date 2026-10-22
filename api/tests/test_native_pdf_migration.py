"""Actual 0009 -> candidate 0010 -> native 0011 preservation and completion fence.

check_native_transition also accepts a fresh coordinator-owned PostgreSQL engine;
this module never discovers database credentials or starts Docker.
"""

import hashlib
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_attachments_migration import history, migrate, seed_history
from test_pdf_lifecycle import ready

from app.models import ProjectAttachment
from app.pdf_lifecycle import PDFProcessor
from app.pdf_protocol import rejected

BODY = b"%PDF-synthetic-native-transition"


def snapshot(engine, table_name):
    with engine.connect() as db:
        table = Table(table_name, MetaData(), autoload_with=db)
        return db.execute(select(table).order_by(*table.primary_key)).all()


def check_native_transition(engine):
    migrate(engine, "20261002_0009")
    owner, project, conversation = seed_history(engine)
    processor = PDFProcessor(engine, Mock())  # DB CAS only; never starts the extractor.
    ids = []
    with Session(engine) as db, db.begin():
        for _ in range(3):
            row = ProjectAttachment(
                project_id=project,
                conversation_id=conversation,
                uploader_user_id=owner,
                filename="retained.pdf",
                status="pending",
                original=BODY,
                original_size=len(BODY),
                original_sha256=hashlib.sha256(BODY).hexdigest(),
            )
            db.add(row)
            db.flush()
            ids.append(row.id)
        failed = ProjectAttachment(
            project_id=project,
            conversation_id=conversation,
            uploader_user_id=owner,
            filename="legacy-rejected.pdf",
            status="failed",
            failure_code="no_text",
            original_size=123,
            original_sha256="a" * 64,
        )
        db.add(failed)
        db.flush()
        failed_id = failed.id
    # Exercise real legacy claim/ready/retry DB state before the transition.
    completed = processor.claim(ids[0])
    assert completed is not None
    assert processor.complete(completed, ready(completed.metadata))
    stale = processor.claim(ids[1])
    assert stale is not None
    with Session(engine) as db, db.begin():
        row = db.get(ProjectAttachment, ids[2])
        row.attempt_count = 3
        row.next_attempt_at = datetime.now(UTC)
        row.last_error_code = "unavailable"
    migrate(engine, "20261002_0010")
    with engine.begin() as db:
        turns = Table("chat_turns", MetaData(), autoload_with=db)
        selections = Table("chat_turn_pdf_selections", MetaData(), autoload_with=db)
        receipts = Table("chat_submission_receipts", MetaData(), autoload_with=db)
        turn_id = db.scalar(select(turns.c.id))
        identity = ids[0].hex if engine.dialect.name == "sqlite" else ids[0]
        db.execute(
            selections.insert().values(
                turn_id=turn_id, position=0, attachment_id=identity, expected_sha256="b" * 64
            )
        )
        db.execute(
            receipts.insert().values(
                turn_id=turn_id, call=1, request_sha256="c" * 64, status="sent"
            )
        )
    before = history(engine)
    old_attachments = snapshot(engine, "project_attachments")
    old_selections = snapshot(engine, "chat_turn_pdf_selections")
    old_receipts = snapshot(engine, "chat_submission_receipts")
    migrate(engine, "20261014_0011")
    assert history(engine) == before
    assert snapshot(engine, "chat_submission_receipts") == old_receipts
    assert [tuple(row)[:-1] for row in snapshot(engine, "chat_turn_pdf_selections")] == [
        tuple(row) for row in old_selections
    ]
    assert all(
        row.reference_kind == "legacy-text-v1"
        for row in snapshot(engine, "chat_turn_pdf_selections")
    )
    cleared = {
        "status",
        "failure_code",
        "attempt_count",
        "lease_id",
        "lease_until",
        "next_attempt_at",
        "last_error_code",
    }
    new_attachments = snapshot(engine, "project_attachments")
    assert [
        {k: v for k, v in row._mapping.items() if k not in cleared} for row in new_attachments
    ] == [
        {k: v for k, v in row._mapping.items() if k not in cleared} for row in old_attachments
    ]  # Both blobs, metadata, ownership and created_at preserved exactly.
    with Session(engine) as db:
        for attachment_id in ids:
            row = db.get(ProjectAttachment, attachment_id)
            assert row.status == "stored" and row.original == BODY
            assert row.attempt_count == 0 and row.lease_id is None and row.lease_until is None
            assert row.next_attempt_at is None and row.last_error_code is None
        row = db.get(ProjectAttachment, failed_id)
        assert row.status == "failed" and row.failure_code == "no_text" and row.original is None
    # Old rejection would clear the original if its status/token CAS still matched.
    assert processor.complete(stale, rejected("invalid")) is False
    assert processor.complete(stale, rejected("unavailable")) is False
    assert all(processor.claim(attachment_id) is None for attachment_id in ids)
    processor.tick()
    processor.extractor.extract.assert_not_called()
    assert snapshot(engine, "project_attachments") == new_attachments
    for field, value in (("attempt_count", 1), ("next_attempt_at", datetime.now(UTC))):
        with Session(engine) as db, pytest.raises(IntegrityError):
            setattr(db.get(ProjectAttachment, ids[0]), field, value)
            db.commit()
    with pytest.raises(RuntimeError, match="cannot be downgraded"):
        migrate(engine, "20261002_0010", downgrade=True)


def test_native_transition_preserves_data_and_rejects_stale_completions(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'native-transition.db'}")
    try:
        check_native_transition(engine)
    finally:
        engine.dispose()
