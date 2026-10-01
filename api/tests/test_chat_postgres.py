"""Coordinator-only fresh disposable PG migration/reservation concurrency checks."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from test_migrations import _alembic_config
from test_projects import _login

from app.chat_dispatch import Dispatcher
from app.config import AppSettings
from app.database import database_url_from_environment
from app.main import create_app
from app.models import ChatTurn, Project, ProjectTurnReservation, User
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


def test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads():
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
    try:
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
            class SubmitOnly:
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

                pumps = (Dispatcher(engine, FakeBroker()), Dispatcher(engine, FakeBroker()))
                with ThreadPoolExecutor(max_workers=2) as pool:
                    claims = list(pool.map(lambda pump: pump.claim(turn_id), pumps))
                assert sum(claim is not None for claim in claims) == 1
                for pump, claim in zip(pumps, claims, strict=True):
                    if claim is not None:
                        pump.release_claim(turn_id, claim)
                # A competing tab has a different request ID but cannot write concurrently.
                other = second.post(
                    base, json={"title": "Other tab"}, headers=headers(second)
                ).json()["id"]
                denied = second.post(
                    f"{base}/{other}/turns",
                    json={"request_id": str(uuid.uuid4()), "prompt": "Competing project writer"},
                    headers=headers(second),
                )
                assert denied.status_code == 409
                app.state.chat_dispatcher = None
    finally:
        with Session(engine) as db, db.begin():
            if project_id is not None:
                db.execute(delete(Project).where(Project.id == project_id))
            db.execute(delete(User).where(User.id == user_id))
        engine.dispose()
