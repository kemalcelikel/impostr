"""Coordinator-only verifier: one fresh owned schema, no extractor/runtime dispatch.

Use the existing disposable api-integration-check profile, after boundary review:
python -m pytest -p no:cacheprovider tests/test_attachments_postgres.py
This agent does not run it or read database configuration. No public-schema downgrade.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from test_attachments import check_overcap, check_roundtrip, setup_intake
from test_attachments_migration import check_preservation

from app.config import AppSettings
from app.database import database_url_from_environment
from app.main import create_app
from app.models import ProjectAttachment, User
from app.passwords import hash_password

pytestmark = pytest.mark.skipif(
    os.environ.get("IMPOSTR_TEST_POSTGRES") != "1",
    reason="requires fresh coordinator-owned PostgreSQL integration profile",
)

POSTGRES_STAGES = (
    "schema_create",
    "preservation_base_migration",
    "preservation_seed",
    "preservation_snapshot",
    "preservation_upgrade",
    "preservation_history",
    "preservation_original",
    "preservation_retained_downgrade",
    "preservation_constraint_size_cap",
    "preservation_constraint_size_match",
    "preservation_constraint_failed_blob",
    "preservation_constraint_ready",
    "preservation_constraint_lease",
    "preservation_delete",
    "preservation_empty_downgrade",
    "preservation_reupgrade",
    "schema_types",
    "schema_conversation_fk",
    "api_account",
    "api_startup",
    "api_setup",
    "roundtrip_upload",
    "roundtrip_stored_original",
    "roundtrip_raw",
    "roundtrip_stored_metadata",
    "roundtrip_delete",
    "overcap_upload",
    "overcap_discarded_blob",
    "overcap_metadata",
    "overcap_recovery",
    "api_shutdown",
    "owned_cleanup",
    "unknown",
)


def report_failure(stage, error):
    """Fixed categories only; never format exception/SQL/assertion contents."""
    category = (
        "assertion"
        if isinstance(error, AssertionError)
        else "expected_exception_missing"
        if isinstance(error, pytest.fail.Exception)
        else "integrity"
        if isinstance(error, IntegrityError)
        else "database"
        if isinstance(error, SQLAlchemyError)
        else "filesystem"
        if isinstance(error, OSError)
        else "unexpected"
    )
    message = json.dumps(
        {
            "diagnostic": "imp017_intake_postgres",
            "stage": stage if stage in POSTGRES_STAGES else "unknown",
            "category": category,
        }
    )
    # Keep the marker standalone even after pytest's progress prefix.
    print("\n" + message, flush=True)


def test_fresh_postgres_intake_migration_api_and_owned_cleanup(tmp_path: Path):
    schema = "imp017_" + uuid.uuid4().hex
    url = database_url_from_environment()
    control = create_engine(
        url, hide_parameters=True, connect_args={"connect_timeout": 3}, poolclass=NullPool
    )
    engine = create_engine(
        url,
        hide_parameters=True,
        poolclass=NullPool,
        connect_args={"connect_timeout": 3, "options": f"-csearch_path={schema}"},
    )
    created = False
    stage = "schema_create"

    def mark(checkpoint):
        nonlocal stage
        stage = checkpoint

    try:
        with control.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        owner_id, _, conversation_id = check_preservation(engine, stage=mark)
        mark("schema_types")
        with engine.connect() as connection:
            columns = {
                column["name"]: column
                for column in inspect(connection).get_columns("project_attachments")
            }
            assert str(columns["original"]["type"]) == "BYTEA"
            assert "text_content" not in columns
        # Composite FK rejects a real existing conversation under a different project.
        mark("schema_conversation_fk")
        with Session(engine) as db, pytest.raises(IntegrityError):
            db.add(
                ProjectAttachment(
                    project_id=uuid.uuid4(),
                    conversation_id=conversation_id,
                    uploader_user_id=owner_id,
                    filename="wrong.pdf",
                    status="failed",
                    failure_code="invalid",
                )
            )
            db.commit()
        mark("api_account")
        with Session(engine) as db, db.begin():
            db.add(
                User(
                    username="pdf-owner",
                    password_hash=hash_password("synthetic PDF passphrase"),
                    role="user",
                    is_active=True,
                )
            )
        settings = AppSettings(
            public_origin="http://127.0.0.1:8080",
            rate_limit_key=b"synthetic-pdf-postgres-not-secret",
            chat_enabled=False,
        )
        mark("api_startup")
        with TestClient(
            create_app(engine, settings, workspace_root=tmp_path / "workspace")
        ) as client:
            mark("api_setup")
            _, _, base = setup_intake(client)
            check_roundtrip(client, engine, base, stage=mark)
            check_overcap(client, engine, base, declared="1", stage=mark)
            mark("api_shutdown")
    except BaseException as error:
        report_failure(stage, error)
        raise
    finally:
        try:
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
        except BaseException as error:
            report_failure("owned_cleanup", error)
            raise
