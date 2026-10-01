"""Coordinator-only executable joined phase-two checks, AFTER boundary review.

Run in the disposable api-integration-check container, never on the host/live DB.
Real HTTP authentication, PostgreSQL, dispatcher, UnixBroker and confined worker.
The child records operation names/IDs only and offers bounded test gates around
real channel calls; it never fabricates a broker response or exposes a test route.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

from imp024_http import Client, TransportError
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.chat_broker import UnixBroker
from app.chat_dispatch import PUMP_LEASE_SECONDS
from app.chat_protocol import FAILURE_REASONS
from app.chat_state import TERMINAL, utc
from app.database import database_url_from_environment
from app.models import (
    AgentDocumentProposal,
    ChatEvent,
    ChatInteraction,
    ChatTurn,
    DocumentConflictProposal,
    Project,
    ProjectDocumentRevision,
    ProjectTurnReservation,
    User,
    WebSession,
)
from app.passwords import hash_password

ORIGIN = "http://127.0.0.1:8080"


def fixture_only():
    assert os.geteuid() == 10001, "container API identity required"
    assert all(
        os.environ.get(name) == "1"
        for name in (
            "IMPOSTR_TEST_POSTGRES",
            "IMPOSTR_TEST_CHAT_CHANNEL",
            "IMPOSTR_TEST_CHAT_JOINED",
        )
    ), "explicit disposable joined fixture required"


def wait(check, *, seconds=12, label="condition"):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Timed out: " + label)


def serve(directory: Path, port: int):
    """Instrumentation wraps the actual client; application transactions unchanged."""
    import uvicorn

    import app.main as main
    from app.config import AppSettings

    class ObservedBroker(UnixBroker):
        def call(self, value):
            op = value["op"]
            for stage in ("before", "after"):
                if stage == "after":
                    result = super().call(value)
                with (directory / "calls.jsonl").open("a") as output:
                    output.write(
                        json.dumps(
                            {
                                "op": op,
                                "stage": stage,
                                "turn": value.get("turn_id"),
                                "at": time.monotonic(),
                            }
                        )
                        + "\n"
                    )
                gate = directory / (stage + "-" + op)
                if gate.exists():
                    (directory / (stage + "-" + op + "-entered")).touch()
                    wait(lambda gate=gate: not gate.exists(), seconds=12, label="test gate release")
            if op == "poll" and any(
                row["event"]["type"] == "completed" for row in result.get("events", [])
            ):
                gate = directory / "after-completion"
                if gate.exists():
                    (directory / "after-completion-entered").touch()
                    wait(lambda: not gate.exists(), seconds=12, label="completion gate release")
            return result

    main.UnixBroker = ObservedBroker
    application = main.create_app(settings=AppSettings.from_environment())
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="critical", access_log=False)


class ApiProcess:
    def __init__(self, directory: Path):
        self.directory = directory
        self.process = None
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.start()

    def launch(self):
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                __file__,
                "serve",
                "--directory",
                str(self.directory),
                "--port",
                str(self.port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )

    def start(self):
        self.launch()

        def healthy():
            assert self.process.poll() is None, "API child exited"
            client = Client(self.url, timeout=1)
            try:
                return client.get("/api/health").status_code == 200
            except TransportError:
                return False
            finally:
                client.close()

        try:
            wait(healthy, label="real API startup")
        except Exception:
            self.stop()
            raise

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=5)

    def restart(self):
        self.stop()
        self.start()

    def gate(self, stage: str, op: str):
        (self.directory / (stage + "-" + op + "-entered")).unlink(missing_ok=True)
        (self.directory / (stage + "-" + op)).touch()

    def entered(self, stage: str, op: str):
        wait(
            lambda: (self.directory / (stage + "-" + op + "-entered")).exists(),
            label="channel gate",
        )

    def release(self, stage: str, op: str):
        (self.directory / (stage + "-" + op)).unlink(missing_ok=True)

    def calls(self, op: str, turn: str, stage="before"):
        path = self.directory / "calls.jsonl"
        if not path.exists():
            return []
        rows = [
            json.loads(line)
            for line in path.read_text().splitlines(keepends=True)
            if line.endswith("\n")
        ]
        return [
            row for row in rows if row["op"] == op and row["stage"] == stage and row["turn"] == turn
        ]

    def count(self, op: str, turn: str, stage="before"):
        return len(self.calls(op, turn, stage))


class Checks:
    def __init__(self, api: ApiProcess, engine):
        self.api, self.engine = api, engine
        self.user_id = uuid.uuid4()
        self.username = "joined-" + self.user_id.hex[:20]
        self.password = "synthetic disposable joined passphrase"
        self.projects = []
        self.last_turn = None
        self.client = Client(base_url=api.url, timeout=5)
        with Session(engine) as db, db.begin():
            db.add(
                User(
                    id=self.user_id,
                    username=self.username,
                    password_hash=hash_password(self.password),
                    role="user",
                    is_active=True,
                )
            )

    def login(self):
        csrf = self.client.get("/api/auth/csrf").json()["csrf_token"]
        result = self.client.post(
            "/api/auth/login",
            json={"username": self.username, "password": self.password},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert result.status_code == 200, "normal fixture login failed"

    def mutate(self, method, path, payload=None, *, status=200):
        result = self.client.request(method, path, json=payload, headers=self.headers())
        assert result.status_code == status, (
            f"{method} fixture request: {result.status_code}, expected {status}"
        )
        return result.json()

    def headers(self):
        return {
            "Origin": ORIGIN,
            "X-CSRF-Token": self.client.cookies.get("impostr_csrf", ""),
        }

    def project(self):
        from test_template_profiles import AGENTS, BACKLOG, PROJECT

        project = self.mutate(
            "POST",
            "/api/projects",
            {"name": "Synthetic joined " + uuid.uuid4().hex[:12]},
            status=201,
        )["id"]
        self.projects.append(uuid.UUID(project))
        root = f"/api/projects/{project}"
        for kind, text in zip(
            ("project", "agents", "backlog"), (PROJECT, AGENTS, BACKLOG), strict=True
        ):
            self.mutate(
                "PUT", root + "/documents/" + kind, {"expected_revision": 1, "content": text}
            )
        pair = self.mutate(
            "POST",
            root + "/document-pair-approval",
            {"expected_project_revision": 2, "expected_agents_revision": 2},
        )
        self.mutate(
            "POST",
            root + "/final-approval",
            {"expected_pair_approval_id": pair["id"], "expected_backlog_revision": 2},
        )
        assert self.client.get(root + "/final-approval").json()["approved"] is True
        conv = self.mutate("POST", root + "/chat", {"title": "Joined synthetic"}, status=201)["id"]
        return project, root, root + "/chat/" + conv, PROJECT

    def submit(self, base):
        payload = {"request_id": str(uuid.uuid4()), "prompt": "Prepare only the synthetic proposal"}
        first = self.mutate("POST", base + "/turns", payload, status=202)
        self.last_turn = first["id"]
        duplicate = self.mutate("POST", base + "/turns", payload, status=202)
        assert duplicate["id"] == first["id"]
        return first["id"], payload

    def state(self, turn):
        with Session(self.engine) as db:
            return db.get(ChatTurn, uuid.UUID(turn)).state

    def pending(self, base, kind):
        def find():
            result = self.client.get(base)
            assert result.status_code == 200, "history inaccessible"
            assert all(
                row["state"] not in TERMINAL
                for row in result.json()["turns"]
                if row["id"] == self.last_turn
            ), "turn ended before native interaction"
            return next(
                (
                    row
                    for row in result.json()["interactions"]
                    if row["turn_id"] == self.last_turn
                    and row["kind"] == kind
                    and row["state"] == "pending"
                ),
                None,
            )

        return wait(find, seconds=25, label="native pending " + kind)

    def diagnostic(self):
        """Fixed categories/counts only, BEFORE cleanup erases failed-turn evidence.

        No cookies, actor/native IDs, document/chat text, channel bodies, DB settings
        or exception details. Diagnostic failure must not replace the original error.
        """
        result = {"diagnostic": "unavailable"}
        try:
            with Session(self.engine) as db:
                turn = db.get(ChatTurn, uuid.UUID(self.last_turn)) if self.last_turn else None
                if turn is not None:
                    interactions = list(
                        db.scalars(
                            select(ChatInteraction).where(ChatInteraction.turn_id == turn.id)
                        )
                    )
                    failures = list(
                        db.scalars(
                            select(ChatEvent).where(
                                ChatEvent.turn_id == turn.id, ChatEvent.kind == "failed"
                            )
                        )
                    )
                    states = {"pending", "replying", "replied", "interrupted"}
                    remaining = (
                        (utc(turn.pump_until) - datetime.now(UTC)).total_seconds()
                        if turn.pump_until
                        else 0
                    )
                    result = {
                        "diagnostic": "joined_turn",
                        "state": (
                            turn.state
                            if turn.state
                            in TERMINAL | {"queued", "dispatching", "running", "cancelling"}
                            else "unknown"
                        ),
                        "lease_remaining_seconds": round(
                            max(0, min(PUMP_LEASE_SECONDS, remaining)), 2
                        ),
                        "broker_cursor": turn.broker_cursor,
                        "interactions": [
                            {
                                "kind": (
                                    row.kind
                                    if row.kind in ("question", "permission")
                                    else "unknown"
                                ),
                                "state": row.state if row.state in states else "unknown",
                                "dispatched": bool(row.reply_dispatched),
                            }
                            for row in interactions
                        ],
                        "failure_reasons": [
                            (
                                row.data.get("reason")
                                if row.data.get("reason") in FAILURE_REASONS
                                else "unspecified"
                            )
                            for row in failures
                        ],
                        "calls": {
                            op: {
                                stage: self.api.count(op, self.last_turn, stage)
                                for stage in ("before", "after")
                            }
                            for op in ("start", "reply", "poll", "abort")
                        },
                    }
                    polls = self.api.calls("poll", self.last_turn, "after")
                    if len(polls) > 1:
                        result["largest_poll_gap_seconds"] = round(
                            max(
                                right["at"] - left["at"]
                                for left, right in zip(polls[:-1], polls[1:], strict=True)
                            ),
                            2,
                        )
        except Exception:
            pass
        print(json.dumps(result), flush=True)

    def reply(self, base, interaction, *, status=202):
        payload = {
            "request_id": str(uuid.uuid4()),
            "answer": (
                {"answers": [["Yes"]]} if interaction["kind"] == "question" else {"reply": "once"}
            ),
        }
        path = base + f"/turns/{interaction['turn_id']}/interactions/{interaction['id']}/reply"
        self.mutate("POST", path, payload, status=status)
        if status == 202:
            self.mutate("POST", path, payload, status=202)
        return path, payload

    def terminal(self, turn, expected):
        wait(lambda: self.state(turn) in TERMINAL, seconds=30, label="durable terminal")
        assert self.state(turn) == expected, "unexpected durable turn outcome"
        with Session(self.engine) as db:
            row = db.get(ChatTurn, uuid.UUID(turn))
            wait_project = row.project_id
            events = list(
                db.scalars(
                    select(ChatEvent)
                    .where(ChatEvent.turn_id == row.id)
                    .order_by(ChatEvent.sequence)
                )
            )
            assert [event.sequence for event in events] == list(range(1, len(events) + 1))
            assert sum(event.kind == expected for event in events) == 1
        wait(
            lambda: self.reservation_gone(wait_project),
            seconds=70,
            label="bounded reservation release",
        )

    def reservation_gone(self, project):
        with Session(self.engine) as db:
            return db.get(ProjectTurnReservation, project) is None

    def invalidated(self, root):
        assert self.client.get(root + "/document-pair-approval").json()["approved"] is False
        assert self.client.get(root + "/final-approval").json()["approved"] is False
        assert self.client.get(root + "/final-approval/files/project").status_code == 409

    def proposal(self, db, turn):
        return db.scalar(
            select(AgentDocumentProposal).where(AgentDocumentProposal.turn_id == uuid.UUID(turn))
        )

    def revoke(self, turn):
        with Session(self.engine) as db, db.begin():
            row = db.get(ChatTurn, uuid.UUID(turn))
            db.execute(
                update(WebSession)
                .where(WebSession.token_hash == row.web_session_hash)
                .values(revoked_at=datetime.now(UTC))
            )

    def no_import(self, turn):
        with Session(self.engine) as db:
            assert self.proposal(db, turn) is None
            assert (
                db.scalar(
                    select(ChatEvent.id).where(
                        ChatEvent.turn_id == uuid.UUID(turn), ChatEvent.kind == "completed"
                    )
                )
                is None
            )

    def normal_restart_and_concurrency(self):
        project, root, base, captured = self.project()
        turn, payload = self.submit(base)
        question = self.pending(base, "question")
        self.api.gate("before", "hello")
        self.api.entered("before", "hello")
        before = self.client.get(base + "/events").json()["events"]
        assert {"queued", "started", "question"} <= {row["type"] for row in before}
        with Session(self.engine) as db:
            native = db.get(ChatTurn, uuid.UUID(turn)).native_session_id
            lease = db.get(ChatTurn, uuid.UUID(turn)).pump_until
            assert lease is not None, "restart must preserve an outstanding pump lease"
        polls = self.api.count("poll", turn, "after")
        # Real SIGKILL/relaunch, same PostgreSQL and broker/worker epoch.
        self.api.stop()
        self.api.release("before", "hello")
        self.api.start()
        # A retained running row and healthy API are NOT evidence that the new
        # dispatcher reclaimed the crashed pump. Require a real post-restart poll
        # ACK, allowing the existing bounded lease to expire without stealing it.
        wait(
            lambda: self.api.count("poll", turn, "after") > polls,
            seconds=PUMP_LEASE_SECONDS + 5,
            label="post-restart native poll ACK",
        )
        assert self.state(turn) == "running", "same-epoch recovery did not retain running turn"
        assert self.client.get(base + "/events").json()["events"] == before
        assert (
            self.client.get(root + "/chat").json()["last_conversation_id"] == base.rsplit("/", 1)[1]
        )
        assert self.mutate("POST", base + "/turns", payload, status=202)["id"] == turn
        self.reply(base, question)
        permission = self.pending(base, "permission")
        with Session(self.engine) as db:
            assert db.get(ChatInteraction, uuid.UUID(question["id"])).state == "replied"
        assert self.api.count("reply", turn, "after") == 1, "question reply ACK not observed"
        # A human HTTP save must finish while real inference awaits permission.
        human = captured + "\nHuman text while inference is pending.\n"
        started = time.monotonic()
        self.mutate("PUT", root + "/documents/project", {"expected_revision": 2, "content": human})
        assert time.monotonic() - started < 5
        assert self.state(turn) == "running"
        self.reply(base, permission)
        self.terminal(turn, "completed")
        assert self.api.count("start", turn) == 1 and self.api.count("reply", turn) == 2
        page = self.client.get(base + "/events").json()
        assert {"delta", "proposals", "completed"} <= {row["type"] for row in page["events"]}
        with Session(self.engine) as db:
            ids = list(
                db.scalars(
                    select(ChatEvent.id)
                    .where(ChatEvent.conversation_id == uuid.UUID(base.rsplit("/", 1)[1]))
                    .order_by(ChatEvent.id)
                )
            )
            assert [row["id"] for row in page["events"]] == ids
        assert self.client.get(base + f"/events?after={page['after']}").json()["events"] == []
        with Session(self.engine) as db:
            assert db.get(ChatTurn, uuid.UUID(turn)).native_session_id == native
            proposal = self.proposal(db, turn)
            assert proposal.state == "conflict" and proposal.imported_revision_id is None
            assert proposal.base_revision_id != proposal.observed_revision_id
            assert db.get(ProjectDocumentRevision, proposal.observed_revision_id).content == human
            assert (
                db.get(DocumentConflictProposal, proposal.conflict_proposal_id).content
                == captured + "\nSynthetic planning proposal.\n"
            )
        self.invalidated(root)
        # Continuation reconstructs actual durable history in a new native session.
        second, _ = self.submit(base)
        question = self.pending(base, "question")
        with Session(self.engine) as db:
            restored = db.get(ChatTurn, uuid.UUID(second))
            assert restored.native_session_id != native
            assert restored.payload["history"][0]["text"].startswith(payload["prompt"])
            assert "Recorded planning interactions" in restored.payload["history"][0]["text"]
        events = self.client.get(base + "/events").json()["events"]
        started_event = next(
            row for row in events if row["turn_id"] == second and row["type"] == "started"
        )
        assert started_event["data"]["context_reconstructed"] is True
        self.mutate("POST", base + f"/turns/{second}/abort")
        self.terminal(second, "cancelled")
        print(
            "PASS joined native flow, API process restart, concurrent inference/save conflict",
            flush=True,
        )

        # Race HTTP human save and the actual completion/import transaction on PG.
        _, root, base, captured = self.project()
        turn, _ = self.submit(base)
        self.reply(base, self.pending(base, "question"))
        permission = self.pending(base, "permission")
        self.api.gate("after", "completion")
        self.reply(base, permission)
        self.api.entered("after", "completion")
        assert self.state(turn) == "running"
        # Release a known completed real response and an HTTP save together. Both
        # transactions contend on the real PG user/document locks, not a double.
        barrier = Barrier(2)
        human = captured + "\nHuman racing import.\n"

        def save():
            barrier.wait(timeout=5)
            return self.client.put(
                root + "/documents/project",
                json={"expected_revision": 2, "content": human},
                headers=self.headers(),
            )

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending_save = pool.submit(save)
            barrier.wait(timeout=5)
            self.api.release("after", "completion")
            response = pending_save.result(timeout=10)
        assert response.status_code in (200, 409)
        self.terminal(turn, "completed")
        with Session(self.engine) as db:
            proposal = self.proposal(db, turn)
            if response.status_code == 200:
                assert proposal.state == "conflict"
                assert proposal.base_revision_id != proposal.observed_revision_id
                assert (
                    db.get(ProjectDocumentRevision, proposal.observed_revision_id).content == human
                )
            else:
                assert proposal.state == "imported"
                assert proposal.base_revision_id == proposal.observed_revision_id
                assert (
                    db.get(ProjectDocumentRevision, proposal.imported_revision_id).origin == "agent"
                )
                assert (
                    db.scalar(
                        select(DocumentConflictProposal).where(
                            DocumentConflictProposal.document_id == proposal.document_id,
                            DocumentConflictProposal.content == human,
                        )
                    )
                    is not None
                )
            assert proposal.content == captured + "\nSynthetic planning proposal.\n"
        self.invalidated(root)
        print("PASS PostgreSQL human-save/import race and provenance", flush=True)

        # Matching-head import must also pass irrespective of the race winner.
        _, root, base, captured = self.project()
        turn, _ = self.submit(base)
        self.reply(base, self.pending(base, "question"))
        self.reply(base, self.pending(base, "permission"))
        self.terminal(turn, "completed")
        with Session(self.engine) as db:
            proposal = self.proposal(db, turn)
            assert proposal.state == "imported"
            assert proposal.base_revision_id == proposal.observed_revision_id
            revision = db.get(ProjectDocumentRevision, proposal.imported_revision_id)
            assert revision.origin == "agent"
            assert revision.content == captured + "\nSynthetic planning proposal.\n"
        self.invalidated(root)
        print("PASS real matching-head agent import invalidates existing approvals", flush=True)

    def uncertain_reply_and_revocation(self):
        _, _, base, _ = self.project()
        self.api.gate("after", "start")
        turn, _ = self.submit(base)
        self.api.entered("after", "start")
        assert self.state(turn) == "dispatching", "dispatch marker must precede channel I/O"
        self.api.stop()
        self.api.release("after", "start")
        self.api.start()
        self.terminal(turn, "interrupted")
        assert self.api.count("start", turn) == 1 and self.api.count("reply", turn) == 0
        print("PASS actual API crash after start ACK: uncertain dispatch not repeated", flush=True)

        _, _, base, _ = self.project()
        turn, _ = self.submit(base)
        question = self.pending(base, "question")
        self.api.gate("after", "reply")
        self.reply(base, question)
        self.api.entered("after", "reply")
        self.api.stop()  # ACK happened, DB replying -> replied commit did not.
        self.api.release("after", "reply")
        self.api.start()
        self.terminal(turn, "interrupted")
        assert self.api.count("reply", turn) == 1 and self.api.count("start", turn) == 1
        print("PASS actual API crash after reply ACK: no duplicate reply", flush=True)

        _, _, base, _ = self.project()
        turn, _ = self.submit(base)
        question = self.pending(base, "question")
        # Hold the next tick before its authorization transaction, not a reply
        # already committed as dispatched. HTTP can still queue a real reply.
        self.api.gate("before", "hello")
        self.api.entered("before", "hello")
        self.reply(base, question)
        after = self.client.get(base + "/events").json()["after"]
        with self.client.stream("GET", base + f"/stream?after={after}") as stream:
            assert stream.status_code == 200
            lines = stream.iter_lines()
            assert next(lines) == ": heartbeat", "actual open incremental HTTP stream required"
            self.revoke(turn)
            self.api.release("before", "hello")
            remaining = list(lines)
            assert "event: unavailable" in remaining
            assert "event: chat" not in remaining, "no chat delivery after committed revocation"
        self.reply(base, question, status=401)
        self.terminal(turn, "interrupted")
        assert self.api.count("reply", turn) == 0
        self.no_import(turn)
        self.login()
        print(
            "PASS joined active HTTP stream/session revocation, stale/queued reply denial",
            flush=True,
        )

        # Completion bytes are real and held after channel ACK, before delivery/
        # import authorization. Revocation must prevent import, not merely hide it.
        _, _, base, _ = self.project()
        turn, _ = self.submit(base)
        self.reply(base, self.pending(base, "question"))
        permission = self.pending(base, "permission")
        self.api.gate("after", "completion")
        self.reply(base, permission)
        self.api.entered("after", "completion")
        self.revoke(turn)
        self.api.release("after", "completion")
        self.terminal(turn, "interrupted")
        self.no_import(turn)
        self.login()
        print("PASS joined revocation after native completion prevents durable import", flush=True)

    def lifecycle(self):
        # Coordinator controls only its own broker/DB, from another terminal.
        _, _, base, _ = self.project()
        turn, _ = self.submit(base)
        self.pending(base, "question")
        old_epoch = UnixBroker().call({"op": "hello"})["epoch"]
        before = self.client.get(base + "/events").json()["events"]
        self.api.stop()
        input(
            "ACTION: SIGTERM owned broker; wait for exit/worker cleanup; "
            "restart with --persistent-directory; then press Enter: "
        )
        assert UnixBroker().call({"op": "hello"})["epoch"] != old_epoch
        self.api.start()
        self.terminal(turn, "interrupted")
        assert self.api.count("start", turn) == 1 and self.api.count("reply", turn) == 0
        after = self.client.get(base + "/events").json()["events"]
        assert after[: len(before)] == before
        assert self.client.get(base).json()["interactions"][0]["state"] == "interrupted"
        print("PASS full API/broker/worker restart: unknown interrupted, no redispatch", flush=True)

        _, _, base, _ = self.project()
        turn, _ = self.submit(base)
        self.pending(base, "question")
        input("ACTION: SIGTERM owned broker and leave stopped; then press Enter: ")
        try:
            UnixBroker().call({"op": "hello"})
        except ValueError:
            pass
        else:
            raise AssertionError("broker outage action was not performed")
        wait(lambda: self.state(turn) == "interrupted", label="channel outage interruption")
        self.no_import(turn)
        input("ACTION: restart owned broker with --persistent-directory; then press Enter: ")
        self.terminal(turn, "interrupted")
        assert self.api.count("start", turn) == 1
        print("PASS channel outage/restoration without false import or duplicate start", flush=True)

        _, _, base, _ = self.project()
        turn, _ = self.submit(base)
        self.pending(base, "question")
        polls = self.api.count("poll", turn)
        before = self.client.get(base + "/events").json()["events"]
        self.api.stop()
        input("ACTION: stop owned Compose db; then press Enter: ")
        self.api.launch()  # Real startup during outage; require 503, not fake health.

        def unavailable():
            assert self.api.process.poll() is None
            try:
                return self.client.get("/api/health").status_code == 503
            except TransportError:
                return False

        wait(unavailable, label="real DB outage HTTP503")
        assert self.client.get(base).status_code == 503
        input("ACTION: start owned Compose db; wait for healthy; then press Enter: ")
        wait(
            lambda: self.client.get("/api/health").status_code == 200,
            seconds=20,
            label="DB restored",
        )
        # The worker may have expired during human orchestration; either retained
        # running or explicit failure/interruption is safe, never completion.
        wait(
            lambda: self.api.count("poll", turn) > polls or self.state(turn) in TERMINAL,
            seconds=25,
            label="post-outage pump recovery",
        )
        assert self.state(turn) in ("running", "failed", "interrupted")
        assert self.api.count("start", turn) == 1
        if self.state(turn) == "running":
            self.mutate("POST", base + f"/turns/{turn}/abort")
            self.terminal(turn, "cancelled")
        else:
            self.terminal(turn, self.state(turn))
        self.no_import(turn)
        after = self.client.get(base + "/events").json()["events"]
        assert after[: len(before)] == before
        print(
            "PASS actual DB outage/recovery: unavailable, no false completion/import or redispatch",
            flush=True,
        )

    def close(self):
        self.api.stop()
        self.client.close()
        # Assertion/interrupt paths must also stop actual workers before deleting
        # the durable records needed to scope them. No Docker or unrelated PIDs.
        broker = UnixBroker()
        epoch = broker.call({"op": "hello"})["epoch"]
        with Session(self.engine) as db:
            turns = list(db.scalars(select(ChatTurn).where(ChatTurn.project_id.in_(self.projects))))
            for turn in turns:
                if str(turn.broker_epoch) == epoch or turn.broker_epoch is None:
                    result = broker.call(
                        {
                            "op": "abort",
                            "epoch": epoch,
                            "project_id": str(turn.project_id),
                            "conversation_id": str(turn.conversation_id),
                            "turn_id": str(turn.id),
                        }
                    )
                    assert result["stopped"] is True, "owned worker stop not confirmed"
        with Session(self.engine) as db, db.begin():
            for project in self.projects:
                db.execute(delete(Project).where(Project.id == project))
            db.execute(delete(User).where(User.id == self.user_id))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "lifecycle", "serve"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    fixture_only()
    if args.mode == "serve":
        assert args.directory is not None and args.port is not None
        serve(args.directory, args.port)
        return
    engine = create_engine(
        database_url_from_environment(),
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
        poolclass=NullPool,
    )
    with Session(engine) as db:
        assert db.scalar(select(User.id)) is None, "requires empty disposable migrated DB"
    broker = UnixBroker()
    assert broker.call({"op": "hello"})["mode"] == "synthetic"
    with TemporaryDirectory(prefix="imp024-joined-") as directory:
        api = ApiProcess(Path(directory))
        checks = None
        try:
            checks = Checks(api, engine)
            checks.login()
            if args.mode == "check":
                checks.normal_restart_and_concurrency()
                checks.uncertain_reply_and_revocation()
            else:
                checks.lifecycle()
        except Exception:
            if checks is not None:
                checks.diagnostic()
            raise
        finally:
            try:
                if checks is not None:
                    checks.close()
            finally:
                api.stop()
                engine.dispose()
    print(
        "PASS owned API child/account/project/test-state cleanup; "
        "broker/stack cleanup still coordinator-owned",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print DB driver exceptions, connection settings, cookies or raw
        # HTTP/channel data. Assertion labels above are fixed/synthetic-only.
        detail = str(error) if isinstance(error, AssertionError) else "fixture operation failed"
        print("FAIL " + detail, flush=True)
        raise SystemExit(1) from None
