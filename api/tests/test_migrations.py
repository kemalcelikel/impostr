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
from app.models import BootstrapState, Project, ProjectDocument, ProjectDocumentRevision
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
                "document_conflict_proposals",
            }.issubset(table_names)
            assert connection.scalar(select(BootstrapState.completed)) is False

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
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
            assert not workspace_root.exists()

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()
