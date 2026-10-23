"""B2 locked API gate/receipt seam only; deliberately does not enable native dispatch."""

import copy
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from imp025_native_fixture import submit_pdf
from sqlalchemy import MetaData, Table, create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_attachments_migration import history, migrate, seed_history
from test_native_pdf_storage import selected_original

from app.chat_protocol import (
    NATIVE_PDF_REFERENCE,
    ChannelError,
    digest,
    manifest_digest,
    native_occurrence_manifest,
    native_prompt_text,
    original_manifest_digest,
    reference_manifest,
)
from app.chat_references import resolve_context
from app.models import (
    AttachmentDeletion,
    ChatSendAuthorization,
    ChatSubmissionReceipt,
    ChatTurn,
    ProjectAttachment,
    ProjectTurnReservation,
    WebSession,
)


def held_call(setup, *, history=False):
    """Seed the future dispatch capture, without bypassing any send authorization."""
    _, engine, _, _, _, _, broker, _ = setup
    first = selected_original(setup, b"%PDF-first exact original")
    second = selected_original(setup, b"%PDF-second exact original")
    response = submit_pdf(setup, [first, second, first])
    assert response.status_code == 202
    turn_id = uuid.UUID(response.json()["id"])
    with Session(engine) as db, db.begin():
        turn = db.get(ChatTurn, turn_id)
        if history:
            # A reconstructed occurrence, not an arbitrary file-read capability.
            turn.payload = dict(
                turn.payload,
                history=[
                    dict(
                        role="user",
                        text="Quoted prior turn",
                        references=copy.deepcopy(turn.payload["references"]),
                    ),
                    dict(role="assistant", text="Quoted prior answer"),
                ],
            )
        resolved = resolve_context(db, turn.project_id, turn.conversation_id, turn.payload)
        turn.state = "running"
        turn.broker_epoch = uuid.UUID(broker.epoch)
        turn.dispatch_deadline = datetime.now(UTC) + timedelta(seconds=50)
        turn.dispatch_manifest = reference_manifest(resolved)
        turn.dispatch_manifest_sha256 = manifest_digest(resolved)
        turn.dispatch_rendered_sha256 = digest(native_prompt_text(resolved))
        turn.receipt_pending = True
        pending = dict(
            project_id=str(turn.project_id),
            conversation_id=str(turn.conversation_id),
            turn_id=str(turn.id),
            epoch=broker.epoch,
            call=1,
            reference_kind=NATIVE_PDF_REFERENCE,
            rendered_sha256=turn.dispatch_rendered_sha256,
            manifest_sha256=turn.dispatch_manifest_sha256,
            request_sha256="a" * 64,
            request_size=1234,
            original_manifest=native_occurrence_manifest(resolved),
        )
    return (
        turn_id,
        dict(
            known=True, stopped=False, epoch=broker.epoch, receipts=[], send_authorization=pending
        ),
        first,
    )


def receipt(result, capability, status="sent"):
    row = copy.deepcopy(result["send_authorization"])
    manifest = row.pop("original_manifest")
    row.update(
        original_manifest_sha256=original_manifest_digest(manifest),
        authorization_id=capability,
        status=status,
    )
    return row


def test_api_grant_is_metadata_only_durable_and_not_renewed_after_lost_ack(chat_setup):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    turn_id, result, _ = held_call(chat_setup, history=True)
    dispatcher.authorize_send(turn_id, result)
    grant = broker.calls[-1]
    assert grant["op"] == "authorize-send" and "file_data" not in str(grant)
    assert len(grant["authorization"]["original_manifest"]) == 6
    with Session(engine) as db:
        rows = list(db.scalars(select(ChatSendAuthorization)))
        assert len(rows) == 1 and rows[0].request_size == 1234
        assert str(rows[0].authorization_id) == grant["authorization"]["authorization_id"]
    broker.calls.clear()
    with pytest.raises(ChannelError):
        dispatcher.authorize_send(turn_id, result)
    assert broker.calls == []  # Restart/repeated polling does not renew a committed call.
    result["send_authorization"]["call"] = 2
    original = broker.call
    broker.call = lambda _: (_ for _ in ()).throw(ChannelError())
    with pytest.raises(ChannelError):
        dispatcher.authorize_send(turn_id, result)
    broker.call = original
    with pytest.raises(ChannelError):
        dispatcher.authorize_send(turn_id, result)
    with Session(engine) as db:
        assert len(list(db.scalars(select(ChatSendAuthorization)))) == 2


@pytest.mark.parametrize(
    "failure", ["revoked", "cancelling", "deleted", "changed-bytes", "reservation"]
)
def test_api_revalidates_each_call_and_keeps_previously_authorized_sent_fact(chat_setup, failure):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    turn_id, result, selected = held_call(chat_setup, history=True)
    dispatcher.authorize_send(turn_id, result)
    capability = broker.calls[-1]["authorization"]["authorization_id"]
    sent = receipt(result, capability)
    dispatcher.persist_receipts(turn_id, dict(epoch=broker.epoch, receipts=[sent]))
    result["send_authorization"]["call"] = 2
    with Session(engine) as db, db.begin():
        turn = db.get(ChatTurn, turn_id)
        if failure == "revoked":
            db.execute(update(WebSession).values(revoked_at=datetime.now(UTC)))
        elif failure == "cancelling":
            turn.state = "cancelling"
        elif failure == "deleted":
            db.add(
                AttachmentDeletion(
                    attachment_id=uuid.UUID(selected["attachment_id"]),
                    project_id=turn.project_id,
                    conversation_id=turn.conversation_id,
                )
            )
        elif failure == "changed-bytes":
            row = db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"]))
            row.original = row.original.replace(b"first", b"other")
        else:
            db.delete(db.get(ProjectTurnReservation, turn.project_id))
    broker.calls.clear()
    with pytest.raises((ChannelError, HTTPException)):
        dispatcher.authorize_send(turn_id, result)
    assert broker.calls == []
    # Receipt-only reconciliation remains independent of authorization/deletion.
    dispatcher.persist_receipts(turn_id, dict(epoch=broker.epoch, receipts=[sent]))
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).submission_state == "sent"
        assert db.get(ChatSubmissionReceipt, (turn_id, 1)).status == "sent"
        assert len(list(db.scalars(select(ChatSendAuthorization)))) == 1


@pytest.mark.parametrize("failure", ["scope", "order", "manifest", "rendering"])
def test_api_observed_manifest_and_dispatch_capture_must_match_exactly(chat_setup, failure):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    turn_id, result, _ = held_call(chat_setup)
    pending = result["send_authorization"]
    if failure == "scope":
        pending["conversation_id"] = str(uuid.uuid4())
    elif failure == "order":
        pending["original_manifest"][0]["attachment_id"] = str(uuid.uuid4())
    elif failure == "manifest":
        pending["original_manifest"].pop()
    else:
        pending["rendered_sha256"] = "b" * 64
    with pytest.raises(ChannelError):
        dispatcher.authorize_send(turn_id, result)
    assert not any(call["op"] == "authorize-send" for call in broker.calls)
    with Session(engine) as db:
        assert not list(db.scalars(select(ChatSendAuthorization)))


def test_native_receipt_requires_exact_final_hash_length_kind_and_committed_capability(chat_setup):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    turn_id, result, _ = held_call(chat_setup)
    dispatcher.authorize_send(turn_id, result)
    capability = broker.calls[-1]["authorization"]["authorization_id"]
    actual = receipt(result, capability, "uncertain")
    for field, wrong in (
        ("authorization_id", str(uuid.uuid4())),
        ("request_sha256", "f" * 64),
        ("request_size", 1235),
        ("original_manifest_sha256", "b" * 64),
    ):
        with pytest.raises(ChannelError):
            dispatcher.persist_receipts(
                turn_id, dict(epoch=broker.epoch, receipts=[dict(actual, **{field: wrong})])
            )
    legacy = {
        name: value
        for name, value in actual.items()
        if name
        not in ("authorization_id", "request_size", "original_manifest_sha256", "reference_kind")
    }
    with pytest.raises(ChannelError):
        dispatcher.persist_receipts(turn_id, dict(epoch=broker.epoch, receipts=[legacy]))
    dispatcher.persist_receipts(turn_id, dict(epoch=broker.epoch, receipts=[actual]))
    actual["status"] = "sent"
    dispatcher.persist_receipts(turn_id, dict(epoch=broker.epoch, receipts=[actual]))
    with Session(engine) as db:
        stored = db.get(ChatSubmissionReceipt, (turn_id, 1))
        assert stored.status == "sent" and stored.request_size == 1234
        assert stored.reference_kind == NATIVE_PDF_REFERENCE
        assert str(stored.authorization_id) == capability


def test_forward_send_schema_preserves_legacy_receipts_and_bounds_native_grants(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'native-send.db'}")
    try:
        migrate(engine, "20261002_0009")
        seed_history(engine)
        migrate(engine, "20261014_0011")
        with engine.begin() as db:
            turns = Table("chat_turns", MetaData(), autoload_with=db)
            receipts = Table("chat_submission_receipts", MetaData(), autoload_with=db)
            turn_id = db.scalar(select(turns.c.id))
            db.execute(
                receipts.insert().values(
                    turn_id=turn_id, call=1, status="sent", request_sha256="c" * 64
                )
            )
            before = db.execute(select(receipts)).one()._mapping
        prior_history = history(engine)
        migrate(engine, "20261014_0012")
        assert history(engine) == prior_history
        with Session(engine) as db:
            row = db.get(ChatSubmissionReceipt, (uuid.UUID(turn_id), 1))
            assert row.status == before["status"] and row.request_sha256 == before["request_sha256"]
            assert (
                row.reference_kind == "legacy-text-v1"
                and row.authorization_id is None
                and row.request_size is None
            )
        values = dict(
            turn_id=uuid.UUID(turn_id),
            call=2,
            epoch=uuid.uuid4(),
            authorization_id=uuid.uuid4(),
            request_sha256="a" * 64,
            request_size=1234,
            original_manifest_sha256="b" * 64,
            expires_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        with Session(engine) as db, db.begin():
            db.add(ChatSendAuthorization(**values))
        with Session(engine) as db, pytest.raises(IntegrityError):
            db.add(ChatSendAuthorization(**dict(values, authorization_id=uuid.uuid4())))
            db.commit()
        with Session(engine) as db, pytest.raises(IntegrityError):
            db.add(
                ChatSubmissionReceipt(
                    turn_id=uuid.UUID(turn_id),
                    call=2,
                    status="sent",
                    request_sha256="a" * 64,
                    reference_kind=NATIVE_PDF_REFERENCE,
                )
            )
            db.commit()
    finally:
        engine.dispose()
