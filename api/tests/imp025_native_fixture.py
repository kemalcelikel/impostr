"""Coordinator synthetic API/DB fixtures; no parser/channel/worker/provider startup.

Only the fresh owned Compose profile may resolve its generated DB settings. No
host discovery, private configuration or reusable login; normal Member sign-in.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_chat import FakeBroker
from test_projects import _login

from app.chat_dispatch import Dispatcher
from app.chat_protocol import (
    NATIVE_PDF_REFERENCE,
    native_occurrence_manifest,
    original_manifest_digest,
)
from app.config import AppSettings
from app.main import create_app
from app.models import ChatTurn, Project, User
from app.passwords import hash_password


def submit_pdf(setup, selections, *, request_id=None, prompt="Use PDF references"):
    client, _, headers, _, base, conv, _, _ = setup
    return client.post(
        f"{base}/{conv}/turns",
        headers=headers,
        json={
            "request_id": str(request_id or uuid.uuid4()),
            "prompt": prompt,
            "selections": selections,
        },
    )


@contextmanager
def native_api(engine, workspace):
    user_id = uuid.uuid4()
    username = "joined-native-" + user_id.hex[:16]
    password = "synthetic disposable native passphrase"
    settings = AppSettings(
        public_origin="http://127.0.0.1:8080",
        rate_limit_key=b"synthetic-native-only-rate-limit-key",
    )
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
    app = create_app(engine, settings, workspace_root=workspace)
    try:
        with TestClient(app) as client:
            _login(client, username, password)
            headers = {
                "Origin": settings.public_origin,
                "X-CSRF-Token": client.cookies["impostr_csrf"],
            }
            assert client.get("/api/admin/users").status_code == 403
            project = client.post(
                "/api/projects", json={"name": "Synthetic native PG"}, headers=headers
            )
            assert project.status_code == 201
            project_id = project.json()["id"]
            base = f"/api/projects/{project_id}/chat"
            conversation = client.post(base, json={"title": "Native"}, headers=headers)
            assert conversation.status_code == 201
            broker = FakeBroker()
            dispatcher = Dispatcher(engine, broker)
            app.state.settings = replace(settings, chat_enabled=True)
            app.state.chat_dispatcher = dispatcher  # No thread, no channel execution.
            try:
                yield (
                    (
                        client,
                        engine,
                        headers,
                        project_id,
                        base,
                        conversation.json()["id"],
                        broker,
                        dispatcher,
                    ),
                    (username, password),
                    settings,
                )
            finally:
                app.state.chat_dispatcher = None
    finally:
        with Session(engine) as db, db.begin():
            for project in db.scalars(select(Project).where(Project.owner_user_id == user_id)):
                db.delete(project)
            db.flush()
            db.execute(delete(User).where(User.id == user_id))


def authorize_fake_call(setup, turn_id):
    """Production grant/receipt persistence with fixed FAKE transport metadata.

    This is an API regression, explicitly NOT serialized native submission proof.
    Only imp025_verify's receiver proves final bytes through the actual worker.
    """
    _, engine, _, _, _, _, broker, dispatcher = setup
    with Session(engine) as db:
        turn = db.get(ChatTurn, uuid.UUID(turn_id))
        manifest = native_occurrence_manifest(broker.payload["context"])
        pending = dict(
            project_id=str(turn.project_id),
            conversation_id=str(turn.conversation_id),
            turn_id=str(turn.id),
            epoch=broker.epoch,
            call=1,
            reference_kind=NATIVE_PDF_REFERENCE,
            rendered_sha256=turn.dispatch_rendered_sha256,
            manifest_sha256=turn.dispatch_manifest_sha256,
            original_manifest=manifest,
            request_sha256="a" * 64,
            request_size=1234,
        )
    result = dict(
        known=True, stopped=False, epoch=broker.epoch, receipts=[], send_authorization=pending
    )
    dispatcher.authorize_send(uuid.UUID(turn_id), result)
    grant = broker.calls[-1]["authorization"]
    receipt = {name: value for name, value in pending.items() if name != "original_manifest"}
    receipt.update(
        status="sent",
        authorization_id=grant["authorization_id"],
        original_manifest_sha256=original_manifest_digest(manifest),
    )
    broker.receipts = [receipt]
    return receipt
