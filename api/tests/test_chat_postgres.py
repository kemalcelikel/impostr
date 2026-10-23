"""Coordinator-only fresh disposable PG migration/reservation concurrency checks."""

from __future__ import annotations

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

import pytest
from alembic import command
from fastapi.testclient import TestClient
from imp018_pytest_diagnostic import CAPTURE_DELETE_PROPERTY, fixed_capture_delete_pair
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from test_migrations import _alembic_config
from test_projects import _login

from app.chat_dispatch import Dispatcher
from app.config import AppSettings
from app.database import database_url_from_environment
from app.main import create_app
from app.models import (
    AttachmentDeletion,
    ChatSubmissionReceipt,
    ChatTurn,
    ChatTurnPdfSelection,
    Project,
    ProjectTurnReservation,
    User,
)
from app.passwords import hash_password

pytestmark = pytest.mark.skipif(
    os.environ.get("IMPOSTR_TEST_POSTGRES") != "1",
    reason="requires fresh coordinator-owned PostgreSQL profile",
)


def test_postgres_chat_migration_preserves_preexisting_identity_and_documents():
    engine = create_engine(
        database_url_from_environment(),
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
        poolclass=NullPool,
    )
    config = _alembic_config()
    owner_id = uuid.uuid4()
    project_id = uuid.uuid4()
    from app.chat_protocol import digest
    from app.models import ProjectDocument, ProjectDocumentRevision

    try:
        # Dedicated fresh stack only. Downgrade refuses to erase agent provenance.
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "20260930_0006")
        with Session(engine) as db, db.begin():
            db.add(
                User(
                    id=owner_id,
                    username="migration-" + owner_id.hex[:20],
                    password_hash="synthetic-not-a-login",
                    role="user",
                    is_active=True,
                )
            )
            db.flush()
            db.add(
                Project(
                    id=project_id, owner_user_id=owner_id, name="Synthetic migration preservation"
                )
            )
            db.flush()
            document = ProjectDocument(
                project_id=project_id, kind="project", head_revision_number=1
            )
            db.add(document)
            db.flush()
            document_id = document.id
            revision = ProjectDocumentRevision(
                document_id=document.id,
                revision_number=1,
                content="# Preserved synthetic draft",
                content_sha256=digest("# Preserved synthetic draft"),
                origin="human",
                author_user_id=owner_id,
            )
            db.add(revision)
            db.flush()
            revision_id = revision.id
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with Session(engine) as db:
            assert db.get(ProjectDocument, document_id).head_revision_number == 1
            assert (
                db.get(ProjectDocumentRevision, revision_id).content
                == "# Preserved synthetic draft"
            )
            assert db.get(ProjectDocumentRevision, revision_id).origin == "human"
            assert db.scalar(select(ChatTurn.id)) is None
    finally:
        with Session(engine) as db, db.begin():
            db.execute(delete(Project).where(Project.id == project_id))
            db.execute(delete(User).where(User.id == owner_id))
        engine.dispose()


def test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads(record_property):
    engine = create_engine(
        database_url_from_environment(),
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
        poolclass=NullPool,
    )
    settings = AppSettings(
        public_origin="http://127.0.0.1:8080",
        rate_limit_key=b"synthetic-chat-postgres-rate-limit-key",
        chat_enabled=False,
    )
    user_id = uuid.uuid4()
    project_id = None
    username = "chat-" + user_id.hex[:20]
    password = "synthetic disposable chat passphrase"
    imp018_diagnostic_stage = None
    try:
        imp018_diagnostic_stage = "submit_idempotency"
        with Session(engine) as db, db.begin():
            db.add(
                User(
                    id=user_id,
                    username=username,
                    password_hash=hash_password(password),
                    role="user",
                    is_active=True,
                )
            )
        with TemporaryDirectory(prefix="chat-pg-") as directory:
            app = create_app(engine, settings, workspace_root=Path(directory) / "workspace")

            # Prevent a failed assertion from leaving a fake dispatcher at lifespan cleanup.
            from test_chat import FakeBroker

            class SubmitOnly:
                broker = FakeBroker()
                test_scope = None

                def __init__(self):
                    self.engine = engine

                def close(self):
                    pass

            with TestClient(app) as first, TestClient(app) as second:
                _login(first, username, password)
                _login(second, username, password)

                def headers(client):
                    return {
                        "Origin": settings.public_origin,
                        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
                    }

                created = first.post(
                    "/api/projects", json={"name": "Synthetic PG chat"}, headers=headers(first)
                )
                assert created.status_code == 201
                project_id = uuid.UUID(created.json()["id"])
                base = f"/api/projects/{project_id}/chat"
                conv = first.post(base, json={"title": "Race"}, headers=headers(first)).json()["id"]
                app.state.settings = AppSettings(
                    public_origin=settings.public_origin,
                    rate_limit_key=settings.rate_limit_key,
                    chat_enabled=True,
                )
                app.state.chat_dispatcher = SubmitOnly()  # no worker/channel execution
                barrier = Barrier(2)
                key = str(uuid.uuid4())

                def submit(client):
                    barrier.wait(timeout=5)
                    return client.post(
                        f"{base}/{conv}/turns",
                        json={"request_id": key, "prompt": "Synthetic concurrent request"},
                        headers=headers(client),
                    )

                with ThreadPoolExecutor(max_workers=2) as pool:
                    replies = list(pool.map(submit, (first, second)))
                assert [reply.status_code for reply in replies] == [202, 202]
                assert replies[0].json()["id"] == replies[1].json()["id"]
                with Session(engine) as db:
                    turns = list(
                        db.scalars(select(ChatTurn).where(ChatTurn.project_id == project_id))
                    )
                    assert len(turns) == 1 and turns[0].state == "queued"
                    assert db.get(ProjectTurnReservation, project_id).turn_id == turns[0].id
                    assert all(
                        item["revision_id"] for item in turns[0].payload["documents"].values()
                    )
                    turn_id = turns[0].id
                # Two restarted API processes may inspect the same reservation;
                # only one claims its short channel-I/O lease at a time.
                from test_chat import FakeBroker

                imp018_diagnostic_stage = "leaseclaim"
                pumps = (Dispatcher(engine, FakeBroker()), Dispatcher(engine, FakeBroker()))
                with ThreadPoolExecutor(max_workers=2) as pool:
                    claims = list(pool.map(lambda pump: pump.claim(turn_id), pumps))
                assert sum(claim is not None for claim in claims) == 1
                for pump, claim in zip(pumps, claims, strict=True):
                    if claim is not None:
                        pump.release_claim(turn_id, claim)
                # A competing tab has a different request ID but cannot write concurrently.
                imp018_diagnostic_stage = "otherwriter"
                other = second.post(
                    base, json={"title": "Other tab"}, headers=headers(second)
                ).json()["id"]
                denied = second.post(
                    f"{base}/{other}/turns",
                    json={"request_id": str(uuid.uuid4()), "prompt": "Competing project writer"},
                    headers=headers(second),
                )
                assert denied.status_code == 409
                # PDF capture/delete use the same project lock on actual PG.
                # Capture reserves first (202/409), or deletion wins. Deletion
                # commits its pending fence BEFORE cleanup, so a concurrent submit
                # may see409 even when cleanup subsequently returns204; after the
                # fence clears it sees404. A pending cleanup may honestly return202.
                # Never a captured unreserved text copy or a future deleted send.
                from test_attachments import ready_derivative, upload

                from app.chat_protocol import digest
                from app.models import ProjectAttachment

                imp018_diagnostic_stage = "abort"
                assert (
                    first.post(
                        f"{base}/{conv}/turns/{turn_id}/abort", headers=headers(first)
                    ).status_code
                    == 200
                )
                imp018_diagnostic_stage = "upload"
                attachment_id = upload(first, f"{base}/{conv}/attachments").json()["id"]
                imp018_diagnostic_stage = "capture_delete_race"
                with Session(engine) as db, db.begin():
                    ready_derivative(db, attachment_id, "PG exact derivative\f\f")
                barrier = Barrier(2)
                capture_request_id = uuid.uuid4()

                def capture_pdf():
                    barrier.wait(timeout=5)
                    return first.post(
                        f"{base}/{conv}/turns",
                        headers=headers(first),
                        json={
                            "request_id": str(capture_request_id),
                            "prompt": "PG selected PDF",
                            "selections": [
                                {
                                    "attachment_id": attachment_id,
                                    "expected_sha256": digest("PG exact derivative\f\f"),
                                }
                            ],
                        },
                    )

                def delete_pdf():
                    barrier.wait(timeout=5)
                    return second.delete(
                        f"{base}/{conv}/attachments/{attachment_id}", headers=headers(second)
                    )

                with ThreadPoolExecutor(max_workers=2) as pool:
                    capture_future = pool.submit(capture_pdf)
                    delete_future = pool.submit(delete_pdf)
                    captured, removed = capture_future.result(15), delete_future.result(15)
                pair = (captured.status_code, removed.status_code)
                record_property(CAPTURE_DELETE_PROPERTY, fixed_capture_delete_pair(*pair))
                assert pair in ((202, 409), (404, 204), (409, 204), (409, 202))
                imp018_diagnostic_stage = "capture_integrity"
                with Session(engine) as db:
                    captured_turn = db.scalar(
                        select(ChatTurn).where(
                            ChatTurn.conversation_id == uuid.UUID(conv),
                            ChatTurn.request_id == capture_request_id,
                        )
                    )
                    reservation = db.get(ProjectTurnReservation, project_id)
                    attachment = db.get(ProjectAttachment, uuid.UUID(attachment_id))
                    if captured.status_code == 202:
                        assert captured_turn is not None and captured_turn.state == "queued"
                        assert str(captured_turn.id) == captured.json()["id"]
                        assert reservation is not None and reservation.turn_id == captured_turn.id
                        assert "text" not in captured_turn.payload["references"][0]
                        assert attachment is not None
                        assert db.get(AttachmentDeletion, uuid.UUID(attachment_id)) is None
                    else:
                        assert captured_turn is None and reservation is None and attachment is None
                        deletion = db.get(AttachmentDeletion, uuid.UUID(attachment_id))
                        assert deletion is not None
                        assert deletion.pending is (removed.status_code == 202)
                        assert (
                            db.scalar(
                                select(ChatTurnPdfSelection.turn_id).where(
                                    ChatTurnPdfSelection.attachment_id == uuid.UUID(attachment_id)
                                )
                            )
                            is None
                        )
                    assert all(
                        "PG exact derivative" not in json.dumps(turn.payload)
                        for turn in db.scalars(
                            select(ChatTurn).where(ChatTurn.project_id == project_id)
                        )
                    )
                if captured.status_code == 202:
                    assert (
                        first.post(
                            f"{base}/{conv}/turns/{captured.json()['id']}/abort",
                            headers=headers(first),
                        ).status_code
                        == 200
                    )
                    assert (
                        first.delete(
                            f"{base}/{conv}/attachments/{attachment_id}", headers=headers(first)
                        ).status_code
                        == 204
                    )
                # After removal, a fresh request is rejected, not reserved or sent.
                future_request_id = uuid.uuid4()
                future = first.post(
                    f"{base}/{conv}/turns",
                    headers=headers(first),
                    json={
                        "request_id": str(future_request_id),
                        "prompt": "No deleted PDF send",
                        "selections": [
                            {
                                "attachment_id": attachment_id,
                                "expected_sha256": digest("PG exact derivative\f\f"),
                            }
                        ],
                    },
                )
                assert future.status_code == (409 if removed.status_code == 202 else 404)
                Dispatcher(engine, app.state.chat_dispatcher.broker).tick()
                assert not any(
                    call["op"] == "start" for call in app.state.chat_dispatcher.broker.calls
                )
                with Session(engine) as db:
                    assert db.get(ProjectAttachment, uuid.UUID(attachment_id)) is None
                    assert db.get(ProjectTurnReservation, project_id) is None
                    assert (
                        db.scalar(
                            select(ChatTurn.id).where(
                                ChatTurn.conversation_id == uuid.UUID(conv),
                                ChatTurn.request_id == future_request_id,
                            )
                        )
                        is None
                    )
                # Exercise the 0010 CHECK constraints on this actual fresh PG schema;
                # opaque attachment identity deliberately has no attachment FK.
                with Session(engine) as db, db.begin():
                    db.add(
                        ChatTurnPdfSelection(
                            turn_id=turn_id,
                            position=0,
                            attachment_id=uuid.uuid4(),
                            expected_sha256="a" * 64,
                        )
                    )
                with Session(engine) as db:
                    with pytest.raises(IntegrityError):
                        with db.begin_nested():
                            db.add(
                                ChatTurnPdfSelection(
                                    turn_id=turn_id,
                                    position=32,
                                    attachment_id=uuid.uuid4(),
                                    expected_sha256="b" * 64,
                                )
                            )
                            db.flush()
                    with pytest.raises(IntegrityError):
                        with db.begin_nested():
                            db.add(
                                ChatSubmissionReceipt(
                                    turn_id=turn_id,
                                    call=9,
                                    request_sha256=None,
                                    status="sent",
                                )
                            )
                            db.flush()
                    with pytest.raises(IntegrityError):
                        with db.begin_nested():
                            db.add(
                                ChatSubmissionReceipt(
                                    turn_id=turn_id,
                                    call=2,
                                    request_sha256=None,
                                    status="sent",
                                )
                            )
                            db.flush()
                app.state.chat_dispatcher = None
    finally:
        if sys.exc_info()[0] is None:
            # This allowlisted local is inspected by the diagnostic hook only if
            # cleanup fails; it is not unused despite having no Python read here.
            imp018_diagnostic_stage = "purge_cleanup"  # noqa: F841 - read by diagnostic hook
        with Session(engine) as db, db.begin():
            if project_id is not None:
                db.execute(delete(Project).where(Project.id == project_id))
            db.execute(delete(User).where(User.id == user_id))
        engine.dispose()
