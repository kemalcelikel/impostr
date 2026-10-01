from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_projects import _login

from app.chat_dispatch import Dispatcher
from app.chat_protocol import MAX_PRIOR_TURNS, MAX_TEXT, ChannelError
from app.config import AppSettings
from app.main import create_app
from app.models import (
    AgentDocumentProposal,
    ChatInteraction,
    ChatTurn,
    Project,
    ProjectDocument,
    ProjectDocumentRevision,
    ProjectTurnReservation,
    WebSession,
)


class FakeBroker:
    """Pure deterministic channel double; never starts the boundary."""

    def __init__(self):
        self.epoch = str(uuid.uuid4())
        self.calls = []
        self.events = []
        self.known = True
        self.fail_start = False
        self.mode = "planning"
        self.admitting = True

    def call(self, value):
        self.calls.append(value)
        if value["op"] == "hello":
            return {"ok": True, "epoch": self.epoch, "mode": self.mode, "admitting": self.admitting}
        if value["op"] == "start" and self.fail_start:
            raise ChannelError()
        if value["op"] == "poll":
            return {
                "ok": True,
                "epoch": self.epoch,
                "known": self.known,
                "events": [row for row in self.events if row["sequence"] > value["after"]][:16],
            }
        return {"ok": True, "epoch": self.epoch, "stopped": True}

    def add(self, kind, data):
        if not self.events and kind != "started":
            self.add(
                "started", {"native_session_id": "ses_synthetic", "context_reconstructed": False}
            )
        self.events.append(
            {"sequence": len(self.events) + 1, "event": {"type": kind, "data": data}}
        )


@pytest.fixture
def chat_setup(client, engine, account_factory):
    account_factory("chat-owner", "synthetic chat passphrase")
    _login(client, "chat-owner", "synthetic chat passphrase")
    headers = {
        "Origin": "http://127.0.0.1:8080",
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }
    project = client.post("/api/projects", json={"name": "Synthetic chat"}, headers=headers).json()[
        "id"
    ]
    base = f"/api/projects/{project}/chat"
    first = client.post(base, json={"title": "Planning"}, headers=headers)
    assert first.status_code == 201
    conv = first.json()["id"]
    broker = FakeBroker()
    dispatcher = Dispatcher(engine, broker)
    # Injectable pure test seam; no startup of actual Unix/bwrap boundary.
    client.app.state.settings = AppSettings(
        public_origin="http://127.0.0.1:8080",
        rate_limit_key=b"test-only-rate-limit-key-that-is-not-a-secret",
        chat_enabled=True,
    )
    client.app.state.chat_dispatcher = dispatcher
    yield client, engine, headers, project, base, conv, broker, dispatcher
    client.app.state.chat_dispatcher = None


def submit(setup, request_id=None, prompt="Synthetic planning"):
    client, _, headers, _, base, conv, _, _ = setup
    return client.post(
        f"{base}/{conv}/turns",
        json={"request_id": str(request_id or uuid.uuid4()), "prompt": prompt},
        headers=headers,
    )


@pytest.mark.parametrize("mode", ["synthetic", "operator", "unknown", None])
def test_normal_api_denies_nonplanning_mode_and_keeps_history(chat_setup, mode):
    client, engine, _, _, base, conv, broker, dispatcher = chat_setup
    request_id = uuid.uuid4()
    turn = submit(chat_setup, request_id).json()["id"]
    broker.mode = mode
    # Existing idempotent history remains accessible even when mode disappears.
    assert submit(chat_setup, request_id).json()["id"] == turn
    dispatcher.tick()
    assert not any(call["op"] == "start" for call in broker.calls)
    assert client.get(f"{base}/{conv}").json()["turns"][0]["state"] == "interrupted"
    assert client.get(f"{base}/{conv}/events").status_code == 200
    assert submit(chat_setup).status_code == 503
    with Session(engine) as db:
        assert len(list(db.scalars(select(ChatTurn)))) == 1


def test_capacity_and_broker_outage_refuse_admission_without_losing_text(chat_setup):
    client, _, _, _, base, conv, broker, dispatcher = chat_setup
    request_id = uuid.uuid4()
    submit(chat_setup, request_id)
    broker.add("delta", {"text": "Safe partial survives outage"})
    dispatcher.tick()
    broker.admitting = False
    # Capacity blocks only NEW dispatch; existing turn can finish and replay.
    broker.add("completed", {"proposals": []})
    dispatcher.tick()
    assert submit(chat_setup).status_code == 503
    original_call = broker.call
    broker.call = lambda _: (_ for _ in ()).throw(ChannelError())
    assert submit(chat_setup).status_code == 503
    assert submit(chat_setup, request_id).status_code == 202
    assert any(
        row["data"].get("text") == "Safe partial survives outage"
        for row in client.get(f"{base}/{conv}/events").json()["events"]
    )
    broker.call = original_call


def test_synthetic_scope_is_specific_to_generated_actor_project_pair(chat_setup):
    _, _, _, project, _, _, broker, dispatcher = chat_setup
    with Session(dispatcher.engine) as db:
        owner = db.get(Project, uuid.UUID(project)).owner_user_id
    broker.mode = "synthetic"
    dispatcher.test_scope = lambda pid, uid: pid == uuid.UUID(project) and uid == owner
    assert submit(chat_setup).status_code == 202
    dispatcher.test_scope = lambda pid, uid: False
    dispatcher.tick()
    assert not any(call["op"] == "start" for call in broker.calls)


def test_disabled_auth_csrf_last_tab_and_cross_project(
    chat_setup, account_factory, settings, workspace_root: Path
):
    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    client.app.state.chat_dispatcher = None
    assert submit(chat_setup).status_code == 503
    client.app.state.chat_dispatcher = dispatcher
    assert (
        client.post(
            f"{base}/{conv}/turns", json={"request_id": str(uuid.uuid4()), "prompt": "Hi"}
        ).status_code
        == 403
    )
    second = client.post(base, json={"title": "Second"}, headers=headers).json()["id"]
    assert client.put(f"{base}/{conv}/last-used", headers=headers).status_code == 200
    account_factory("chat-other", "synthetic other passphrase")
    with TestClient(create_app(engine, settings, workspace_root=workspace_root)) as other:
        _login(other, "chat-other", "synthetic other passphrase")
        assert other.get(base).status_code == 404
        assert other.get(f"{base}/{conv}/events").status_code == 404
        assert other.get(f"{base}/{conv}/stream").status_code == 404
        _login(other, "chat-owner", "synthetic chat passphrase")
        assert other.get(base).json()["last_conversation_id"] == conv
    assert second != conv
    assert broker.calls == []


def test_committed_idempotency_reservation_ordered_replay_and_restart(chat_setup):
    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    request_id = uuid.uuid4()
    first = submit(chat_setup, request_id)
    assert first.status_code == 202
    turn_id = first.json()["id"]
    assert submit(chat_setup, request_id).json()["id"] == turn_id
    assert submit(chat_setup, request_id, "Changed").status_code == 409
    assert submit(chat_setup).status_code == 409
    assert all(call["op"] == "hello" for call in broker.calls)
    with Session(engine) as db:
        assert db.get(ChatTurn, uuid.UUID(turn_id)).state == "queued"
        assert db.get(ProjectTurnReservation, uuid.UUID(project)).turn_id == uuid.UUID(turn_id)
    broker.add("started", {"native_session_id": "ses_synthetic", "context_reconstructed": False})
    broker.add("delta", {"text": "First partial"})
    dispatcher.tick()
    page = client.get(f"{base}/{conv}/events").json()["events"]
    assert [row["type"] for row in page] == ["queued", "started", "delta"]
    assert [row["sequence"] for row in page] == [1, 2, 3]
    assert client.get(f"{base}/{conv}/events?after={page[-1]['id']}").json()["events"] == []
    # API restart retains same broker epoch; no second dispatch, DB cursor replays.
    replacement = Dispatcher(engine, broker)
    replacement.tick()
    assert sum(call["op"] == "start" for call in broker.calls) == 1
    broker.add("completed", {"proposals": []})
    replacement.tick()
    with Session(engine) as db:
        assert db.get(ChatTurn, uuid.UUID(turn_id)).state == "completed"
        assert db.get(ProjectTurnReservation, uuid.UUID(project)) is None
    assert submit(chat_setup, request_id).json()["state"] == "completed"


@pytest.mark.parametrize("failure", ["start-outage", "broker-restart", "unknown-worker", "revoked"])
def test_unknown_dispatch_outage_revocation_interrupt_without_duplicate(chat_setup, failure):
    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    turn_id = uuid.UUID(submit(chat_setup).json()["id"])
    if failure == "start-outage":
        broker.fail_start = True
    dispatcher.tick()
    if failure == "broker-restart":
        broker.epoch = str(uuid.uuid4())
    elif failure == "unknown-worker":
        broker.known = False
    elif failure == "revoked":
        with Session(engine) as db, db.begin():
            db.execute(update(WebSession).values(revoked_at=datetime.now(UTC)))
    dispatcher.tick()
    dispatcher.tick()
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).state == "interrupted"
    assert sum(call["op"] == "start" for call in broker.calls) == 1
    if failure == "revoked":
        assert client.get(f"{base}/{conv}/events").status_code == 401
        assert client.get(f"{base}/{conv}/stream").status_code == 401


def test_interaction_policy_idempotency_abort_and_forged_scope(chat_setup):
    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    turn_id = submit(chat_setup).json()["id"]
    broker.add("permission", {"id": "per_synthetic", "permission": "edit", "once_allowed": True})
    dispatcher.tick()
    interaction = client.get(f"{base}/{conv}").json()["interactions"][0]["id"]
    path = f"{base}/{conv}/turns/{turn_id}/interactions/{interaction}/reply"
    assert (
        client.post(
            path,
            json={"request_id": str(uuid.uuid4()), "answer": {"reply": "always"}},
            headers=headers,
        ).status_code
        == 422
    )
    key = str(uuid.uuid4())
    payload = {"request_id": key, "answer": {"reply": "once"}}
    assert client.post(path, json=payload, headers=headers).status_code == 202
    assert client.post(path, json=payload, headers=headers).status_code == 202
    dispatcher.tick()
    assert sum(call["op"] == "reply" for call in broker.calls) == 1
    assert (
        client.post(
            path.replace(interaction, str(uuid.uuid4())), json=payload, headers=headers
        ).status_code
        == 404
    )
    assert client.post(f"{base}/{conv}/turns/{turn_id}/abort", headers=headers).status_code == 200
    dispatcher.tick()
    assert (
        client.post(
            path,
            json={"request_id": str(uuid.uuid4()), "answer": {"reply": "once"}},
            headers=headers,
        ).status_code
        == 409
    )
    with Session(engine) as db:
        assert db.get(ChatTurn, uuid.UUID(turn_id)).state == "cancelled"


def test_generated_import_conflict_provenance_and_human_readiness(chat_setup):
    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    turn_id = uuid.UUID(submit(chat_setup).json()["id"])
    with Session(engine) as db:
        captured = db.get(ChatTurn, turn_id).payload["documents"]
    # A human save wins; generated PROJECT text is retained only as conflict.
    assert (
        client.put(
            f"/api/projects/{project}/documents/project",
            json={"expected_revision": 1, "content": "# New human head"},
            headers=headers,
        ).status_code
        == 200
    )
    broker.add(
        "completed",
        {
            "proposals": [
                {
                    "filename": name,
                    "base_sha256": captured[name]["sha256"],
                    "content": captured[name]["content"] + "\nSynthetic proposal.\n",
                    "origin": "agent",
                    "approval": False,
                }
                for name in ("PROJECT.md", "AGENTS.md")
            ]
        },
    )
    dispatcher.tick()
    assert (
        client.get(f"/api/projects/{project}/documents/project").json()["content"]
        == "# New human head"
    )
    assert client.get(f"/api/projects/{project}/documents/agents").json()["origin"] == "agent"
    with Session(engine) as db:
        proposals = list(
            db.scalars(
                select(AgentDocumentProposal).where(AgentDocumentProposal.turn_id == turn_id)
            )
        )
        assert {row.state for row in proposals} == {"imported", "conflict"}
        assert all(row.base_revision_id and row.observed_revision_id for row in proposals)
    assert client.get(f"/api/projects/{project}/final-approval").json()["approved"] is False
    # Agent may add draft tasks but cannot activate even an existing draft.
    with Session(engine) as db:
        backlog = db.scalar(
            select(ProjectDocument).where(
                ProjectDocument.project_id == uuid.UUID(project), ProjectDocument.kind == "backlog"
            )
        )
        head = db.scalar(
            select(ProjectDocumentRevision).where(
                ProjectDocumentRevision.document_id == backlog.id,
                ProjectDocumentRevision.revision_number == backlog.head_revision_number,
            )
        )
    task_text = head.content + "\n\n## [-] SYN-991 — Define scope\n\n**Depends on:** None\n"
    assert (
        client.put(
            f"/api/projects/{project}/documents/backlog",
            json={"expected_revision": head.revision_number, "content": task_text},
            headers=headers,
        ).status_code
        == 200
    )
    next_turn = uuid.UUID(submit(chat_setup).json()["id"])
    with Session(engine) as db:
        capture = db.get(ChatTurn, next_turn).payload["documents"]["BACKLOG.md"]
    broker.events = []
    broker.add(
        "completed",
        {
            "proposals": [
                {
                    "filename": "BACKLOG.md",
                    "base_sha256": capture["sha256"],
                    "content": task_text.replace("## [-] SYN-991", "## [ ] SYN-991"),
                    "origin": "agent",
                    "approval": False,
                }
            ]
        },
    )
    dispatcher.tick()
    assert client.get(f"/api/projects/{project}/documents/backlog").json()["content"] == task_text
    with Session(engine) as db:
        assert db.get(ChatTurn, next_turn).state == "interrupted"


def test_uncertain_committed_dispatch_is_not_retried(chat_setup):
    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    turn_id = uuid.UUID(submit(chat_setup).json()["id"])
    with Session(engine) as db, db.begin():
        turn = db.get(ChatTurn, turn_id)
        turn.state = "dispatching"
        turn.broker_epoch = uuid.UUID(broker.epoch)
        turn.dispatch_deadline = datetime.now(UTC) + timedelta(seconds=50)
    dispatcher.tick()
    assert all(call["op"] != "start" for call in broker.calls)
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).state == "interrupted"


def test_uncertain_reply_does_not_resubmit(chat_setup):
    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    turn_id = uuid.UUID(submit(chat_setup).json()["id"])
    broker.add(
        "question",
        {
            "id": "que_synthetic",
            "questions": [
                {
                    "header": "Scope",
                    "question": "Choose?",
                    "options": [{"label": "Local", "description": "Synthetic"}],
                    "custom": False,
                }
            ],
        },
    )
    dispatcher.tick()
    interaction = client.get(f"{base}/{conv}").json()["interactions"][0]["id"]
    path = f"{base}/{conv}/turns/{turn_id}/interactions/{interaction}/reply"
    assert (
        client.post(
            path,
            json={"request_id": str(uuid.uuid4()), "answer": {"answers": [["Local"]]}},
            headers=headers,
        ).status_code
        == 202
    )
    # Persisted marker from a crashed pump means unknown reply dispatch, not a
    # license to answer the native question a second time.
    with Session(engine) as db, db.begin():
        row = db.get(ChatInteraction, uuid.UUID(interaction))
        row.reply_dispatched = True
    dispatcher.tick()
    assert all(call["op"] != "reply" for call in broker.calls)
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).state == "interrupted"
        assert db.get(ChatInteraction, uuid.UUID(interaction)).state == "interrupted"


def test_restarted_pump_waits_for_lease_then_sends_queued_question_once(chat_setup):
    client, engine, headers, _, base, conv, broker, dispatcher = chat_setup
    turn_id = uuid.UUID(submit(chat_setup).json()["id"])
    broker.add(
        "question",
        {
            "id": "que_synthetic",
            "questions": [
                {
                    "header": "Scope",
                    "question": "Choose?",
                    "options": [{"label": "Local", "description": "Synthetic"}],
                    "custom": False,
                }
            ],
        },
    )
    dispatcher.tick()
    interaction = client.get(f"{base}/{conv}").json()["interactions"][0]["id"]
    claim = dispatcher.claim(turn_id)  # Crash while holding a committed pump lease.
    assert claim is not None
    assert (
        client.post(
            f"{base}/{conv}/turns/{turn_id}/interactions/{interaction}/reply",
            json={"request_id": str(uuid.uuid4()), "answer": {"answers": [["Local"]]}},
            headers=headers,
        ).status_code
        == 202
    )
    replacement = Dispatcher(engine, broker)
    calls = len(broker.calls)
    replacement.tick()
    assert len(broker.calls) == calls  # Running/202 did not mean recovered or sent.
    with Session(engine) as db, db.begin():
        assert db.get(ChatInteraction, uuid.UUID(interaction)).state == "replying"
        db.get(ChatTurn, turn_id).pump_until = datetime.now(UTC) - timedelta(seconds=1)
    replacement.tick()
    replacement.tick()
    assert sum(call["op"] == "start" for call in broker.calls) == 1
    assert sum(call["op"] == "reply" for call in broker.calls) == 1
    with Session(engine) as db:
        assert db.get(ChatInteraction, uuid.UUID(interaction)).state == "replied"
        assert db.get(ChatTurn, turn_id).state == "running"


def test_fixed_worker_failure_category_survives_durable_delivery(chat_setup):
    client, _, _, _, base, conv, broker, dispatcher = chat_setup
    submit(chat_setup)
    broker.add("failed", {"reason": "native_stream_timeout"})
    dispatcher.tick()
    page = client.get(f"{base}/{conv}/events").json()["events"]
    assert page[-1]["type"] == "failed"
    assert page[-1]["data"] == {"reason": "native_stream_timeout"}


def test_joined_failure_summary_excludes_private_turn_data(chat_setup, capsys):
    import json
    from unittest.mock import Mock

    from imp024_joined import Checks

    _, engine, _, _, _, _, broker, dispatcher = chat_setup
    turn_id = uuid.UUID(submit(chat_setup, prompt="synthetic-private-transcript").json()["id"])
    broker.add("failed", {"reason": "native_stream_timeout"})
    dispatcher.tick()
    checks = Checks.__new__(Checks)
    checks.engine = engine
    checks.last_turn = str(turn_id)
    checks.api = Mock()
    checks.api.count.return_value = 1
    checks.api.calls.return_value = [{"at": 1}, {"at": 21}]
    checks.diagnostic()
    output = capsys.readouterr().out
    summary = json.loads(output)
    assert summary["state"] == "failed"
    assert summary["failure_reasons"] == ["native_stream_timeout"]
    assert summary["largest_poll_gap_seconds"] == 20
    assert "synthetic-private-transcript" not in output and str(turn_id) not in output
    assert set(summary) == {
        "diagnostic",
        "state",
        "lease_remaining_seconds",
        "broker_cursor",
        "interactions",
        "failure_reasons",
        "calls",
        "largest_poll_gap_seconds",
    }


def test_revoked_reply_sender_cannot_dispatch_under_initiator_authority(chat_setup):
    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    turn_id = uuid.UUID(submit(chat_setup).json()["id"])
    broker.add("permission", {"id": "per_synthetic", "permission": "edit", "once_allowed": True})
    dispatcher.tick()
    # Re-login creates a separate sender session, leaving the initiator session valid.
    _login(client, "chat-owner", "synthetic chat passphrase")
    headers = {
        "Origin": "http://127.0.0.1:8080",
        "X-CSRF-Token": client.cookies.get("impostr_csrf", ""),
    }
    interaction = client.get(f"{base}/{conv}").json()["interactions"][0]["id"]
    path = f"{base}/{conv}/turns/{turn_id}/interactions/{interaction}/reply"
    assert (
        client.post(
            path,
            json={"request_id": str(uuid.uuid4()), "answer": {"reply": "once"}},
            headers=headers,
        ).status_code
        == 202
    )
    with Session(engine) as db, db.begin():
        row = db.get(ChatInteraction, uuid.UUID(interaction))
        db.execute(
            update(WebSession)
            .where(WebSession.token_hash == row.reply_session_hash)
            .values(revoked_at=datetime.now(UTC))
        )
    dispatcher.tick()
    assert all(call["op"] != "reply" for call in broker.calls)
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).state == "interrupted"


def test_stream_revocation_stops_an_already_open_replay(chat_setup):
    import asyncio

    from starlette.requests import Request

    from app.chat import stream
    from app.chat_state import initiating_actor

    _, engine, _, project, _, conv, _, _ = chat_setup
    turn_id = uuid.UUID(submit(chat_setup).json()["id"])

    async def disconnected():
        return False

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    request.is_disconnected = disconnected
    with Session(engine) as db:
        actor = initiating_actor(db, db.get(ChatTurn, turn_id))
        response = stream(uuid.UUID(project), uuid.UUID(conv), request, db, actor, after=0)
    with Session(engine) as db, db.begin():
        db.execute(update(WebSession).values(revoked_at=datetime.now(UTC)))

    async def consume():
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(consume())
    assert chunks == ["event: unavailable\ndata: {}\n\n"]


def test_agent_revision_invalidates_approved_pair_and_can_be_approved_only_by_human(chat_setup):
    from test_template_profiles import AGENTS, BACKLOG, PROJECT

    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    for kind, content in zip(
        ("project", "agents", "backlog"), (PROJECT, AGENTS, BACKLOG), strict=True
    ):
        assert (
            client.put(
                f"/api/projects/{project}/documents/{kind}",
                json={"expected_revision": 1, "content": content},
                headers=headers,
            ).status_code
            == 200
        )
    pair = client.post(
        f"/api/projects/{project}/document-pair-approval",
        json={"expected_project_revision": 2, "expected_agents_revision": 2},
        headers=headers,
    )
    assert pair.status_code == 200
    final = client.post(
        f"/api/projects/{project}/final-approval",
        json={
            "expected_pair_approval_id": pair.json()["id"],
            "expected_backlog_revision": 2,
        },
        headers=headers,
    )
    assert final.status_code == 200
    turn_id = uuid.UUID(submit(chat_setup).json()["id"])
    with Session(engine) as db:
        capture = db.get(ChatTurn, turn_id).payload["documents"]["PROJECT.md"]
    broker.add(
        "completed",
        {
            "proposals": [
                {
                    "filename": "PROJECT.md",
                    "base_sha256": capture["sha256"],
                    "content": PROJECT + "\nReviewed synthetic local-only change.\n",
                    "origin": "agent",
                    "approval": False,
                }
            ]
        },
    )
    dispatcher.tick()
    assert client.get(f"/api/projects/{project}/document-pair-approval").json()["approved"] is False
    assert client.get(f"/api/projects/{project}/final-approval").json()["approved"] is False
    assert client.get(f"/api/projects/{project}/final-approval/files/project").status_code == 409
    # Generated origin is reviewable, not an integrity failure or implicit approval.
    reapprove = client.post(
        f"/api/projects/{project}/document-pair-approval",
        json={"expected_project_revision": 3, "expected_agents_revision": 2},
        headers=headers,
    )
    assert reapprove.status_code == 200


def test_maximum_message_continuation_preserves_context_and_rejects_overflow_before_queue(
    chat_setup,
):
    client, engine, headers, project, base, conv, broker, dispatcher = chat_setup
    first_prompt = "x" * MAX_TEXT
    first = submit(chat_setup, prompt=first_prompt)
    assert first.status_code == 202
    broker.add("delta", {"text": "a" * MAX_TEXT})
    broker.add("completed", {"proposals": []})
    dispatcher.tick()
    second = submit(chat_setup, prompt="Continue")
    assert second.status_code == 202
    with Session(engine) as db:
        turn = db.get(ChatTurn, uuid.UUID(second.json()["id"]))
        assert turn.payload["history"][0]["text"] == first_prompt
        assert turn.payload["history"][1]["text"].startswith("a" * MAX_TEXT)
    aborted = client.post(f"{base}/{conv}/turns/{second.json()['id']}/abort", headers=headers)
    assert aborted.status_code == 200
    assert aborted.json()["state"] == "cancelled"
    # Build the overflowing history exclusively through accepted bounded messages
    # and durable assistant events. Each next turn still fits at submission;
    # after three complete 64 KiB pairs, framing/current text exceeds 384 KiB.
    for _ in range(2):
        accepted = submit(chat_setup, prompt=first_prompt)
        assert accepted.status_code == 202
        broker.events = []
        broker.add("delta", {"text": "a" * MAX_TEXT})
        broker.add("completed", {"proposals": []})
        dispatcher.tick()
        with Session(engine) as db:
            assert db.get(ChatTurn, uuid.UUID(accepted.json()["id"])).state == "completed"
    before = client.get(f"{base}/{conv}/events").json()
    rejected = submit(chat_setup, prompt="z" * MAX_TEXT)
    assert rejected.status_code == 422
    assert client.get(f"{base}/{conv}/events").json() == before
    with Session(engine) as db:
        assert (
            len(
                list(
                    db.scalars(select(ChatTurn).where(ChatTurn.conversation_id == uuid.UUID(conv)))
                )
            )
            == 4
        )
        assert db.get(ProjectTurnReservation, uuid.UUID(project)) is None


def test_twelve_complete_prior_turns_accepted_without_omission(chat_setup):
    client, engine, _, _, base, conv, broker, dispatcher = chat_setup
    for index in range(MAX_PRIOR_TURNS + 1):
        response = submit(chat_setup, prompt=f"Synthetic turn {index}")
        assert response.status_code == 202
        with Session(engine) as db:
            turn = db.get(ChatTurn, uuid.UUID(response.json()["id"]))
            assert len(turn.payload["history"]) == index * 2
            assert {item["text"] for item in turn.payload["history"] if item["role"] == "user"} == {
                f"Synthetic turn {prior}" for prior in range(index)
            }
        broker.events = []
        broker.add("delta", {"text": f"Synthetic answer {index}"})
        broker.add("completed", {"proposals": []})
        dispatcher.tick()
    rejected = submit(chat_setup, prompt="No silent omission")
    assert rejected.status_code == 422
    assert len(client.get(f"{base}/{conv}").json()["turns"]) == MAX_PRIOR_TURNS + 1
