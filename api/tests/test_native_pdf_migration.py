"""Forward migration preservation using real historical schema, no extractor imports.

Helpers accept only an explicitly supplied fresh coordinator-owned engine. They do
not discover credentials, launch Docker or use a worker/provider. Original hashes,
history and metadata-only legacy/native receipts are compared across the upgrade.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_attachments_migration import history, migrate, seed_history

from app.models import ProjectAttachment

BODY = b"%PDF-synthetic-native-transition"
RETIRED_COLUMNS = {
    "text_content",
    "text_size",
    "text_sha256",
    "page_count",
    "missing_pages",
    "extraction_policy",
    "qpdf_version",
    "pdftotext_version",
    "extractor_build_sha256",
    "attempt_count",
    "lease_id",
    "lease_until",
    "next_attempt_at",
    "last_error_code",
}


def snapshot(engine, table_name):
    with engine.connect() as db:
        table = Table(table_name, MetaData(), autoload_with=db)
        return db.execute(select(table).order_by(*table.primary_key)).all()


def check_native_transition(engine):
    migrate(engine, "20261002_0009")
    owner, project, conversation = seed_history(engine)
    ids = [uuid.uuid4() for _ in range(4)]
    stale_token = uuid.uuid4()
    now = datetime.now(UTC)

    def identity(value):
        return value.hex if engine.dialect.name == "sqlite" else value

    with engine.begin() as db:
        table = Table("project_attachments", MetaData(), autoload_with=db)
        for attachment_id, status in zip(
            ids, ("ready", "processing", "pending", "failed"), strict=True
        ):
            values = dict(
                id=identity(attachment_id),
                project_id=identity(project),
                conversation_id=identity(conversation),
                uploader_user_id=identity(owner),
                filename="retained.pdf",
                status=status,
                attempt_count=1,
                original=BODY,
                original_size=len(BODY),
                original_sha256=hashlib.sha256(BODY).hexdigest(),
            )
            if status == "ready":
                content = "Synthetic legacy text\f"
                values.update(
                    text_content=content,
                    text_size=len(content.encode()),
                    text_sha256=hashlib.sha256(content.encode()).hexdigest(),
                    page_count=1,
                    missing_pages=[],
                    extraction_policy="imp017-text-v1",
                    qpdf_version="11.3.0",
                    pdftotext_version="22.12.0",
                    extractor_build_sha256="a" * 64,
                )
            elif status == "processing":
                values.update(lease_id=identity(stale_token), lease_until=now + timedelta(seconds=60))
            elif status == "pending":
                values.update(attempt_count=3, next_attempt_at=now, last_error_code="unavailable")
            else:
                values.update(original=None, failure_code="no_text")
            db.execute(table.insert().values(**values))
    migrate(engine, "20261002_0010")
    with engine.begin() as db:
        turns = Table("chat_turns", MetaData(), autoload_with=db)
        selections = Table("chat_turn_pdf_selections", MetaData(), autoload_with=db)
        receipts = Table("chat_submission_receipts", MetaData(), autoload_with=db)
        turn_id = db.scalar(select(turns.c.id))
        db.execute(
            selections.insert().values(
                turn_id=turn_id,
                position=0,
                attachment_id=identity(ids[0]),
                expected_sha256="b" * 64,
            )
        )
        for call, status in enumerate(("sent", "uncertain"), 1):
            db.execute(
                receipts.insert().values(
                    turn_id=turn_id, call=call, request_sha256="c" * 64, status=status
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
    ]  # Originals and derivatives still preserved at the immutable 0011 boundary.
    assert all(
        row.status == "stored"
        and row.attempt_count == 0
        and row.lease_id is None
        and row.lease_until is None
        and row.next_attempt_at is None
        and row.last_error_code is None
        for row in new_attachments
        if row.original is not None
    )
    assert all(
        row.status == "failed" and row.failure_code == "no_text"
        for row in new_attachments
        if row.original is None
    )
    # Exercise the actual old completion predicate without importing retired code.
    with engine.begin() as db:
        table = Table("project_attachments", MetaData(), autoload_with=db)
        completed = db.execute(
            table.update()
            .where(
                table.c.id == identity(ids[1]),
                table.c.status == "processing",
                table.c.lease_id == identity(stale_token),
                table.c.lease_until > now,
            )
            .values(status="failed", failure_code="invalid", original=None)
        )
        assert completed.rowcount == 0
    assert snapshot(engine, "project_attachments") == new_attachments
    for field, value in (("attempt_count", 1), ("next_attempt_at", now)):
        with engine.begin() as db, pytest.raises(IntegrityError):
            table = Table("project_attachments", MetaData(), autoload_with=db)
            db.execute(table.update().where(table.c.id == identity(ids[0])).values(**{field: value}))


def check_extractor_retirement(engine, *, populated=True):
    if populated:
        check_native_transition(engine)
        migrate(engine, "20261014_0012")
        with engine.begin() as db:
            turns = Table("chat_turns", MetaData(), autoload_with=db)
            turn = db.execute(select(turns)).one()
            selections = Table("chat_turn_pdf_selections", MetaData(), autoload_with=db)
            grants = Table("chat_send_authorizations", MetaData(), autoload_with=db)
            receipts = Table("chat_submission_receipts", MetaData(), autoload_with=db)
            deletions = Table("attachment_deletions", MetaData(), autoload_with=db)
            purges = Table("attachment_purges", MetaData(), autoload_with=db)

            def identity(value):
                return value.hex if engine.dialect.name == "sqlite" else value

            attachment = next(
                row for row in snapshot(engine, "project_attachments") if row.original is not None
            )
            authorization = identity(uuid.uuid4())
            deleted = identity(uuid.uuid4())
            db.execute(
                selections.insert().values(
                    turn_id=turn.id,
                    position=1,
                    attachment_id=attachment.id,
                    expected_sha256=attachment.original_sha256,
                    reference_kind="native-original-v1",
                )
            )
            db.execute(
                grants.insert().values(
                    turn_id=turn.id,
                    call=3,
                    epoch=identity(uuid.uuid4()),
                    authorization_id=authorization,
                    request_sha256="d" * 64,
                    request_size=1234,
                    original_manifest_sha256="e" * 64,
                    expires_at=datetime.now(UTC) + timedelta(seconds=5),
                )
            )
            db.execute(
                receipts.insert().values(
                    turn_id=turn.id,
                    call=3,
                    status="sent",
                    request_sha256="d" * 64,
                    reference_kind="native-original-v1",
                    request_size=1234,
                    authorization_id=authorization,
                )
            )
            db.execute(
                deletions.insert().values(
                    attachment_id=deleted,
                    project_id=turn.project_id,
                    conversation_id=turn.conversation_id,
                    pending=True,
                )
            )
            db.execute(purges.insert().values(attachment_id=deleted, turn_id=turn.id))
    else:
        migrate(engine, "20261014_0012")
    # All non-attachment authoritative data must be byte/value identical, including
    # payload/dispatch JSON, legacy sent/uncertain receipts and cleanup tombstones.
    with engine.connect() as db:
        names = set(inspect(db).get_table_names()) - {"alembic_version", "project_attachments"}
    before = {name: snapshot(engine, name) for name in names}
    old_attachments = snapshot(engine, "project_attachments")
    migrate(engine, "head")
    assert {name: snapshot(engine, name) for name in names} == before
    new_attachments = snapshot(engine, "project_attachments")
    assert [dict(row._mapping) for row in new_attachments] == [
        {key: value for key, value in row._mapping.items() if key not in RETIRED_COLUMNS}
        for row in old_attachments
    ]
    with engine.connect() as db:
        assert {column["name"] for column in inspect(db).get_columns("project_attachments")} == {
            column.name for column in ProjectAttachment.__table__.columns
        }
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261022_0013"
    with Session(engine) as db:
        for row in db.scalars(select(ProjectAttachment)):
            if row.original is None:
                assert row.status == "failed" and row.failure_code == "no_text"
            else:
                assert row.status == "stored" and row.original == BODY
                assert hashlib.sha256(row.original).hexdigest() == row.original_sha256
    if populated:
        with engine.begin() as db, pytest.raises(IntegrityError):
            table = Table("project_attachments", MetaData(), autoload_with=db)
            db.execute(table.update().values(status="pending"))
    with pytest.raises(RuntimeError, match="cannot be recovered"):
        migrate(engine, "20261014_0012", downgrade=True)


@pytest.mark.parametrize("populated", [False, True])
def test_retirement_fresh_and_populated_preservation(tmp_path, populated):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'retirement.db'}")
    try:
        check_extractor_retirement(engine, populated=populated)
    finally:
        engine.dispose()
