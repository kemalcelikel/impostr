from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.database import database_url_from_environment
from app.db import Base
from app.models import (
    AuditEvent,
    DocumentConflictProposal,
    Project,
    ProjectApprovalManifest,
    ProjectDocument,
    ProjectDocumentPairApproval,
    ProjectDocumentRevision,
    User,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("IMPOSTR_TEST_POSTGRES") != "1",
    reason="requires the disposable PostgreSQL integration profile",
)


@pytest.fixture
def schema_engine() -> Iterator[Engine]:
    """Exercise migrations in an owned schema, never downgrade the public schema."""
    schema = f"imp020_{uuid.uuid4().hex}"
    url = database_url_from_environment()
    control = create_engine(
        url, connect_args={"connect_timeout": 3}, hide_parameters=True, poolclass=NullPool
    )
    engine = create_engine(
        url,
        connect_args={"connect_timeout": 3, "options": f"-csearch_path={schema}"},
        hide_parameters=True,
        poolclass=NullPool,
    )
    created = False
    try:
        with control.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        yield engine
    finally:
        engine.dispose()
        try:
            if created:
                with control.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                    assert (
                        connection.scalar(
                            text("SELECT count(*) FROM pg_namespace WHERE nspname = :schema"),
                            {"schema": schema},
                        )
                        == 0
                    )
        finally:
            control.dispose()


def _migrate(engine: Engine, target: str, *, downgrade: bool = False) -> None:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(str(api_directory / "alembic.ini"))
    config.set_main_option("script_location", str(api_directory / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if downgrade:
            command.downgrade(config, target)
        else:
            command.upgrade(config, target)


def _assert_head_matches_orm(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260930_0006"
        )
        assert (
            compare_metadata(
                MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata
            )
            == []
        )


def _history(engine: Engine) -> dict[str, list[tuple]]:
    tables = (
        User,
        Project,
        ProjectDocument,
        ProjectDocumentRevision,
        ProjectDocumentPairApproval,
        DocumentConflictProposal,
        AuditEvent,
    )
    with engine.connect() as connection:
        return {
            model.__tablename__: [
                tuple(row) for row in connection.execute(select(model.__table__).order_by(model.id))
            ]
            for model in tables
        }


def test_fresh_postgres_manifest_schema_matches_orm(schema_engine: Engine) -> None:
    _migrate(schema_engine, "head")
    _assert_head_matches_orm(schema_engine)
    with Session(schema_engine) as db:
        assert db.scalar(select(ProjectApprovalManifest.id)) is None
        assert db.scalar(select(ProjectDocumentPairApproval.id)) is None


def test_postgres_manifest_migration_preserves_history_and_enforces_snapshot_constraints(
    schema_engine: Engine,
) -> None:
    _migrate(schema_engine, "20260929_0005")
    now = datetime.now(UTC)
    owner_id, project_id, other_project_id, pair_id = [uuid.uuid4() for _ in range(4)]
    documents = {kind: uuid.uuid4() for kind in ("project", "agents", "backlog")}
    revisions = {kind: uuid.uuid4() for kind in documents}
    old_project_revision = uuid.uuid4()
    with Session(schema_engine) as db, db.begin():
        db.add(
            User(
                id=owner_id,
                username="schema-test-owner",
                password_hash="synthetic-schema-test-only-hash",
                role="user",
                is_active=True,
                created_at=now,
                password_changed_at=now,
            )
        )
        db.flush()
        db.add_all(
            [
                Project(id=project_id, name="Schema preservation", owner_user_id=owner_id),
                Project(id=other_project_id, name="Other schema project", owner_user_id=owner_id),
            ]
        )
        db.flush()
        db.add_all(
            ProjectDocument(
                id=identifier,
                project_id=project_id,
                kind=kind,
                head_revision_number=2 if kind == "project" else 1,
            )
            for kind, identifier in documents.items()
        )
        db.flush()
        for kind, identifier, number in (
            ("project", old_project_revision, 1),
            *(
                (kind, identifier, 2 if kind == "project" else 1)
                for kind, identifier in revisions.items()
            ),
        ):
            content = f"# Preserved {kind} revision {number}\n"
            db.add(
                ProjectDocumentRevision(
                    id=identifier,
                    document_id=documents[kind],
                    revision_number=number,
                    content=content,
                    content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                    origin="human",
                    author_user_id=owner_id,
                    created_at=now,
                )
            )
        db.flush()
        db.add(
            ProjectDocumentPairApproval(
                id=pair_id,
                project_id=project_id,
                project_revision_id=revisions["project"],
                agents_revision_id=revisions["agents"],
                actor_user_id=owner_id,
                created_at=now,
            )
        )
        content = "# Preserved losing edit\n"
        db.add(
            DocumentConflictProposal(
                document_id=documents["project"],
                expected_revision_number=1,
                observed_revision_number=2,
                content=content,
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                author_user_id=owner_id,
                created_at=now,
            )
        )
        db.add(
            AuditEvent(
                actor_kind="user",
                actor_user_id=owner_id,
                action="project.document_pair.approved",
                project_id=project_id,
                details={"pair_approval_id": str(pair_id)},
                created_at=now,
            )
        )
    history = _history(schema_engine)
    _migrate(schema_engine, "head")
    _assert_head_matches_orm(schema_engine)
    assert _history(schema_engine) == history
    with Session(schema_engine) as db:
        assert db.scalar(select(ProjectApprovalManifest.id)) is None

    snapshot = {
        "project_id": project_id,
        "pair_approval_id": pair_id,
        "project_revision_id": revisions["project"],
        "agents_revision_id": revisions["agents"],
        "backlog_revision_id": revisions["backlog"],
        "actor_user_id": owner_id,
        "created_at": now,
    }
    pair_constraint = "fk_project_approval_manifests_pair_snapshot"
    for changes, constraint in (
        ({"project_id": other_project_id}, pair_constraint),
        ({"project_revision_id": old_project_revision}, pair_constraint),
        ({"agents_revision_id": revisions["project"]}, pair_constraint),
        ({"pair_approval_id": uuid.uuid4()}, pair_constraint),
        ({"backlog_revision_id": uuid.uuid4()}, None),
    ):
        with Session(schema_engine) as db:
            with pytest.raises(IntegrityError) as failure, db.begin():
                db.add(ProjectApprovalManifest(**(snapshot | changes)))
                db.flush()
            assert failure.value.orig.sqlstate == "23503"
            if constraint is not None:
                assert failure.value.orig.diag.constraint_name == constraint

    manifest_id = uuid.uuid4()
    with Session(schema_engine) as db, db.begin():
        db.add(ProjectApprovalManifest(id=manifest_id, **snapshot))
    with Session(schema_engine) as db:
        manifest = db.get(ProjectApprovalManifest, manifest_id)
        assert manifest is not None
        assert all(getattr(manifest, key) == value for key, value in snapshot.items())
        with pytest.raises(IntegrityError) as failure:
            db.add(ProjectApprovalManifest(**snapshot))
            db.flush()
        db.rollback()
        assert failure.value.orig.sqlstate == "23505"
        assert failure.value.orig.diag.constraint_name == "uq_project_approval_manifest_snapshot"

    _migrate(schema_engine, "20260929_0005", downgrade=True)
    assert _history(schema_engine) == history
    with schema_engine.connect() as connection:
        inspector = inspect(connection)
        assert "project_approval_manifests" not in inspector.get_table_names()
        assert "uq_project_pair_approval_snapshot" not in {
            item["name"]
            for item in inspector.get_unique_constraints("project_document_pair_approvals")
        }
    _migrate(schema_engine, "head")
    _assert_head_matches_orm(schema_engine)
    assert _history(schema_engine) == history
    with Session(schema_engine) as db:
        assert db.scalar(select(ProjectApprovalManifest.id)) is None
