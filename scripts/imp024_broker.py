"""Host UID1000 product broker. REVIEW before new channel/worker execution.

Fixed framed Unix operations, API UID10001 peers only. No HTTP/OpenCode proxy,
Docker, DB, host config/auth or arbitrary inference upstream. Public CLI synthetic
only; reviewed ordinary human launcher explicitly injects planning transport.
Each turn owns the delivered bwrap boundary + inference relay; restart changes
epoch. Runtime state is not trusted after a full restart: API interrupts unknowns.
"""

import argparse
import os
from pathlib import Path
import selectors
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from app.chat_protocol import (MAX_CONTEXT, MAX_EVENTS, MAX_FRAME, TURN_SECONDS, encode, event,
                               receive_request, request, require, scope, NATIVE_INLINE_CONTEXT,
                               PDF_TRANSFER_SECONDS, STOP_SECONDS, encode_native_context)
from imp002_prototype import check_runtime, command
from imp002_relay import SyntheticRelay
from imp024_inference import native_response
from imp018_receipts import ReceiptLedger

WORKER_CODE_FILES = (
    "imp002_worker.py", "imp002_relay.py", "imp023_worker.py", "imp024_protocol.py",
    "imp024_inference.py", "imp024_worker.py", "imp024_product_worker.py",
)

# Exact synthetic-only prompts, not a new channel operation or live model mode.
# Keep the original UI/phase-two fixture unchanged for every other prompt.
SPECIFY_PROMPT = "Synthetic acceptance: specify Fieldnotes"
BACKLOG_PROMPT = "Synthetic acceptance: plan Fieldnotes backlog"
REVISE_PROMPT = "Synthetic acceptance: revise Fieldnotes specification"
EXTEND_PROMPT = "Synthetic acceptance: extend Fieldnotes backlog"
READINESS_PROMPT = "Synthetic acceptance: activate Fieldnotes task"
SYNTHETIC_PROJECT = """# Fieldnotes

## Purpose and scope
Fieldnotes lets a local owner save and search private observations.
- In scope: Save and search dated observations.
- Later/out of scope: Public publishing and shared accounts.

## Important behavior
| Workflow | Expected result | Important rules/failures |
|---|---|---|
| Save observation | Text remains searchable after reopening | Reject empty text |
- Domain terms and examples: Observation means one dated note, such as a bird sighting.
- Important data/access rules: Only the local owner reads observations.

## Stack and architecture
- Runtime/framework/package manager: Python 3.12 with locked pip dependencies.
- Storage/services: Local SQLite database; no external services.
- Structure/data flow: CLI validates input before passing it to storage.py.
- Existing implementation vs planned changes: New command-line application.

## Contracts and constraints
- Important API/schema/file-format contracts: UTF-8 observation text.
- Cross-service dependencies/compatibility: None.
- UI direction/components/devices: None; this is a CLI.
- Security/data/operating limits: Synthetic local observations only.
- Migration/performance/deployment requirements: Version schema changes before migration.

## Decisions still needed
None.

## Completion
Saving and searching notes meets the task acceptance criteria.
"""
SYNTHETIC_AGENTS = """# Agent guide: Fieldnotes

## Project context
- Product/architecture: PROJECT.md. Active tasks: BACKLOG.md.
- Important contract/design references: None.
- Coding conventions and protected/generated paths: PEP 8; preserve generated schema files.
- Dependency/migration rules: Pin dependencies and version storage changes.
- Environment limits: Synthetic local observations only; no external network.

## Commands
| Purpose | Directory | Command | When to use |
|---|---|---|---|
| Setup | . | python -m venv .venv | Before development |
| Run app | . | python -m fieldnotes | After implementation |
| Focused tests | . | python -m pytest tests/test_notes.py | Changed note behavior |
| Type/compile/lint | . | None | No separate checker selected |
- UI URL/login/representative viewport: None.
- Essential task-level gates: Save/search regressions; these planned commands are not yet run.
- CI/release-only checks: None.

## Testing and review
Check changed behavior and realistic save/search failures.

## Execution and Git
The human chooses ready work; agents cannot activate tasks or approve files.
- Git workflow: Existing local branch; coordinator owns commits, no push or merge.

## Completion and communication
Report changed paths and actual focused checks in one brief response.
"""
SYNTHETIC_BACKLOG = """# Backlog: Fieldnotes

## [-] TASK-001 — Save one observation
Depends on: None

Persist validated UTF-8 text in storage.py; exclude public publishing.
Acceptance:
- Saved observations remain searchable after reopening.
- Empty text is rejected.
Verification: After implementation, run python -m pytest tests/test_notes.py.

## [-] TASK-002 — Review saved observations
Depends on: TASK-001

List stored observations for the local owner; exclude shared accounts.
Acceptance:
- The owner can inspect saved notes.
Verification: Inspect one synthetic observation after reopening.
"""
SYNTHETIC_TASK = """
## [-] TASK-003 — Search observations by date
Depends on: TASK-001

Filter locally stored observations by date; exclude network search.
Acceptance:
- Date filtering returns only matching saved observations.
Verification: After implementation, test matching and nonmatching synthetic dates.
"""


def synthetic_plan(payload):
    """Fixture tool DATA only; native OpenCode still reads/asks/edits in confinement."""
    prompt = payload["prompt"]
    if prompt == SPECIFY_PROMPT:
        changes = {"PROJECT.md": SYNTHETIC_PROJECT, "AGENTS.md": SYNTHETIC_AGENTS}
    elif prompt == BACKLOG_PROMPT:
        changes = {"BACKLOG.md": SYNTHETIC_BACKLOG}
    elif prompt == REVISE_PROMPT:
        changes = {"PROJECT.md": payload["documents"]["PROJECT.md"]["content"]
                   + "\nThe local owner reviews note text before saving.\n"}
    elif prompt == EXTEND_PROMPT:
        changes = {"BACKLOG.md": payload["documents"]["BACKLOG.md"]["content"] + SYNTHETIC_TASK}
    elif prompt == READINESS_PROMPT:
        # Deliberate negative import scenario: a once-only file permission must
        # NOT grant human task-readiness authority to the agent.
        changes = {"BACKLOG.md": payload["documents"]["BACKLOG.md"]["content"].replace(
            "## [-] TASK-002", "## [ ] TASK-002", 1)}
    else:
        return None
    calls = [("read", {"filePath": "/project/" + name}) for name in changes]
    calls.append(("question", {"questions": [{"question": "Prepare the synthetic proposal?",
        "header": "Planning", "options": [{"label": "Yes", "description": "Synthetic only"}]}]}))
    calls.extend(("edit", {"filePath": "/project/" + name,
        "oldString": payload["documents"][name]["content"], "newString": content})
        for name, content in changes.items())
    return calls


def copy_worker_code(destination):
    for filename in WORKER_CODE_FILES:
        (destination / filename).write_bytes(Path(__file__).with_name(filename).read_bytes())
    (destination / "imp024_channel.py").write_bytes(
        Path(__file__).resolve().parents[1].joinpath("api/app/chat_protocol.py").read_bytes())


class SyntheticProduct:
    """Deterministic fixture inference data; tools execute only in OpenCode."""
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.plan = synthetic_plan(payload)

    def events(self, data, cancelled, deadline, *, submission=None):
        self.calls += 1
        require(self.calls <= 8)
        if submission is not None:
            require(not cancelled.is_set() and time.monotonic() < deadline)
            require(not submission.ledger.native)  # Native sent proof requires a receiving transport, not this ACK.
            # This is the synthetic inference boundary consuming the full native
            # request, not a worker's started event or prompt acknowledgement.
            submission.consumed(data, cancelled=cancelled, deadline=deadline)
        results = [item for item in data["input"] if item.get("type") == "function_call_output"]
        stage = len(results)
        if self.plan is not None:
            require(stage <= len(self.plan))
            if stage == len(self.plan):
                yield from native_response("Synthetic planning proposal prepared.")
                return
            name, args = self.plan[stage]
            import json
            yield from native_response(calls=[{"type": "function_call", "name": name,
                "call_id": "call_product_" + str(stage), "arguments": json.dumps(args)}])
            return
        require(stage <= 3)
        if stage == 3:
            yield from native_response("Synthetic planning proposal prepared.")
            return
        if stage == 0:
            name, args = "read", {"filePath": "/project/PROJECT.md"}
        elif stage == 1:
            name, args = "question", {"questions": [{"question": "Prepare the synthetic proposal?",
                "header": "Planning", "options": [{"label": "Yes", "description": "Synthetic only"}]}]}
        else:
            name, args = "edit", {"filePath": "/project/PROJECT.md",
                "oldString": self.payload["documents"]["PROJECT.md"]["content"],
                "newString": self.payload["documents"]["PROJECT.md"]["content"]
                             + "\nSynthetic planning proposal.\n"}
        import json
        yield from native_response(calls=[{"type": "function_call", "name": name,
            "call_id": "call_product_" + str(stage), "arguments": json.dumps(args)}])


def worker_command(root):
    args = command(root, "imp024-planning", 0)
    bootstrap = "import sys; sys.path.insert(0, '/prototype'); import imp024_product_worker; raise SystemExit(imp024_product_worker.main())"
    args[args.index("-c") + 1] = bootstrap
    return args


def send_pipe(process, value, *, native=False, cancelled=None, turn_deadline=None):
    value = encode_native_context(value) if native else encode(value)
    fd = process.stdin.fileno()
    os.set_blocking(fd, False)
    deadline = time.monotonic() + (PDF_TRANSFER_SECONDS if native else 3)
    if turn_deadline is not None:
        deadline = min(deadline, turn_deadline)
    view = memoryview(value)
    while view:
        require(time.monotonic() < deadline and process.poll() is None
                and (cancelled is None or not cancelled.is_set()))
        if select.select([], [fd], [], 0.05)[1]:
            count = os.write(fd, view)
            require(count > 0)
            view = view[count:]


class Turn:
    def __init__(self, key, payload, *, epoch, transport_factory=SyntheticProduct, scratch_parent="/tmp/opencode",
                 deadline=None):
        self.key, self.payload = key, payload
        self.receipts = ReceiptLedger(key, epoch, payload)
        self.purged = False
        self.transport_factory = transport_factory
        self.scratch_parent = scratch_parent
        self.events = []
        self.bytes = 0
        self.controls = []
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.abort_requested = threading.Event()
        self.teardown_lock = threading.Lock()
        self.process = self.relay = self.scratch = None
        self.deadline = time.monotonic() + TURN_SECONDS if deadline is None else deadline
        self.thread = threading.Thread(target=self.run, daemon=True)

    def add(self, value):
        value = event(value)
        with self.lock:
            self.bytes += len(encode(value))
            require(self.bytes <= MAX_FRAME and len(self.events) < MAX_EVENTS - 2)
            self.events.append({"sequence": len(self.events) + 1, "event": value})

    def run(self):
        terminal = False
        try:
            if self.abort_requested.is_set():
                return
            self.scratch = tempfile.TemporaryDirectory(prefix="imp024-turn-", dir=self.scratch_parent)
            root = Path(self.scratch.name)
            root.chmod(0o700)
            for directory in ("project", "code", "empty", "config"):
                (root / directory).mkdir(mode=0o700)
            (root / "config" / "opencode").mkdir(mode=0o700)
            (root / "config" / "opencode" / ".gitignore").write_text("node_modules\n")
            copy_worker_code(root / "code")
            native = self.payload.get("kind") == NATIVE_INLINE_CONTEXT
            metadata = self.payload["context"] if native else self.payload
            for filename, document in metadata["documents"].items():
                (root / "project" / filename).write_bytes(document["content"].encode("utf-8"))
                (root / "project" / filename).chmod(0o600)
            # Transport factories receive metadata ONLY, never another inline copy.
            self.relay = SyntheticRelay(root / "relay.sock", lifetime=60,
                                        transport=self.transport_factory(metadata), planning=True,
                                        input_text_limit=MAX_CONTEXT, receipts=self.receipts)
            self.relay.deadline = min(self.relay.deadline, self.deadline)
            self.relay.__enter__()
            self.process = subprocess.Popen(worker_command(root), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin"}, close_fds=True, start_new_session=True)
            send_pipe(self.process, self.payload, native=native, cancelled=self.abort_requested,
                      turn_deadline=self.deadline)
            self.release_payload()  # Worker owns input; host retains only manifests/receipts.
            selector = selectors.DefaultSelector()
            selector.register(self.process.stdout, selectors.EVENT_READ)
            buffer = bytearray()
            try:
                while time.monotonic() < self.deadline:
                    if self.abort_requested.is_set():
                        break
                    with self.lock:
                        controls, self.controls = self.controls, []
                    for control in controls:
                        send_pipe(self.process, control)
                    for _, _ in selector.select(0.05):
                        block = os.read(self.process.stdout.fileno(), 8192)
                        if not block:
                            require(not buffer)
                            return
                        buffer.extend(block)
                        require(len(buffer) <= MAX_FRAME + 4)
                        while len(buffer) >= 4:
                            size = struct.unpack("!I", buffer[:4])[0]
                            require(0 < size <= MAX_FRAME)
                            if len(buffer) < size + 4:
                                break
                            from app.chat_protocol import decode
                            value = decode(bytes(buffer[4:size + 4]))
                            del buffer[:size + 4]
                            self.add(value)
                            terminal = value["type"] in ("completed", "failed", "cancelled")
                            if terminal:
                                return
            finally:
                selector.close()
        except Exception:
            pass
        finally:
            if not terminal:
                try:
                    cancelled = self.abort_requested.is_set()
                    self.add({"type": "cancelled" if cancelled else "failed",
                              "data": {} if cancelled else {"reason": "broker_worker_error"}})
                except Exception:
                    pass
            metadata = document = None
            self.confirm_stop()

    def confirm_stop(self):
        """Retry cleanup ONLY, never prompt/reply/send. Failure retains a visible fence.

        Called by run's finalizer, or after that thread exits on a later abort.
        Reaping bwrap kills the PID namespace (including native server descendants);
        joining relay releases held request generators; scratch cleanup removes surfaces.
        """
        with self.teardown_lock:
            if self.stopped.is_set():
                return True
            self.receipts.close()  # Wake held-body gates and reject every new call.
            self.release_payload()
            try:
                if self.process is not None:
                    if self.process.poll() is None:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=3)
                    self.process.stdin.close()
                    self.process.stdout.close()
                    self.process = None
                if self.relay is not None:
                    self.relay.__exit__(None, None, None)
                    require(not self.relay.thread.is_alive())
                    self.relay = None
                if self.scratch is not None:
                    self.scratch.cleanup()
                    self.scratch = None
            except Exception:
                return False
            self.stopped.set()  # No stop/reservation release before ALL three proofs.
            return True

    def release_payload(self):
        with self.lock:
            self.payload = None
            self.transport_factory = None
            self.controls.clear()

    def purge(self):
        require(self.stopped.is_set())
        self.release_payload()
        with self.lock:
            self.events.clear()
            self.bytes = 0
            self.replied = set()
            self.purged = True


class Broker:
    def __init__(self, directory, *, persistent_directory=False, transport_factory=None,
                 mode="synthetic", scratch_parent="/tmp/opencode", owned_runtime=False):
        require(os.getuid() == os.geteuid() == 1000 and os.getgid() == 1000)
        check_runtime()
        require(directory.parent == Path("/tmp/opencode") or owned_runtime)
        self.persistent_directory = persistent_directory
        # Host-process injection ONLY. No channel field/CLI flag can choose a
        # transport, endpoint, credential or live activation for a worker.
        require(mode in ("synthetic", "operator", "planning"))
        require(mode == "synthetic" or transport_factory is not None)
        self.transport_factory = transport_factory or SyntheticProduct
        self.mode = mode  # Explicit trusted construction, NEVER inferred from injection.
        self.scratch_parent = scratch_parent
        # A bind mount pins the directory inode, not its pathname. Explicit
        # retained-channel mode preserves that inode across clean restarts.
        # Never adopt a symlink, foreign/writable directory or stale socket.
        if persistent_directory and directory.exists():
            validate_persistent_directory(directory)
        else:
            require(not directory.exists())
            directory.mkdir(mode=0o711)
            directory.chmod(0o711)
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 1000)
        self.directory = directory
        self.path = directory / "channel.sock"
        self.epoch = str(uuid.uuid4())
        self.turns = {}
        self.aborted_unknown = {}
        self.stop = threading.Event()
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(str(self.path))
        # The API container cannot share the host user's group. Linux SO_PEERCRED
        # admits ONLY UID10001; no secret file/env token or worker mount is needed.
        self.path.chmod(0o666)
        self.listener.listen(8)
        self.listener.settimeout(0.25)

    def handle(self, value):
        value = request(value)
        if value["op"] == "hello":
            return {"ok": True, "epoch": self.epoch, "mode": self.mode,
                    "admitting": len(self.turns) + len(self.aborted_unknown) < 248}
        require(value["epoch"] == self.epoch)
        key = scope(value)
        turn = self.turns.get(key[2])
        if value["op"] == "start":
            # Never resubmit, even after a completed/failed turn. Retained bounded
            # tombstones; bounded admission reserves 8 slots for uncertain aborts.
            # At capacity the service remains available for polls/cleanup/history,
            # but new turns require an explicit clean foreground human restart.
            require(turn is None and key[2] not in self.aborted_unknown
                    and len(self.turns) + len(self.aborted_unknown) < 248)
            require(sum(not item.stopped.is_set() for item in self.turns.values()) < 8)
            require(not any(item.key[0] == key[0] and not item.stopped.is_set()
                            for item in self.turns.values()))
            deadline = None
            if value["payload"].get("kind") == NATIVE_INLINE_CONTEXT:
                remaining = value["deadline"] - time.time()
                require(0 < remaining <= TURN_SECONDS)
                require(self.transport_factory is not SyntheticProduct)  # No fake ACK relabeled as PDF send.
                deadline = time.monotonic() + remaining
            turn = Turn(key, value["payload"], epoch=self.epoch, transport_factory=self.transport_factory,
                        scratch_parent=self.scratch_parent, deadline=deadline)
            self.turns[key[2]] = turn
            turn.thread.start()
            return {"ok": True, "epoch": self.epoch}
        if turn is None:
            if value["op"] in ("abort", "purge"):
                existing = self.aborted_unknown.get(key[2])
                require(existing is None or existing == key)
                require(existing is not None or len(self.turns) + len(self.aborted_unknown) < 256)
                # Abort can precede a delayed first start from a crashed API
                # pump. Preserve a tombstone so that start cannot execute later.
                self.aborted_unknown[key[2]] = key
            return {"ok": True, "epoch": self.epoch, "known": False, "stopped": True,
                    "events": [], "receipts": []}
        require(turn.key == key)
        if value["op"] == "authorize-send":
            require(not turn.stopped.is_set() and not turn.abort_requested.is_set())
            turn.receipts.grant(value["authorization"])
            return {"ok": True, "epoch": self.epoch}
        if value["op"] == "purge":
            turn.purge()  # Active/queued turns require explicit abort + confirmed stop first.
            return {"ok": True, "epoch": self.epoch, "known": True, "stopped": True,
                    "purged": True, "receipts": turn.receipts.snapshot()}
        if value["op"] == "abort":
            turn.abort_requested.set()
            if not turn.thread.is_alive() and not turn.stopped.is_set():
                require(turn.confirm_stop())
            require(turn.stopped.wait(STOP_SECONDS))
            return {"ok": True, "epoch": self.epoch, "stopped": True}
        if value["op"] == "poll":
            with turn.lock:
                page = turn.events[value["after"]:value["after"] + 16]
                if not turn.stopped.is_set():
                    page = [item for item in page if item["event"]["type"] not in
                            ("completed", "failed", "cancelled")]
            response = {"ok": True, "epoch": self.epoch, "known": True, "events": [],
                        "stopped": turn.stopped.is_set(), "receipts": turn.receipts.snapshot()}
            pending = turn.receipts.pending_authorization()
            if pending is not None:
                response["send_authorization"] = pending
            # Receipt overhead counts toward the unchanged final frame bound.
            # Shorten this PAGE only; the next cursor still retrieves every event.
            for item in page:
                response["events"].append(item)
                try:
                    encode(response)
                except ValueError:
                    response["events"].pop()
                    require(response["events"])
                    break
            return response
        require(not turn.stopped.is_set() and not turn.abort_requested.is_set())
        from app.chat_protocol import answer
        with turn.lock:
            pending = [item["event"] for item in turn.events
                       if item["event"]["type"] in ("question", "permission")
                       and item["event"]["data"]["id"] == value["interaction_id"]]
            require(len(pending) == 1 and len(turn.controls) < 16)
            interaction = pending[0]
            answer(interaction["type"], interaction["data"], value["answer"])
            # Tombstone separately; do not mutate an event already durably replayed.
            used = getattr(turn, "replied", set())
            require(value["interaction_id"] not in used)
            used.add(value["interaction_id"])
            turn.replied = used
            turn.controls.append({"op": "reply", "interaction_id": value["interaction_id"],
                                  "answer": value["answer"]})
        return {"ok": True, "epoch": self.epoch}

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    connection, _ = self.listener.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.settimeout(3)
                    def close_request(peer=connection):
                        try:
                            peer.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    guard = threading.Timer(4, close_request)
                    guard.start()
                    try:
                        _, uid, _ = struct.unpack("3i", connection.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        require(uid == 10001)
                        def frame_timeout(size):
                            nonlocal guard
                            if size > MAX_FRAME:
                                guard.cancel()
                                connection.settimeout(PDF_TRANSFER_SECONDS)
                                guard = threading.Timer(PDF_TRANSFER_SECONDS, close_request)
                                guard.start()
                        value = receive_request(connection, on_size=frame_timeout)
                        if value["op"] == "abort":
                            guard.cancel()
                            guard = threading.Timer(STOP_SECONDS + 1, close_request)
                            guard.start()
                        result = self.handle(value)
                        value = None  # Release start bytes BEFORE accepting stop/purge/control.
                        connection.settimeout(3)
                        connection.sendall(encode(result))
                    except Exception:
                        try:
                            connection.sendall(encode({"ok": False}))
                        except OSError:
                            pass
                    finally:
                        value = None  # Do not retain the last start body while accept waits.
                        guard.cancel()
        finally:
            for turn in self.turns.values():
                turn.abort_requested.set()
            deadline = time.monotonic() + 12
            for turn in self.turns.values():
                turn.thread.join(max(0, deadline - time.monotonic()))
            require(all(not turn.thread.is_alive() for turn in self.turns.values()))
            require(all(turn.stopped.is_set() for turn in self.turns.values()))
            self.listener.close()
            self.path.unlink()
            if not self.persistent_directory:
                self.directory.rmdir()


def validate_persistent_directory(directory):
    info = directory.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == info.st_gid == 1000
            and stat.S_IMODE(info.st_mode) == 0o711 and not any(directory.iterdir()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("synthetic",))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--persistent-directory", action="store_true",
                        help="Retain the empty owned fixture mount directory on clean stop")
    args = parser.parse_args()
    broker = Broker(args.directory, persistent_directory=args.persistent_directory)
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: broker.stop.set())
    broker.run()


if __name__ == "__main__":
    raise SystemExit(main())
