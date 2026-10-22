"""0007 -> 0009 PDF schema preservation/guards, using the SQLite test seam."""

from __future__ import annotations

import uuid

import pytest
from alembic import command
from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_migrations import _alembic_config

from app.models import (
    ChatEvent,
    ChatTurn,
    Conversation,
    Project,
    ProjectApprovalManifest,
    ProjectAttachment,
    ProjectDocument,
    ProjectDocumentPairApproval,
    ProjectDocumentRevision,
    User,
)

INTAKE_HEAD = "20261002_0009"


def seed_history(engine):
    owner_id, project_id, conversation_id = (uuid.uuid4() for _ in range(3))
    with Session(engine) as db, db.begin():
        db.add(
            User(
                id=owner_id,
                username="pdf-migration",
                password_hash="synthetic-unused",
                role="user",
                is_active=True,
            )
        )
        db.flush()
        db.add(Project(id=project_id, owner_user_id=owner_id, name="Preserved PDF history"))
        db.flush()
        revisions = {}
        for kind in ("project", "agents", "backlog"):
            document = ProjectDocument(project_id=project_id, kind=kind)
            db.add(document)
            db.flush()
            revision = ProjectDocumentRevision(
                document_id=document.id,
                revision_number=1,
                content=f"# Preserved {kind}",
                content_sha256="a" * 64,
                origin="human",
                author_user_id=owner_id,
            )
            db.add(revision)
            db.flush()
            revisions[kind] = revision.id
        pair = ProjectDocumentPairApproval(
            project_id=project_id,
            project_revision_id=revisions["project"],
            agents_revision_id=revisions["agents"],
            actor_user_id=owner_id,
        )
        db.add(pair)
        db.flush()
        db.add(
            ProjectApprovalManifest(
                project_id=project_id,
                pair_approval_id=pair.id,
                project_revision_id=revisions["project"],
                agents_revision_id=revisions["agents"],
                backlog_revision_id=revisions["backlog"],
                actor_user_id=owner_id,
            )
        )
        db.add(
            Conversation(
                id=conversation_id,
                project_id=project_id,
                creator_user_id=owner_id,
                title="Preserved conversation",
            )
        )
        db.flush()
        # Seed the actual pre-0010 schema, not an ORM INSERT containing future
        # submission columns. This helper deliberately runs before upgrade.
        turn_id = uuid.uuid4()
        turns = Table("chat_turns", MetaData(), autoload_with=db.connection())

        def identity(value):
            return value.hex if engine.dialect.name == "sqlite" else value

        db.execute(
            turns.insert().values(
                id=identity(turn_id),
                project_id=identity(project_id),
                conversation_id=identity(conversation_id),
                request_id=identity(uuid.uuid4()),
                actor_user_id=identity(owner_id),
                web_session_hash=b"a" * 32,
                prompt="Preserved chat",
                payload={"synthetic": "preserved"},
                state="completed",
                event_count=0,
                broker_cursor=0,
                output_bytes=0,
            )
        )
        db.add(
            ChatEvent(
                conversation_id=conversation_id,
                turn_id=turn_id,
                sequence=1,
                kind="completed",
                data={"preserved": True},
            )
        )
    return owner_id, project_id, conversation_id


def history(engine):
    tables = (
        User,
        Project,
        ProjectDocument,
        ProjectDocumentRevision,
        ProjectDocumentPairApproval,
        ProjectApprovalManifest,
        Conversation,
        ChatTurn,
        ChatEvent,
    )
    with engine.connect() as connection:
        added_turn_columns = {
            "submission_state",
            "dispatch_rendered_sha256",
            "dispatch_manifest_sha256",
            "dispatch_manifest",
            "receipt_pending",
            "stop_confirmed",
        }
        return {
            model.__tablename__: connection.execute(
                select(
                    *[
                        column
                        for column in model.__table__.columns
                        if model is not ChatTurn or column.name not in added_turn_columns
                    ]
                ).order_by(model.id)
            ).all()
            for model in tables
        }


def migrate(engine, target, downgrade=False):
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, target)


def check_preservation(engine, stage=lambda _: None):
    stage("preservation_base_migration")
    migrate(engine, "20261001_0007")
    stage("preservation_seed")
    ids = seed_history(engine)
    stage("preservation_snapshot")
    before = history(engine)
    stage("preservation_upgrade")
    # This historical attachment-only fixture stops at its actual schema slice.
    # Following head would first downgrade 0010 before 0009 rejects attachment
    # loss; SQLite's nontransactional DDL can then leave a partially downgraded
    # schema. The dedicated selection migration test exercises 0010 separately.
    migrate(engine, INTAKE_HEAD)
    stage("preservation_history")
    assert history(engine) == before
    with engine.connect() as connection:
        assert "project_attachments" in inspect(connection).get_table_names()
    owner_id, project_id, conversation_id = ids
    stage("preservation_original")
    with Session(engine) as db, db.begin():
        row = ProjectAttachment(
            project_id=project_id,
            conversation_id=conversation_id,
            uploader_user_id=owner_id,
            filename="reference.pdf",
            original=b"%PDF-test",
            original_size=9,
            original_sha256="a" * 64,
            status="pending",  # Historical 0009 schema precedes native storage.
        )
        db.add(row)
        db.flush()
        attachment_id = row.id
    stage("preservation_retained_downgrade")
    with pytest.raises(RuntimeError, match="Cannot discard retained attachments"):
        migrate(engine, "20261001_0007", downgrade=True)
    with Session(engine) as db:
        assert db.get(ProjectAttachment, attachment_id).original == b"%PDF-test"
    assert history(engine) == before
    for checkpoint, changes in (
        ("preservation_constraint_size_cap", {"original_size": 50_000_001}),
        ("preservation_constraint_size_match", {"original_size": 8}),
        ("preservation_constraint_failed_blob", {"status": "failed", "failure_code": "invalid"}),
        ("preservation_constraint_ready", {"status": "ready"}),
        ("preservation_constraint_lease", {"status": "processing"}),
    ):
        stage(checkpoint)
        with Session(engine) as db, pytest.raises(IntegrityError):
            row = db.get(ProjectAttachment, attachment_id)
            for key, value in changes.items():
                setattr(row, key, value)
            db.commit()
    stage("preservation_delete")
    with Session(engine) as db, db.begin():
        db.delete(db.get(ProjectAttachment, attachment_id))
    stage("preservation_empty_downgrade")
    migrate(engine, "20261001_0007", downgrade=True)
    assert history(engine) == before
    stage("preservation_reupgrade")
    # Joined PostgreSQL/API callers need the current schema after the historical
    # downgrade guards have finished, with no retained attachment to discard.
    migrate(engine, "head")
    return ids


def test_pdf_intake_migration_preserves_approvals_chat_and_rejects_loss(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'pdf-migration.db'}")
    try:
        check_preservation(engine)
    finally:
        engine.dispose()
