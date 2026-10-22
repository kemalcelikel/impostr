"""Durable dispatch/receipt/deletion orchestration with the existing fake channel.

No worker, provider or runtime harness executes here. PostgreSQL race verification
uses these transaction seams in the coordinator's pinned checks.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_chat_references import selected_pdf, submit_pdf

from app.chat_dispatch import Dispatcher
from app.chat_protocol import ChannelError
from app.models import (
    AttachmentDeletion,
    AttachmentPurge,
    ChatSubmissionReceipt,
    ChatTurn,
    ProjectAttachment,
    ProjectTurnReservation,
    WebSession,
)


def delete_path(setup, selection):
    return f"{setup[4]}/{setup[5]}/attachments/{selection['attachment_id']}"


def stop_queued(setup, response):
    client, _, headers, _, base, conv, _, _ = setup
    assert (
        client.post(
            f"{base}/{conv}/turns/{response.json()['id']}/abort", headers=headers
        ).status_code
        == 200
    )


@pytest.mark.parametrize("status", ["sent", "uncertain", "failed-before-send"])
def test_receipts_commit_without_events_and_survive_cancel_and_restart(chat_setup, status):
    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    response = submit_pdf(chat_setup, [selected])
    turn_id = uuid.UUID(response.json()["id"])
    dispatcher.tick()
    broker.add_receipt(status, request_sha256=None if status == "failed-before-send" else "a" * 64)
    # No started/delta event can be mistaken for this host-only proof.
    assert broker.events == []
    if status == "failed-before-send":
        broker.stopped = True
    dispatcher.tick()
    view = client.get(f"{base}/{conv}").json()["turns"][0]["submission"]
    assert view["status"] == status
    assert view["manifest"][-1][0]["reference"]["missing_pages"] == [2]
    assert view["manifest"][-1][0]["reference"]["text_sha256"] == selected["expected_sha256"]
    assert "Exact café" not in json.dumps(view)
    assert client.post(f"{base}/{conv}/turns/{turn_id}/abort", headers=headers).status_code == 200
    Dispatcher(engine, broker).tick()
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).state == "cancelled"
        assert db.get(ChatTurn, turn_id).submission_state == status
        assert db.get(ProjectTurnReservation, uuid.UUID(project)) is None
        assert len(list(db.scalars(select(ChatSubmissionReceipt)))) == 1
    assert sum(call["op"] == "start" for call in broker.calls) == 1


def test_receipt_monotonic_hash_validation_and_revoked_terminal_reconciliation(chat_setup):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    response = submit_pdf(chat_setup, [selected_pdf(chat_setup)])
    turn_id = uuid.UUID(response.json()["id"])
    dispatcher.tick()
    broker.add_receipt("uncertain")
    dispatcher.poll_receipts(turn_id)
    broker.receipts[0]["status"] = "sent"
    dispatcher.poll_receipts(turn_id)
    broker.receipts[0]["status"] = "uncertain"  # Older snapshot cannot downgrade sent.
    dispatcher.poll_receipts(turn_id)
    broker.receipts[0]["request_sha256"] = "f" * 64
    with pytest.raises(ChannelError):
        dispatcher.poll_receipts(turn_id)
    broker.receipts[0]["request_sha256"] = "a" * 64
    original_project = broker.receipts[0]["project_id"]
    broker.receipts[0]["project_id"] = str(uuid.uuid4())
    with pytest.raises(ChannelError):
        dispatcher.poll_receipts(turn_id)
    broker.receipts[0]["project_id"] = original_project
    with Session(engine) as db, db.begin():
        db.execute(update(WebSession).values(revoked_at=datetime.now(UTC)))
    dispatcher.tick()
    with Session(engine) as db:
        turn = db.get(ChatTurn, turn_id)
        assert turn.state == "interrupted" and turn.submission_state == "sent"
        assert not turn.receipt_pending


def test_lost_start_ack_reconciles_receipt_without_second_inference(chat_setup):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    response = submit_pdf(chat_setup, [selected_pdf(chat_setup)])
    turn_id = uuid.UUID(response.json()["id"])
    call = broker.call

    def lost_ack(value):
        result = call(value)
        if value["op"] == "start":
            broker.add_receipt()
            raise ChannelError()
        return result

    broker.call = lost_ack
    dispatcher.tick()
    Dispatcher(engine, broker).tick()
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).submission_state == "sent"
        assert db.get(ChatTurn, turn_id).state == "interrupted"
    assert sum(value["op"] == "start" for value in broker.calls) == 1


def test_crashed_dispatch_marker_recovers_same_epoch_by_poll_only(chat_setup):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    response = submit_pdf(chat_setup, [selected_pdf(chat_setup)])
    turn_id = uuid.UUID(response.json()["id"])
    dispatcher.tick()
    broker.add_receipt()
    # Crash after broker accepted, before the API persisted running/receipt ACK.
    with Session(engine) as db, db.begin():
        turn = db.get(ChatTurn, turn_id)
        turn.state = "dispatching"
        turn.dispatch_deadline = datetime.now(UTC) + timedelta(seconds=50)
    Dispatcher(engine, broker).tick()
    with Session(engine) as db:
        turn = db.get(ChatTurn, turn_id)
        assert turn.state == "running" and turn.submission_state == "sent"
    assert sum(value["op"] == "start" for value in broker.calls) == 1


def test_missing_current_selection_at_dispatch_never_starts(chat_setup):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    response = submit_pdf(chat_setup, [selected])
    # Simulate out-of-band integrity failure, not the authorized delete endpoint
    # (which correctly returns409 while this capture is reserved).
    with Session(engine) as db, db.begin():
        db.delete(db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"])))
    dispatcher.tick()
    with Session(engine) as db:
        turn = db.get(ChatTurn, uuid.UUID(response.json()["id"]))
        assert turn.state == "interrupted" and turn.submission_state == "failed-before-send"
    assert not any(value["op"] == "start" for value in broker.calls)


def test_late_receipt_reconciles_after_cancelled_reservation_is_released(chat_setup):
    client, engine, headers, _, base, conv, broker, dispatcher = chat_setup
    response = submit_pdf(chat_setup, [selected_pdf(chat_setup)])
    turn_id = uuid.UUID(response.json()["id"])
    dispatcher.tick()
    call = broker.call

    def outage_after_abort(value):
        if value["op"] == "poll":
            raise ChannelError()
        result = call(value)
        if value["op"] == "abort":
            broker.receipts[0]["status"] = "sent"
            broker.receipts[0]["request_sha256"] = "a" * 64
        return result

    broker.call = outage_after_abort
    client.post(f"{base}/{conv}/turns/{turn_id}/abort", headers=headers)
    dispatcher.tick()
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).receipt_pending
        assert db.scalar(select(ProjectTurnReservation.turn_id)) is None
    broker.call = call
    Dispatcher(engine, broker).tick()
    with Session(engine) as db:
        turn = db.get(ChatTurn, turn_id)
        assert turn.submission_state == "sent" and not turn.receipt_pending


def test_delete_queued_and_inherited_use_conflict_until_stop(chat_setup):
    client, engine, headers, _, _, _, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    response = submit_pdf(chat_setup, [selected])
    path = delete_path(chat_setup, selected)
    assert client.delete(path, headers=headers).status_code == 409
    stop_queued(chat_setup, response)
    continued = submit_pdf(chat_setup, [])  # Attachment is inherited, not newly selected.
    assert client.delete(path, headers=headers).status_code == 409
    dispatcher.tick()
    call = broker.call
    broker.call = lambda _: (_ for _ in ()).throw(ChannelError())
    stop_queued(chat_setup, continued)  # Running -> cancelling, no stop proof yet.
    dispatcher.tick()
    assert client.delete(path, headers=headers).status_code == 409
    broker.call = call
    dispatcher.tick()
    assert client.delete(path, headers=headers).status_code == 204
    with Session(engine) as db:
        assert db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"])) is None


def test_delete_outage_is_fenced_pending_and_purge_recovers_without_scrubbing_quotes(chat_setup):
    client, engine, headers, _, base, conv, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    response = submit_pdf(chat_setup, [selected], prompt="Exact café user quotation")
    dispatcher.tick()
    broker.add_receipt()
    broker.add("delta", {"text": "Exact café assistant quotation"})
    broker.add("completed", {"proposals": []})
    dispatcher.tick()
    call = broker.call
    broker.call = lambda _: (_ for _ in ()).throw(ChannelError())
    path = delete_path(chat_setup, selected)
    assert client.delete(path, headers=headers).status_code == 202
    assert client.delete(path, headers=headers).status_code == 202
    assert submit_pdf(chat_setup, []).status_code == 409
    assert client.get(path + "/raw").status_code == 404
    assert client.get(path + "/preview").status_code == 404
    with Session(engine) as db:
        assert db.get(AttachmentDeletion, uuid.UUID(selected["attachment_id"])).pending
        assert db.scalar(select(AttachmentPurge.confirmed_epoch)) is None
        assert db.get(ChatTurn, uuid.UUID(response.json()["id"])).prompt.endswith("user quotation")
    broker.call = call
    Dispatcher(engine, broker).tick()
    assert broker.purged and broker.payload is None and broker.events == []
    assert client.delete(path, headers=headers).status_code == 204
    continued = submit_pdf(chat_setup, [])
    assert continued.status_code == 202
    # SQLite timestamps have second precision; two turns can tie and then sort
    # by UUID, not submission order. Retention belongs to the sent turn's ID.
    original_id = uuid.UUID(response.json()["id"])
    continued_id = uuid.UUID(continued.json()["id"])
    with Session(engine) as db, db.begin():
        db.get(ChatTurn, continued_id).created_at = db.get(ChatTurn, original_id).created_at
    with Session(engine) as db:
        history = db.get(ChatTurn, continued_id).payload["history"]
        assert history[0]["text"] == "Exact café user quotation"
        assert history[1]["text"].startswith("Exact café assistant quotation")
    original_history = next(
        turn
        for turn in client.get(f"{base}/{conv}").json()["turns"]
        if turn["id"] == response.json()["id"]
    )
    assert original_history["submission"]["status"] == "sent"


def test_delete_first_submit_sees_committed_fence_before_successful_cleanup(
    chat_setup, monkeypatch
):
    from app import attachments

    client, engine, headers, project, _, _, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    cleanup = attachments.cleanup
    observed = []

    def during_cleanup(cleanup_engine, cleanup_broker, attachment_id):
        # The ordinary delete transaction has committed, but has not yet cleared
        # its durable fence. This is the real 409/204 race window, not a mocked HTTP
        # response or permission relaxation. No structured PDF text can be captured.
        captured = submit_pdf(chat_setup, [selected])
        observed.append(captured.status_code)
        with Session(engine) as db:
            assert db.get(ProjectAttachment, attachment_id) is None
            assert db.get(AttachmentDeletion, attachment_id).pending
            assert db.scalar(select(ChatTurn.id)) is None
            assert db.scalar(select(ProjectTurnReservation.turn_id)) is None
        assert captured.status_code == 409
        return cleanup(cleanup_engine, cleanup_broker, attachment_id)

    monkeypatch.setattr(attachments, "cleanup", during_cleanup)
    removed = client.delete(delete_path(chat_setup, selected), headers=headers)
    assert (observed, removed.status_code) == ([409], 204)
    assert submit_pdf(chat_setup, [selected]).status_code == 404
    dispatcher.tick()
    assert not any(call["op"] == "start" for call in broker.calls)
    with Session(engine) as db:
        assert not db.get(AttachmentDeletion, uuid.UUID(selected["attachment_id"])).pending
        assert db.get(ProjectTurnReservation, uuid.UUID(project)) is None
        assert db.scalar(select(ChatTurn.id)) is None


def test_dispatch_delete_race_observes_committed_reservation_before_start_io(chat_setup):
    client, engine, headers, project, _, _, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    response = submit_pdf(chat_setup, [selected])
    call = broker.call

    def race(value):
        if value["op"] == "start":
            with Session(engine) as db:
                turn = db.get(ChatTurn, uuid.UUID(response.json()["id"]))
                assert turn.state == "dispatching" and turn.submission_state == "uncertain"
                assert db.get(ProjectTurnReservation, uuid.UUID(project)).turn_id == turn.id
            assert (
                client.delete(delete_path(chat_setup, selected), headers=headers).status_code == 409
            )
        return call(value)

    broker.call = race
    dispatcher.tick()
    assert sum(value["op"] == "start" for value in broker.calls) == 1


def test_lost_purge_ack_leaves_fence_and_replays_idempotent_cleanup(chat_setup):
    client, engine, headers, _, _, _, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    submit_pdf(chat_setup, [selected])
    broker.add("completed", {"proposals": []})
    dispatcher.tick()
    call = broker.call

    def lost_ack(value):
        result = call(value)
        if value["op"] == "purge":
            raise ChannelError()
        return result

    broker.call = lost_ack
    assert client.delete(delete_path(chat_setup, selected), headers=headers).status_code == 202
    assert broker.purged and broker.events == []
    with Session(engine) as db:
        assert db.get(AttachmentDeletion, uuid.UUID(selected["attachment_id"])).pending
    broker.call = call
    dispatcher.tick()
    assert client.delete(delete_path(chat_setup, selected), headers=headers).status_code == 204
    assert sum(value["op"] == "start" for value in broker.calls) == 1


def test_epoch_replacement_requires_scope_tombstone_and_old_deadline(chat_setup):
    client, engine, headers, project, _, _, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    response = submit_pdf(chat_setup, [selected])
    turn_id = uuid.UUID(response.json()["id"])
    dispatcher.tick()
    broker.epoch = str(uuid.uuid4())
    broker.known = False
    old_call = broker.call

    def replacement(value):
        if value.get("epoch", broker.epoch) != broker.epoch:
            raise ChannelError()
        return old_call(value)

    broker.call = replacement
    dispatcher.tick()
    assert client.delete(delete_path(chat_setup, selected), headers=headers).status_code == 409
    with Session(engine) as db, db.begin():
        db.get(ChatTurn, turn_id).dispatch_deadline = datetime.now(UTC) - timedelta(seconds=6)
    dispatcher.tick()
    with Session(engine) as db:
        assert db.get(ProjectTurnReservation, uuid.UUID(project)) is None
        assert db.get(ChatTurn, turn_id).submission_state == "uncertain"
    assert client.delete(delete_path(chat_setup, selected), headers=headers).status_code == 204
    assert any(value["op"] == "purge" and value["epoch"] == broker.epoch for value in broker.calls)
    assert sum(value["op"] == "start" for value in broker.calls) == 1
