"""Native API deletion/recovery + fresh owned PostgreSQL acceptance, not PDF proof.

The only native boundary proof lives in the reviewed coordinator verifier. These
checks use normal login and the existing fake broker, never a live native worker.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from imp025_native_fixture import authorize_fake_call, native_api, submit_pdf
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from test_attachments_migration import history, migrate
from test_native_pdf_migration import check_extractor_retirement, check_native_transition, snapshot
from test_native_pdf_storage import selected_original
from test_projects import _login

from app.chat_dispatch import Dispatcher
from app.chat_protocol import NATIVE_PDF_REFERENCE, ChannelError
from app.database import database_url_from_environment
from app.main import create_app
from app.models import (
    AttachmentDeletion,
    AttachmentPurge,
    ChatSendAuthorization,
    ChatSubmissionReceipt,
    ChatTurn,
    ChatTurnPdfSelection,
    ProjectAttachment,
    ProjectTurnReservation,
)


def test_native_outage_restart_receipt_purge_quotes(chat_setup):
    client, engine, headers, _, base, conv, broker, dispatcher = chat_setup
    selected = selected_original(chat_setup)
    response = submit_pdf(chat_setup, [selected], prompt="Native user quotation")
    assert response.status_code == 202
    original_id = response.json()["id"]
    dispatcher.tick()
    authorize_fake_call(chat_setup, original_id)
    broker.add("delta", {"text": "Native assistant quotation"})
    broker.add("completed", {"proposals": []})
    dispatcher.tick()
    assert client.get(f"{base}/{conv}").json()["turns"][0]["submission"]["status"] == "sent"
    call = broker.call
    broker.call = lambda _: (_ for _ in ()).throw(ChannelError())
    path = f"{base}/{conv}/attachments/{selected['attachment_id']}"
    assert client.delete(path, headers=headers).status_code == 202
    assert client.delete(path, headers=headers).status_code == 202
    assert submit_pdf(chat_setup, []).status_code == 409
    assert client.get(path + "/raw").status_code == 404
    with Session(engine) as db:
        assert db.get(AttachmentDeletion, uuid.UUID(selected["attachment_id"])).pending
        assert db.scalar(select(AttachmentPurge.confirmed_epoch)) is None
    broker.call = call
    Dispatcher(engine, broker).tick()  # New API pump; receipt fact is not resubmitted.
    assert broker.purged and broker.payload is None and not broker.events
    assert client.delete(path, headers=headers).status_code == 204
    continued = submit_pdf(chat_setup, [])
    assert continued.status_code == 202
    with Session(engine) as db:
        retained = db.get(ChatTurn, uuid.UUID(original_id))  # Never select by tied timestamp/order.
        current = db.get(ChatTurn, uuid.UUID(continued.json()["id"]))
        assert retained.submission_state == "sent"
        receipt = db.get(ChatSubmissionReceipt, (retained.id, 1))
        assert receipt.reference_kind == NATIVE_PDF_REFERENCE
        assert current.payload["history"][0]["text"] == "Native user quotation"
        assert current.payload["history"][1]["text"].startswith("Native assistant quotation")
        assert db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"])) is None
    assert sum(call["op"] == "start" for call in broker.calls) == 1


def test_native_capture_delete_committed_fence(chat_setup, monkeypatch):
    from app import attachments

    client, engine, headers, _, base, conv, broker, dispatcher = chat_setup
    selected = selected_original(chat_setup)
    cleanup = attachments.cleanup
    observed = []

    def after_delete_commit(cleanup_engine, cleanup_broker, attachment_id):
        with Session(engine) as db:
            assert db.get(ProjectAttachment, attachment_id) is None
            assert db.get(AttachmentDeletion, attachment_id).pending
        captured = submit_pdf(chat_setup, [selected])
        observed.append(captured.status_code)
        assert captured.status_code == 409
        return cleanup(cleanup_engine, cleanup_broker, attachment_id)

    monkeypatch.setattr(attachments, "cleanup", after_delete_commit)
    removed = client.delete(
        f"{base}/{conv}/attachments/{selected['attachment_id']}", headers=headers
    )
    assert removed.status_code == 204
    assert observed == [409] and submit_pdf(chat_setup, [selected]).status_code == 404
    dispatcher.tick()
    assert not any(call["op"] == "start" for call in broker.calls)
    with Session(engine) as db:
        assert db.scalar(select(ChatTurn.id)) is None
        assert db.scalar(select(ProjectTurnReservation.turn_id)) is None


def test_native_active_delete_conflict_until_confirmed_stop(chat_setup):
    client, engine, headers, _, base, conv, broker, dispatcher = chat_setup
    selected = selected_original(chat_setup)
    response = submit_pdf(chat_setup, [selected])
    path = f"{base}/{conv}/attachments/{selected['attachment_id']}"
    assert client.delete(path, headers=headers).status_code == 409
    dispatcher.tick()
    call = broker.call
    broker.call = lambda _: (_ for _ in ()).throw(ChannelError())
    aborted = client.post(f"{base}/{conv}/turns/{response.json()['id']}/abort", headers=headers)
    assert aborted.status_code == 200
    dispatcher.tick()
    assert client.delete(path, headers=headers).status_code == 409
    broker.call = call
    Dispatcher(engine, broker).tick()
    assert client.delete(path, headers=headers).status_code == 204
    with Session(engine) as db:
        assert db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"])) is None
        assert db.scalar(select(ProjectTurnReservation.turn_id)) is None


@pytest.fixture
def native_postgres():
    if not (
        os.environ.get("IMPOSTR_TEST_POSTGRES") == "1"
        and os.environ.get("IMPOSTR_TEST_NATIVE_PDF") == "1"
    ):
        pytest.skip("requires fresh coordinator-owned native PostgreSQL profile")
    # No host settings: generated Compose DB settings only, and a unique owned
    # schema so preservation starts at actual 0009, not today's already-new schema.
    assert os.geteuid() == 10001
    url = database_url_from_environment()
    owner = create_engine(
        url, hide_parameters=True, poolclass=NullPool, connect_args={"connect_timeout": 3}
    )
    schema = "imp025_" + uuid.uuid4().hex
    engine = None
    try:
        with owner.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(
            url,
            hide_parameters=True,
            poolclass=NullPool,
            connect_args={"connect_timeout": 3, "options": f"-csearch_path={schema}"},
        )
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        try:
            with owner.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                remaining = db.scalar(
                    text("SELECT count(*) FROM pg_namespace WHERE nspname=:name"), {"name": schema}
                )
                assert remaining == 0
        finally:
            owner.dispose()


@pytest.mark.parametrize("populated", [False, True])
def test_postgres_extractor_retirement_preservation(native_postgres, populated):
    check_extractor_retirement(native_postgres, populated=populated)


def test_postgres_native_migrations_preservation_and_legacy_fence(native_postgres):
    engine = native_postgres
    check_native_transition(engine)  # Historical SQL completion fence and original preservation.
    print("IMP025_STAGE pg_legacy_fence", flush=True)
    before_history = history(engine)
    before_originals = snapshot(engine, "project_attachments")
    before_receipts = snapshot(engine, "chat_submission_receipts")
    migrate(engine, "20261014_0012")
    assert history(engine) == before_history
    assert snapshot(engine, "project_attachments") == before_originals
    with engine.connect() as db:
        receipts = Table("chat_submission_receipts", MetaData(), autoload_with=db)
        rows = db.execute(select(receipts).order_by(receipts.c.turn_id, receipts.c.call)).all()
        assert len(rows) == len(before_receipts)
        for old, new in zip(before_receipts, rows, strict=True):
            assert all(new._mapping[key] == value for key, value in old._mapping.items())
            assert new.reference_kind == "legacy-text-v1"
            assert new.request_size is None and new.authorization_id is None
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261014_0012"
    print("IMP025_STAGE pg_preservation", flush=True)
    # The existing actual send schema constraint/regression helper is SQLite-only;
    # prove native NOT NULL/domain constraints on this real PostgreSQL too.
    with Session(engine) as db:
        turn_id = db.scalar(select(ChatTurn.id))
    grant = dict(
        turn_id=turn_id,
        call=2,
        epoch=uuid.uuid4(),
        authorization_id=uuid.uuid4(),
        request_sha256="b" * 64,
        request_size=1234,
        original_manifest_sha256="c" * 64,
        expires_at=datetime.now(UTC) + timedelta(seconds=5),
    )
    with Session(engine) as db, db.begin():
        db.add(ChatSendAuthorization(**grant))
    for change in ({"request_size": 0}, {"request_size": 100_000_000}, {"request_sha256": "bad"}):
        with Session(engine) as db, pytest.raises(IntegrityError):
            db.add(
                ChatSendAuthorization(
                    **dict(grant, call=3, authorization_id=uuid.uuid4(), **change)
                )
            )
            db.commit()
    with Session(engine) as db, pytest.raises(IntegrityError):
        db.add(
            ChatSubmissionReceipt(
                turn_id=turn_id,
                call=2,
                status="sent",
                request_sha256="a" * 64,
                reference_kind=NATIVE_PDF_REFERENCE,
            )
        )
        db.commit()
    print("IMP025_STAGE pg_send_schema", flush=True)


def test_postgres_native_capture_delete_race(native_postgres, tmp_path):
    engine = native_postgres
    migrate(engine, "head")
    with native_api(engine, tmp_path / "native-workspaces") as (setup, login, settings):
        first, _, headers, project, base, conv, broker, dispatcher = setup
        selected = selected_original(setup)
        second_app = create_app(engine, settings, workspace_root=tmp_path / "other-workspaces")
        with TestClient(second_app) as second:
            _login(second, *login)
            second_app.state.settings = replace(settings, chat_enabled=True)
            second_app.state.chat_dispatcher = Dispatcher(engine, broker)
            try:
                other_headers = {
                    "Origin": settings.public_origin,
                    "X-CSRF-Token": second.cookies["impostr_csrf"],
                }
                barrier = Barrier(2)
                key = uuid.uuid4()

                def capture():
                    barrier.wait(timeout=5)
                    return submit_pdf(setup, [selected], request_id=key)

                def remove():
                    barrier.wait(timeout=5)
                    return second.delete(
                        f"{base}/{conv}/attachments/{selected['attachment_id']}",
                        headers=other_headers,
                    )

                with ThreadPoolExecutor(max_workers=2) as pool:
                    captured_future, removed_future = pool.submit(capture), pool.submit(remove)
                    captured, removed = captured_future.result(15), removed_future.result(15)
                assert (captured.status_code, removed.status_code) in {
                    (202, 409),
                    (404, 204),
                    (409, 204),
                    (409, 202),
                }
                with Session(engine) as db:
                    turn = db.scalar(select(ChatTurn).where(ChatTurn.request_id == key))
                    reservation = db.get(ProjectTurnReservation, uuid.UUID(project))
                    if captured.status_code == 202:
                        assert turn is not None and reservation.turn_id == turn.id
                        assert turn.payload["references"][0]["kind"] == NATIVE_PDF_REFERENCE
                        reference = turn.payload["references"][0]
                        assert reference["original_sha256"] == selected["expected_sha256"]
                        assert "base64" not in str(turn.payload)
                    else:
                        assert turn is None and reservation is None
                        assert (
                            db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"])) is None
                        )
                        assert db.scalar(select(ChatTurnPdfSelection.turn_id)) is None
                if captured.status_code == 202:
                    aborted = first.post(
                        f"{base}/{conv}/turns/{captured.json()['id']}/abort", headers=headers
                    )
                    assert aborted.status_code == 200
                    deleted = first.delete(
                        f"{base}/{conv}/attachments/{selected['attachment_id']}", headers=headers
                    )
                    assert deleted.status_code == 204
                dispatcher.tick()
                expected = 409 if removed.status_code == 202 else 404
                assert submit_pdf(setup, [selected]).status_code == expected
                assert not any(call["op"] == "start" for call in broker.calls)
                print("IMP025_STAGE pg_capture_delete", flush=True)
            finally:
                second_app.state.chat_dispatcher = None
