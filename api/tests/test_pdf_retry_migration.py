"""0008 accepted pending bytes survive retry-schema upgrade and restart leases."""

import pytest
from sqlalchemy import create_engine, inspect, text
from test_attachments_migration import history, migrate, seed_history


def test_0008_pending_bytes_preserved_and_lossy_downgrade_denied(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'retry-migration.db'}")
    try:
        migrate(engine, "20261002_0008")
        owner, project, conversation = seed_history(engine)
        before = history(engine)
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO project_attachments "
                    "(id, project_id, conversation_id, uploader_user_id, "
                    "filename, status, original, original_size, original_sha256, attempt_count) "
                    "VALUES (:id, :project, :conversation, :owner, 'reference.pdf', 'pending', "
                    ":body, 9, :digest, 0)"
                ),
                {
                    "id": "b" * 32,
                    "project": project.hex,
                    "conversation": conversation.hex,
                    "owner": owner.hex,
                    "body": b"%PDF-test",
                    "digest": "a" * 64,
                },
            )
        migrate(engine, "head")
        assert history(engine) == before
        with engine.connect() as db:
            row = db.execute(
                text(
                    "SELECT original, status, attempt_count, next_attempt_at, "
                    "last_error_code FROM project_attachments"
                )
            ).one()
            assert tuple(row) == (b"%PDF-test", "pending", 0, None, None)
        with pytest.raises(RuntimeError, match="Cannot discard retained attachments"):
            migrate(engine, "20261002_0008", downgrade=True)
        with engine.begin() as db:
            db.execute(text("DELETE FROM project_attachments"))
        migrate(engine, "20261002_0008", downgrade=True)
        with engine.connect() as db:
            assert "next_attempt_at" not in {
                c["name"] for c in inspect(db).get_columns("project_attachments")
            }
        assert history(engine) == before
        migrate(engine, "head")
    finally:
        engine.dispose()
