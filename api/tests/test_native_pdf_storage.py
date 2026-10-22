"""Native capture/availability regressions using the existing API/SQLite seam."""

import hashlib
import json
import uuid
from dataclasses import replace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from imp025_native_fixture import submit_pdf
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from test_attachments import PDF, ready_derivative, upload
from test_projects import _login

from app.chat_protocol import NATIVE_PDF_REFERENCE, inline_pdf_data, native_dispatch_context
from app.chat_references import legacy_reference_metadata, resolve_context, resolve_dispatch_context
from app.main import create_app
from app.models import ChatSubmissionReceipt, ChatTurn, ChatTurnPdfSelection, ProjectAttachment


def selected_original(setup, body=PDF):
    client, _, _, _, base, conv, _, _ = setup
    response = upload(client, f"{base}/{conv}/attachments", body)
    assert response.status_code == 201
    return {
        "attachment_id": response.json()["id"],
        "expected_sha256": response.json()["original_sha256"],
    }


def test_ordered_original_capture_is_binary_free_and_only_dispatch_gets_authorized_bytes(
    chat_setup,
):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    first = selected_original(chat_setup, b"%PDF-first exact bytes")
    second = selected_original(chat_setup, b"%PDF-second exact bytes")
    response = submit_pdf(chat_setup, [second, first, second])
    assert response.status_code == 202
    turn_id = uuid.UUID(response.json()["id"])
    with Session(engine) as db:
        turn = db.get(ChatTurn, turn_id)
        references = turn.payload["references"]
        assert [item["attachment_id"] for item in references] == [
            second["attachment_id"],
            first["attachment_id"],
            second["attachment_id"],
        ]
        assert all(item["kind"] == NATIVE_PDF_REFERENCE for item in references)
        assert all(
            set(item) == {"kind", "attachment_id", "filename", "original_sha256", "original_size"}
            for item in references
        )
        assert "exact bytes" not in json.dumps(turn.payload)
        assert [
            row.expected_sha256
            for row in db.scalars(
                select(ChatTurnPdfSelection).order_by(ChatTurnPdfSelection.position)
            )
        ] == [second["expected_sha256"], first["expected_sha256"], second["expected_sha256"]]
        resolved = resolve_context(db, turn.project_id, turn.conversation_id, turn.payload)
        assert all(set(item) == {"reference", "availability"} for item in resolved["references"])
    dispatcher.tick()
    starts = [call for call in broker.calls if call["op"] == "start"]
    assert len(starts) == 1
    dispatched = native_dispatch_context(starts[0]["payload"])
    assert [item["manifest"]["attachment_id"] for item in dispatched["files"]] == [
        second["attachment_id"],
        first["attachment_id"],
        second["attachment_id"],
    ]
    for item in dispatched["files"]:
        inline_pdf_data(item["url"], item["manifest"])
    dispatcher.tick()
    assert len([call for call in broker.calls if call["op"] == "start"]) == 1  # Poll, never resend.
    with Session(engine) as db:
        turn = db.get(ChatTurn, turn_id)
        assert turn.submission_state == "uncertain" and turn.broker_epoch == uuid.UUID(broker.epoch)
        assert "base64" not in json.dumps(turn.payload) and "url" not in json.dumps(
            turn.dispatch_manifest
        )
        assert not list(
            db.scalars(select(ChatSubmissionReceipt))
        )  # Worker ACK is NOT sent evidence.


def test_inline_history_preserves_each_original_occurrence(chat_setup):
    from copy import deepcopy

    _, engine, _, _, _, _, _, _ = chat_setup
    selected = selected_original(chat_setup, b"%PDF-original history bytes")
    response = submit_pdf(chat_setup, [selected])
    with Session(engine) as db:
        turn = db.get(ChatTurn, uuid.UUID(response.json()["id"]))
        captured = deepcopy(turn.payload)
        captured["history"] = [
            dict(
                role="user",
                text="Quoted prior request",
                references=deepcopy(captured["references"]),
            )
        ]
        dispatch = resolve_dispatch_context(db, turn.project_id, turn.conversation_id, captured)
        assert len(dispatch["files"]) == 2
        assert [item["manifest"]["message_index"] for item in dispatch["files"]] == [0, 1]
        assert dispatch["files"][0]["url"] == dispatch["files"][1]["url"]


def test_original_hash_and_bytes_revalidated_and_derivative_not_required(chat_setup):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    selected = selected_original(chat_setup)
    assert submit_pdf(chat_setup, [dict(selected, expected_sha256="f" * 64)]).status_code == 409
    response = submit_pdf(chat_setup, [selected])
    assert response.status_code == 202
    with Session(engine) as db, db.begin():
        row = db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"]))
        assert row.status == "stored" and row.text_content is None
        row.original = row.original.replace(b"Synthetic", b"Altered!!")  # Same byte length.
    dispatcher.tick()
    assert not any(call["op"] == "start" for call in broker.calls)
    with Session(engine) as db:
        turn = db.get(ChatTurn, uuid.UUID(response.json()["id"]))
        with pytest.raises(HTTPException, match="changed"):
            resolve_context(db, turn.project_id, turn.conversation_id, turn.payload)


def test_deletion_idempotency_and_unavailable_history_without_binary_metadata(chat_setup):
    client, engine, headers, _, base, conv, _, _ = chat_setup
    selected = selected_original(chat_setup)
    key = uuid.uuid4()
    first = submit_pdf(chat_setup, [selected], request_id=key)
    turn_id = first.json()["id"]
    assert submit_pdf(chat_setup, [], request_id=key).status_code == 409
    assert client.post(f"{base}/{conv}/turns/{turn_id}/abort", headers=headers).status_code == 200
    assert (
        client.delete(
            f"{base}/{conv}/attachments/{selected['attachment_id']}", headers=headers
        ).status_code
        == 204
    )
    assert submit_pdf(chat_setup, [selected], request_id=key).json()["id"] == turn_id
    resumed = submit_pdf(chat_setup, [])
    assert resumed.status_code == 202
    with Session(engine) as db:
        turn = db.get(ChatTurn, uuid.UUID(resumed.json()["id"]))
        resolved = resolve_context(db, turn.project_id, turn.conversation_id, turn.payload)
        assert resolved["history"][0]["references"][0]["availability"] == "unavailable"
        assert resolved["history"][0]["references"][0]["reference"]["kind"] == NATIVE_PDF_REFERENCE
    statements = []

    def capture(_, __, statement, *args):
        if statement.lstrip().upper().startswith("SELECT") and "project_attachments" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        client.get(f"{base}/{conv}")
        client.get(f"{base}/{conv}/attachments")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements
    assert all(
        "project_attachments.original," not in sql and "project_attachments.text_content" not in sql
        for sql in statements
    )


def test_legacy_receipt_and_replay_hash_semantics_are_not_relabelled(chat_setup):
    client, engine, headers, _, base, conv, _, _ = chat_setup
    selected = selected_original(chat_setup)
    key = uuid.uuid4()
    response = submit_pdf(chat_setup, [selected], request_id=key)
    turn_id = uuid.UUID(response.json()["id"])
    client.post(f"{base}/{conv}/turns/{turn_id}/abort", headers=headers)
    with Session(engine) as db, db.begin():
        ready_derivative(db, selected["attachment_id"], PDF.decode())
        row = db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"]))
        row.status = "stored"  # Retained legacy derivative after forward transition.
        legacy = legacy_reference_metadata(row)
        assert legacy["text_sha256"] == selected["expected_sha256"]  # Hash collision in domains.
        turn = db.get(ChatTurn, turn_id)
        turn.payload = dict(turn.payload, references=[legacy])
        turn.dispatch_manifest = [[{"reference": legacy, "availability": "available"}]]
        turn.submission_state = "sent"
        db.get(ChatTurnPdfSelection, (turn_id, 0)).reference_kind = "legacy-text-v1"
        db.add(
            ChatSubmissionReceipt(turn_id=turn_id, call=1, status="sent", request_sha256="a" * 64)
        )
    assert submit_pdf(chat_setup, [selected], request_id=key).status_code == 409
    legacy_selection = dict(selected, reference_kind="legacy-text-v1")
    replay = submit_pdf(chat_setup, [legacy_selection], request_id=key)
    assert replay.status_code == 202 and replay.json()["id"] == str(turn_id)
    assert replay.json()["submission"]["status"] == "sent"
    assert submit_pdf(chat_setup, [legacy_selection]).status_code == 409
    view = client.get(f"{base}/{conv}").json()["turns"][0]
    assert view["submission"]["status"] == "sent"
    assert view["submission"]["reference_kind"] == "legacy-text-v1"
    assert "kind" not in view["submission"]["manifest"][0][0]["reference"]
    assert view["references"][0]["availability"] == "unavailable"
    assert submit_pdf(chat_setup, []).status_code == 202  # Legacy history retained as unavailable.


def test_admission_charges_original_occurrences_from_prior_turns_without_truncation(chat_setup):
    client, engine, headers, _, base, conv, broker, _ = chat_setup
    body = b"%PDF-" + b"x" * (24_999_999 - 5)
    selected = selected_original(chat_setup, body)
    for _ in range(2):
        accepted = submit_pdf(chat_setup, [selected])
        assert accepted.status_code == 202
        assert (
            client.post(
                f"{base}/{conv}/turns/{accepted.json()['id']}/abort", headers=headers
            ).status_code
            == 200
        )
    before = client.get(f"{base}/{conv}").json()
    rejected = submit_pdf(chat_setup, [selected])  # Three copies of the same original overflow.
    assert rejected.status_code == 422 and "nothing was truncated" in rejected.json()["detail"]
    assert client.get(f"{base}/{conv}").json() == before
    assert not any(call["op"] == "start" for call in broker.calls)
    with Session(engine) as db:
        assert len(list(db.scalars(select(ChatTurn)))) == 2


def test_foreign_conversation_and_account_original_selection_denied(
    chat_setup, account_factory, settings, workspace_root
):
    client, engine, headers, _, base, conv, _, _ = chat_setup
    selected = selected_original(chat_setup)
    other_conv = client.post(base, headers=headers, json={"title": "Other"}).json()["id"]
    foreign_setup = (*chat_setup[:5], other_conv, *chat_setup[6:])
    assert submit_pdf(foreign_setup, [selected]).status_code == 404
    account_factory("native-other", "synthetic native passphrase")
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as other:
        _login(other, "native-other", "synthetic native passphrase")
        other_headers = {
            "Origin": settings.public_origin,
            "X-CSRF-Token": other.cookies["impostr_csrf"],
        }
        assert (
            other.post(
                f"{base}/{conv}/turns",
                headers=other_headers,
                json={
                    "request_id": str(uuid.uuid4()),
                    "prompt": "Foreign",
                    "selections": [selected],
                },
            ).status_code
            == 404
        )


def test_oversized_legacy_original_download_delete_but_not_capture_and_no_original_honest(
    chat_setup,
):
    client, engine, headers, _, base, conv, _, _ = chat_setup
    selected = selected_original(chat_setup)
    body = b"%PDF-" + b"x" * (50_000_000 - 5)
    with Session(engine) as db, db.begin():
        row = db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"]))
        row.original = body
        row.original_size = len(body)
        row.original_sha256 = hashlib.sha256(body).hexdigest()
        selected["expected_sha256"] = row.original_sha256
    path = f"{base}/{conv}/attachments/{selected['attachment_id']}"
    assert client.get(path).json()["native_available"] is False
    assert client.get(path + "/raw").content == body
    assert submit_pdf(chat_setup, [selected]).status_code == 409
    assert client.delete(path, headers=headers).status_code == 204
    failed = upload(client, f"{base}/{conv}/attachments", b"invalid").json()["attachment"]
    assert failed["native_available"] is False and failed["original_sha256"] is None
    assert client.get(f"{base}/{conv}/attachments/{failed['id']}/raw").status_code == 404


def test_startup_disables_legacy_processor_even_when_old_pdf_setting_enabled(
    engine, settings, workspace_root
):
    enabled = replace(settings, pdf_enabled=True)
    with TestClient(create_app(engine, enabled, workspace_root=workspace_root)) as client:
        assert client.app.state.pdf_processor is None
