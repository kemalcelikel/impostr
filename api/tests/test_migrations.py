from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.main import create_app
from app.models import (
    BootstrapState,
    Project,
    ProjectApprovalManifest,
    ProjectDocument,
    ProjectDocumentPairApproval,
    ProjectDocumentRevision,
    User,
)
from app.project_names import project_name_key
from app.project_templates import default_template_root


def _alembic_config() -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(str(api_directory / "alembic.ini"))
    config.set_main_option("script_location", str(api_directory / "migrations"))
    return config


def test_identity_and_private_metadata_migration_upgrades_and_downgrades(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration.db'}")
    config = _alembic_config()

    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            table_names = set(inspect(connection).get_table_names())
            assert {
                "users",
                "web_sessions",
                "rate_limit_buckets",
                "audit_events",
                "projects",
                "bootstrap_state",
                "project_documents",
                "project_document_revisions",
                "project_document_pair_approvals",
                "project_approval_manifests",
                "document_conflict_proposals",
            }.issubset(table_names)
            assert connection.scalar(select(BootstrapState.completed)) is False
            inspector = inspect(connection)
            manifest_columns = {
                column["name"] for column in inspector.get_columns("project_approval_manifests")
            }
            assert {
                "id",
                "project_id",
                "pair_approval_id",
                "project_revision_id",
                "agents_revision_id",
                "backlog_revision_id",
                "actor_user_id",
                "created_at",
            } == manifest_columns
            manifest_uniques = {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints("project_approval_manifests")
            }
            assert ("project_id", "pair_approval_id", "backlog_revision_id") in manifest_uniques
            pair_uniques = {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints(
                    "project_document_pair_approvals"
                )
            }
            assert ("id", "project_id", "project_revision_id", "agents_revision_id") in pair_uniques
            manifest_foreign_keys = inspector.get_foreign_keys("project_approval_manifests")
            assert any(
                constraint["constrained_columns"]
                == ["pair_approval_id", "project_id", "project_revision_id", "agents_revision_id"]
                and constraint["referred_table"] == "project_document_pair_approvals"
                and constraint["referred_columns"]
                == ["id", "project_id", "project_revision_id", "agents_revision_id"]
                for constraint in manifest_foreign_keys
            )

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "20260929_0005")
            assert "project_approval_manifests" not in set(inspect(connection).get_table_names())
            remaining_pair_uniques = {
                tuple(constraint["column_names"])
                for constraint in inspect(connection).get_unique_constraints(
                    "project_document_pair_approvals"
                )
            }
            assert (
                "id",
                "project_id",
                "project_revision_id",
                "agents_revision_id",
            ) not in remaining_pair_uniques

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()


def test_manifest_migration_preserves_existing_pair_approval_without_backfill(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'manifest-migration.db'}")
    config = _alembic_config()
    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    project_document_id = uuid.uuid4()
    agents_document_id = uuid.uuid4()
    project_revision_id = uuid.uuid4()
    agents_revision_id = uuid.uuid4()
    pair_approval_id = uuid.uuid4()
    now = datetime.now(UTC).replace(tzinfo=None)

    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "20260929_0005")

        with Session(engine) as db, db.begin():
            db.add(
                User(
                    id=owner_id,
                    username="migration-owner",
                    password_hash="migration-test-only-hash",
                    role="user",
                    is_active=True,
                    created_at=now,
                    password_changed_at=now,
                )
            )
            db.add(Project(id=project_id, name="Manifest migration", owner_user_id=owner_id))
            db.add_all(
                [
                    ProjectDocument(
                        id=project_document_id,
                        project_id=project_id,
                        kind="project",
                        head_revision_number=1,
                        created_at=now,
                    ),
                    ProjectDocument(
                        id=agents_document_id,
                        project_id=project_id,
                        kind="agents",
                        head_revision_number=1,
                        created_at=now,
                    ),
                ]
            )
            db.add_all(
                [
                    ProjectDocumentRevision(
                        id=project_revision_id,
                        document_id=project_document_id,
                        revision_number=1,
                        content="# Saved project\n",
                        content_sha256="1" * 64,
                        origin="human",
                        author_user_id=owner_id,
                        created_at=now,
                    ),
                    ProjectDocumentRevision(
                        id=agents_revision_id,
                        document_id=agents_document_id,
                        revision_number=1,
                        content="# Saved rules\n",
                        content_sha256="2" * 64,
                        origin="human",
                        author_user_id=owner_id,
                        created_at=now,
                    ),
                ]
            )
            db.add(
                ProjectDocumentPairApproval(
                    id=pair_approval_id,
                    project_id=project_id,
                    project_revision_id=project_revision_id,
                    agents_revision_id=agents_revision_id,
                    actor_user_id=owner_id,
                    created_at=now,
                )
            )

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        with Session(engine) as db:
            pair = db.get(ProjectDocumentPairApproval, pair_approval_id)
            assert pair is not None
            assert pair.project_id == project_id
            assert pair.project_revision_id == project_revision_id
            assert pair.agents_revision_id == agents_revision_id
            assert (
                db.scalar(
                    select(ProjectApprovalManifest.id).where(
                        ProjectApprovalManifest.project_id == project_id
                    )
                )
                is None
            )

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "20260929_0005")
            assert "project_approval_manifests" not in set(inspect(connection).get_table_names())

        with Session(engine) as db:
            assert db.get(ProjectDocumentPairApproval, pair_approval_id) is not None
    finally:
        engine.dispose()


def test_document_migration_preserves_legacy_projects_and_backfills_drafts(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'legacy-migration.db'}")
    config = _alembic_config()
    user_id = uuid.uuid4()
    project_ids = [uuid.uuid4(), uuid.uuid4()]
    now = datetime.now(UTC).replace(tzinfo=None)
    repository_root = default_template_root()
    workspace_root = tmp_path / "legacy-workspaces"
    settings = AppSettings(
        public_origin="http://127.0.0.1:8080",
        rate_limit_key=b"migration-test-rate-limit-key-not-secret",
    )

    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "20260925_0002")
            metadata = MetaData()
            users = Table("users", metadata, autoload_with=connection)
            projects = Table("projects", metadata, autoload_with=connection)
            connection.execute(
                users.insert(),
                {
                    "id": user_id.hex,
                    "username": "legacy-owner",
                    "password_hash": "not-used-for-migration-test",
                    "role": "user",
                    "is_active": True,
                    "created_at": now,
                    "password_changed_at": now,
                },
            )
            connection.execute(
                projects.insert(),
                [
                    {
                        "id": project_id.hex,
                        "name": name,
                        "owner_user_id": user_id.hex,
                        "created_at": now,
                    }
                    for project_id, name in zip(
                        project_ids, ("ﷺ" * 120, "ﷺ" * 119 + "ﷲ"), strict=True
                    )
                ],
            )

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            columns = {
                column["name"]: column for column in inspect(connection).get_columns("projects")
            }
            assert columns["name_key"]["nullable"] is False
            rows = connection.execute(
                select(Project.id, Project.name, Project.name_key).order_by(Project.name)
            ).all()
            assert {row.id for row in rows} == set(project_ids)
            assert {row.name for row in rows} == {"ﷺ" * 120, "ﷺ" * 119 + "ﷲ"}
            assert len({row.name_key for row in rows}) == 2
            assert {row.name_key for row in rows} == {
                project_name_key("ﷺ" * 120),
                project_name_key("ﷺ" * 119 + "ﷲ"),
            }
            assert all(len(row.name_key) == 64 for row in rows)
            assert connection.scalar(select(ProjectDocument.id).limit(1)) is None

        # Legacy metadata has no revision history to migrate. At application start,
        # each row receives current root-template revision one without changing its
        # original id, name, owner, or timestamp. Workspace copies are lazy.
        with TestClient(
            create_app(
                engine,
                settings,
                workspace_root=workspace_root,
                template_root=repository_root,
            )
        ):
            with Session(engine) as db:
                legacy_projects = list(
                    db.scalars(select(Project).order_by(Project.name, Project.id)).all()
                )
                assert {project.id for project in legacy_projects} == set(project_ids)
                assert {project.name for project in legacy_projects} == {
                    "ﷺ" * 120,
                    "ﷺ" * 119 + "ﷲ",
                }
                assert all(project.owner_user_id == user_id for project in legacy_projects)
                assert all(project.created_at is not None for project in legacy_projects)
                documents = list(db.scalars(select(ProjectDocument)).all())
                assert len(documents) == 6
                revisions = list(db.scalars(select(ProjectDocumentRevision)).all())
                assert len(revisions) == 6
                assert all(revision.revision_number == 1 for revision in revisions)
                assert all(revision.origin == "template" for revision in revisions)
                # Historical drafts are not silently converted into human approvals.
                assert db.scalar(select(ProjectDocumentPairApproval.id).limit(1)) is None
            assert not workspace_root.exists()

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()
