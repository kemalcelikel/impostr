"""Additive 0010 preserves prior turns; replay selections cannot be downgraded away."""

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from test_attachments_migration import history, migrate, seed_history


def test_selection_migration_preservation_identity_and_lossy_downgrade_guard(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'pdf-selection.db'}")
    try:
        migrate(engine, "20261002_0009")
        seed_history(engine)
        before = history(engine)
        migrate(engine, "20261002_0010")  # Historical selection slice, not native transition.
        assert history(engine) == before
        with engine.connect() as db:
            turn_id = db.scalar(text("SELECT id FROM chat_turns"))
            assert db.scalar(text("SELECT count(*) FROM chat_turn_pdf_selections")) == 0
            assert (
                db.scalar(text("SELECT submission_state FROM chat_turns")) == "failed-before-send"
            )
            assert db.scalar(text("SELECT receipt_pending FROM chat_turns")) == 0
        # No attachment FK: an opaque deleted ID must remain durable request identity.
        attachment_id = uuid.uuid4().hex
        insert = text(
            "INSERT INTO chat_turn_pdf_selections "
            "(turn_id, position, attachment_id, expected_sha256) "
            "VALUES (:turn, :position, :attachment, :digest)"
        )
        params = {"turn": turn_id, "position": 0, "attachment": attachment_id, "digest": "a" * 64}
        with engine.begin() as db:
            db.execute(insert, params)
        for change in ({"position": 32}, {"position": 1, "digest": "short"}, {}):
            with pytest.raises(IntegrityError), engine.begin() as db:
                db.execute(insert, {**params, **change})
        with pytest.raises(RuntimeError, match="Cannot discard retained PDF turn selections"):
            migrate(engine, "20261002_0009", downgrade=True)
        with engine.begin() as db:
            db.execute(text("DELETE FROM chat_turn_pdf_selections"))
        receipt = text(
            "INSERT INTO chat_submission_receipts (turn_id, call, request_sha256, status) "
            "VALUES (:turn, :call, :hash, :status)"
        )
        for change in ({"call": 9}, {"status": "accepted"}, {"hash": None}):
            with pytest.raises(IntegrityError), engine.begin() as db:
                db.execute(
                    receipt,
                    {"turn": turn_id, "call": 1, "hash": "b" * 64, "status": "sent", **change},
                )
        with engine.begin() as db:
            db.execute(receipt, {"turn": turn_id, "call": 1, "hash": "b" * 64, "status": "sent"})
        with pytest.raises(RuntimeError, match="submission or cleanup proof"):
            migrate(engine, "20261002_0009", downgrade=True)
        with engine.begin() as db:
            db.execute(text("DELETE FROM chat_submission_receipts"))
        migrate(engine, "20261002_0009", downgrade=True)
        assert "chat_turn_pdf_selections" not in inspect(engine).get_table_names()
        assert history(engine) == before
    finally:
        engine.dispose()
