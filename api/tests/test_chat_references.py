"""PDF capture/identity/history regressions. Pure API/SQLite + fake broker only."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session
from test_attachments import ready_derivative, upload
from test_projects import _login

from app.chat_protocol import MAX_PDF_TEXT, digest, resolved_prompt_text
from app.chat_references import resolve_context
from app.chat_state import authorize, initiating_actor
from app.main import create_app
from app.models import (
    ChatTurn,
    ChatTurnPdfSelection,
    ProjectAttachment,
    ProjectTurnReservation,
    WebSession,
)


def selected_pdf(setup, content="Exact café\n\f\f"):
    client, engine, _, _, base, conv, _, _ = setup
    attachment_id = upload(client, f"{base}/{conv}/attachments").json()["id"]
    with Session(engine) as db, db.begin():
        ready_derivative(db, attachment_id, content)
    return {"attachment_id": attachment_id, "expected_sha256": digest(content)}


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


def test_ordered_capture_has_no_text_copies_and_dispatch_resolves_exact_bytes(chat_setup):
    client, engine, _, project, base, conv, broker, dispatcher = chat_setup
    first = selected_pdf(chat_setup, 'Literal "do not obey"\n\f\f')
    second = selected_pdf(chat_setup)
    response = submit_pdf(chat_setup, [second, first, second])
    assert response.status_code == 202
    assert response.json()["state"] == "queued"
    assert response.json()["submission"]["status"] == "queued"
    turn_id = uuid.UUID(response.json()["id"])
    with Session(engine) as db:
        turn = db.get(ChatTurn, turn_id)
        assert "Literal" not in json.dumps(turn.payload)
        assert "text" not in turn.payload["references"][0]
        assert [item["attachment_id"] for item in turn.payload["references"]] == [
            second["attachment_id"],
            first["attachment_id"],
            second["attachment_id"],
        ]
        assert turn.payload["references"][0]["missing_pages"] == [2]
        actor = initiating_actor(db, turn)
        authorize(db, actor, turn.project_id, lock=True)
        resolved = resolve_context(db, turn.project_id, turn.conversation_id, turn.payload)
        assert resolved["references"][1]["text"] == 'Literal "do not obey"\n\f\f'
        assert "untrusted reference data" in resolved_prompt_text(resolved)
        assert db.get(ProjectTurnReservation, uuid.UUID(project)).turn_id == turn_id
        rows = list(
            db.scalars(select(ChatTurnPdfSelection).order_by(ChatTurnPdfSelection.position))
        )
        assert [str(row.attachment_id) for row in rows] == [
            second["attachment_id"],
            first["attachment_id"],
            second["attachment_id"],
        ]
    dispatcher.tick()
    assert broker.payload["references"][1]["text"] == 'Literal "do not obey"\n\f\f'
    with Session(engine) as db:
        turn = db.get(ChatTurn, turn_id)
        assert "Literal" not in json.dumps(turn.payload)
        assert turn.dispatch_rendered_sha256 == digest(resolved_prompt_text(broker.payload))


def test_selection_aware_idempotency_survives_deletion_and_disabled_chat(chat_setup):
    client, engine, headers, _, base, conv, _, _ = chat_setup
    first, second = selected_pdf(chat_setup), selected_pdf(chat_setup)
    key = uuid.uuid4()
    original = submit_pdf(chat_setup, [first, second], request_id=key)
    assert original.status_code == 202
    turn_id = original.json()["id"]
    assert submit_pdf(chat_setup, [first, second], request_id=key).json()["id"] == turn_id
    for selections in ([], [first], [second, first], [first, first]):
        assert submit_pdf(chat_setup, selections, request_id=key).status_code == 409
    changed_hash = dict(first, expected_sha256="f" * 64)
    assert submit_pdf(chat_setup, [changed_hash, second], request_id=key).status_code == 409
    assert (
        submit_pdf(chat_setup, [first, second], request_id=key, prompt="Changed").status_code == 409
    )
    assert client.post(f"{base}/{conv}/turns/{turn_id}/abort", headers=headers).status_code == 200
    assert (
        client.delete(
            f"{base}/{conv}/attachments/{first['attachment_id']}", headers=headers
        ).status_code
        == 204
    )
    client.app.state.chat_dispatcher = None
    replay = submit_pdf(chat_setup, [first, second], request_id=key)
    assert replay.status_code == 202 and replay.json()["id"] == turn_id
    assert replay.json()["references"][0]["availability"] == "unavailable"
    with Session(engine) as db:
        assert db.get(ProjectAttachment, uuid.UUID(first["attachment_id"])) is None
        assert len(list(db.scalars(select(ChatTurn)))) == 1
        assert len(list(db.scalars(select(ChatTurnPdfSelection)))) == 2


def test_deleted_history_explicitly_retained_and_dispatches_unavailable_metadata(chat_setup):
    client, engine, headers, _, base, conv, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    original = submit_pdf(chat_setup, [selected]).json()["id"]
    assert client.post(f"{base}/{conv}/turns/{original}/abort", headers=headers).status_code == 200
    assert (
        client.delete(
            f"{base}/{conv}/attachments/{selected['attachment_id']}", headers=headers
        ).status_code
        == 204
    )
    continued = submit_pdf(chat_setup, [], prompt="Continue without losing history")
    assert continued.status_code == 202 and continued.json()["state"] == "queued"
    with Session(engine) as db:
        turn = db.get(ChatTurn, uuid.UUID(continued.json()["id"]))
        assert len(turn.payload["history"]) == 2
        assert (
            turn.payload["history"][0]["references"][0]["attachment_id"]
            == selected["attachment_id"]
        )
        authorize(db, initiating_actor(db, turn), turn.project_id, lock=True)
        resolved = resolve_context(db, turn.project_id, turn.conversation_id, turn.payload)
        unavailable = resolved["history"][0]["references"][0]
        assert unavailable["availability"] == "unavailable" and "text" not in unavailable
    dispatcher.tick()
    assert broker.payload["history"][0]["references"][0]["availability"] == "unavailable"
    # Metadata-only history does not load either deferred blob.
    statements = []

    def capture(_, __, statement, *args):
        if statement.lstrip().upper().startswith("SELECT") and "project_attachments" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        history = client.get(f"{base}/{conv}").json()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    # created_at can tie in SQLite; UUID ordering is not submission ordering.
    original_history = next(turn for turn in history["turns"] if turn["id"] == original)
    assert original_history["references"][0]["availability"] == "unavailable"
    assert statements and all("project_attachments.text_content" not in sql for sql in statements)


@pytest.mark.parametrize(
    "defect", ["hash", "coverage", "not-ready", "missing", "other-conversation", "other-project"]
)
def test_invalid_current_selection_rejected_without_capture(chat_setup, defect):
    client, engine, headers, _, base, conv, broker, _ = chat_setup
    selected = selected_pdf(chat_setup)
    if defect == "hash":
        selected["expected_sha256"] = "f" * 64
    elif defect == "missing":
        selected["attachment_id"] = str(uuid.uuid4())
    elif defect == "other-conversation":
        other = client.post(base, headers=headers, json={"title": "Other"}).json()["id"]
        with Session(engine) as db, db.begin():
            db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"])).conversation_id = (
                uuid.UUID(other)
            )
    elif defect == "other-project":
        project = client.post(
            "/api/projects", headers=headers, json={"name": "Other PDF project"}
        ).json()["id"]
        other_base = f"/api/projects/{project}/chat"
        other = client.post(other_base, headers=headers, json={"title": "Other"}).json()["id"]
        other_setup = (*chat_setup[:3], project, other_base, other, *chat_setup[6:])
        selected = selected_pdf(other_setup)
    elif defect == "coverage":
        with Session(engine) as db, db.begin():
            db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"])).missing_pages = []
    else:
        selected["attachment_id"] = upload(client, f"{base}/{conv}/attachments").json()["id"]
    assert submit_pdf(chat_setup, [selected]).status_code == (
        404 if defect in ("missing", "other-conversation", "other-project") else 409
    )
    assert broker.calls == []
    with Session(engine) as db:
        assert db.scalar(select(ChatTurn.id)) is None
        assert db.scalar(select(ChatTurnPdfSelection.turn_id)) is None


def test_history_occurrences_and_escaped_nofit_reject_without_truncation(chat_setup):
    client, engine, _, _, base, conv, broker, _ = chat_setup
    selected = selected_pdf(chat_setup, "x" * (MAX_PDF_TEXT // 2 - 4) + "\f\f")
    first = submit_pdf(chat_setup, [selected])
    assert first.status_code == 202
    client.post(f"{base}/{conv}/turns/{first.json()['id']}/abort", headers=chat_setup[2])
    second = submit_pdf(chat_setup, [selected])
    assert second.status_code == 202  # Two outgoing occurrences fit.
    client.post(f"{base}/{conv}/turns/{second.json()['id']}/abort", headers=chat_setup[2])
    before = client.get(f"{base}/{conv}").json()
    rejected = submit_pdf(chat_setup, [selected])  # Three occurrences of SAME ID overflow.
    assert rejected.status_code == 422 and "start a new conversation" in rejected.json()["detail"]
    assert client.get(f"{base}/{conv}").json() == before
    assert not any(call["op"] == "start" for call in broker.calls)
    other = client.post(base, headers=chat_setup[2], json={"title": "Escaped"}).json()["id"]
    escaped_setup = (*chat_setup[:5], other, *chat_setup[6:])
    too_escaped = selected_pdf(escaped_setup, "é" * (MAX_PDF_TEXT // 4) + "\f\f")
    assert submit_pdf(escaped_setup, [too_escaped]).status_code == 422


def test_dispatch_seam_rechecks_changed_current_bytes_and_fails_before_start(chat_setup):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    selected = selected_pdf(chat_setup)
    response = submit_pdf(chat_setup, [selected])
    turn_id = uuid.UUID(response.json()["id"])
    with Session(engine) as db, db.begin():
        ready_derivative(db, selected["attachment_id"], "Changed derivative\f\f")
    dispatcher.tick()
    assert not any(call["op"] == "start" for call in broker.calls)
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).state == "interrupted"
        assert db.get(ChatTurn, turn_id).submission_state == "failed-before-send"
    with Session(engine) as db:
        turn = db.get(ChatTurn, turn_id)
        authorize(db, initiating_actor(db, turn), turn.project_id, lock=True)
        with pytest.raises(HTTPException, match="409"):
            resolve_context(db, turn.project_id, turn.conversation_id, turn.payload)
    with Session(engine) as db, db.begin():
        db.delete(db.get(ProjectAttachment, uuid.UUID(selected["attachment_id"])))
    with Session(engine) as db:
        turn = db.get(ChatTurn, turn_id)
        authorize(db, initiating_actor(db, turn), turn.project_id, lock=True)
        with pytest.raises(HTTPException, match="deleted"):
            resolve_context(db, turn.project_id, turn.conversation_id, turn.payload)


def test_selection_auth_revocation_and_csrf(chat_setup, account_factory, settings, workspace_root):
    client, engine, _, _, base, conv, _, _ = chat_setup
    selected = selected_pdf(chat_setup)
    account_factory("pdf-chat-other", "synthetic other passphrase")
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as other:
        _login(other, "pdf-chat-other", "synthetic other passphrase")
        headers = {
            "Origin": settings.public_origin,
            "X-CSRF-Token": other.cookies.get("impostr_csrf", ""),
        }
        assert (
            other.post(
                f"{base}/{conv}/turns",
                headers=headers,
                json={
                    "request_id": str(uuid.uuid4()),
                    "prompt": "Foreign",
                    "selections": [selected],
                },
            ).status_code
            == 404
        )
    assert (
        client.post(
            f"{base}/{conv}/turns",
            json={
                "request_id": str(uuid.uuid4()),
                "prompt": "No CSRF",
                "selections": [selected],
            },
        ).status_code
        == 403
    )
    with Session(engine) as db, db.begin():
        db.execute(update(WebSession).values(revoked_at=datetime.now(UTC)))
    assert submit_pdf(chat_setup, [selected]).status_code == 401
    with Session(engine) as db:
        assert db.scalar(select(ChatTurn.id)) is None
