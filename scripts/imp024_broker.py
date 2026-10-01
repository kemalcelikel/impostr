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
                               receive, request, require, scope)
from imp002_prototype import check_runtime, command
from imp002_relay import SyntheticRelay
from imp024_inference import native_response

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

    def events(self, data, cancelled, deadline):
        self.calls += 1
        require(self.calls <= 8)
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


def send_pipe(process, value):
    value = encode(value)
    fd = process.stdin.fileno()
    os.set_blocking(fd, False)
    deadline = time.monotonic() + 3
    while value:
        require(time.monotonic() < deadline and process.poll() is None)
        if select.select([], [fd], [], 0.05)[1]:
            count = os.write(fd, value)
            require(count > 0)
            value = value[count:]


class Turn:
    def __init__(self, key, payload, *, transport_factory=SyntheticProduct, scratch_parent="/tmp/opencode"):
        self.key, self.payload = key, payload
        self.transport_factory = transport_factory
        self.scratch_parent = scratch_parent
        self.events = []
        self.bytes = 0
        self.controls = []
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.abort_requested = threading.Event()
        self.deadline = time.monotonic() + TURN_SECONDS
        self.thread = threading.Thread(target=self.run, daemon=True)

    def add(self, value):
        value = event(value)
        with self.lock:
            self.bytes += len(encode(value))
            require(self.bytes <= MAX_FRAME and len(self.events) < MAX_EVENTS - 2)
            self.events.append({"sequence": len(self.events) + 1, "event": value})

    def run(self):
        process = None
        terminal = False
        try:
            with tempfile.TemporaryDirectory(prefix="imp024-turn-", dir=self.scratch_parent) as name:
                root = Path(name)
                root.chmod(0o700)
                for directory in ("project", "code", "empty", "config"):
                    (root / directory).mkdir(mode=0o700)
                (root / "config" / "opencode").mkdir(mode=0o700)
                (root / "config" / "opencode" / ".gitignore").write_text("node_modules\n")
                copy_worker_code(root / "code")
                for filename, document in self.payload["documents"].items():
                    (root / "project" / filename).write_bytes(document["content"].encode("utf-8"))
                    (root / "project" / filename).chmod(0o600)
                with SyntheticRelay(root / "relay.sock", lifetime=60,
                                    transport=self.transport_factory(self.payload), planning=True,
                                    input_text_limit=MAX_CONTEXT):
                    process = subprocess.Popen(worker_command(root), stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        env={"PATH": "/usr/bin:/bin"}, close_fds=True, start_new_session=True)
                    send_pipe(process, self.payload)
                    # Incremental bounded framing; no unbounded readline or process
                    # wait before draining. Abort/control never exposes host sockets.
                    selector = selectors.DefaultSelector()
                    selector.register(process.stdout, selectors.EVENT_READ)
                    buffer = bytearray()
                    try:
                        while time.monotonic() < self.deadline:
                            if self.abort_requested.is_set():
                                break
                            with self.lock:
                                controls, self.controls = self.controls, []
                            for control in controls:
                                send_pipe(process, control)
                            for _, _ in selector.select(0.05):
                                block = os.read(process.stdout.fileno(), 8192)
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
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=3)
        except Exception:
            pass
        finally:
            if process is not None:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
                process.stdin.close()
                process.stdout.close()
            if not terminal:
                try:
                    cancelled = self.abort_requested.is_set()
                    self.add({"type": "cancelled" if cancelled else "failed",
                              "data": {} if cancelled else {"reason": "broker_worker_error"}})
                except Exception:
                    pass
            self.stopped.set()


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
            turn = Turn(key, value["payload"], transport_factory=self.transport_factory,
                        scratch_parent=self.scratch_parent)
            self.turns[key[2]] = turn
            turn.thread.start()
            return {"ok": True, "epoch": self.epoch}
        if turn is None:
            if value["op"] == "abort":
                existing = self.aborted_unknown.get(key[2])
                require(existing is None or existing == key)
                require(existing is not None or len(self.turns) + len(self.aborted_unknown) < 256)
                # Abort can precede a delayed first start from a crashed API
                # pump. Preserve a tombstone so that start cannot execute later.
                self.aborted_unknown[key[2]] = key
            return {"ok": True, "epoch": self.epoch, "known": False, "stopped": True, "events": []}
        require(turn.key == key)
        if value["op"] == "abort":
            turn.abort_requested.set()
            require(turn.stopped.wait(4))
            return {"ok": True, "epoch": self.epoch, "stopped": True}
        if value["op"] == "poll":
            with turn.lock:
                page = turn.events[value["after"]:value["after"] + 16]
                if not turn.stopped.is_set():
                    page = [item for item in page if item["event"]["type"] not in
                            ("completed", "failed", "cancelled")]
            return {"ok": True, "epoch": self.epoch, "known": True, "events": page}
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
                    guard = threading.Timer(8, close_request)
                    guard.start()
                    try:
                        _, uid, _ = struct.unpack("3i", connection.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        require(uid == 10001)
                        value = receive(connection)
                        connection.sendall(encode(self.handle(value)))
                    except Exception:
                        try:
                            connection.sendall(encode({"ok": False}))
                        except OSError:
                            pass
                    finally:
                        guard.cancel()
        finally:
            for turn in self.turns.values():
                turn.abort_requested.set()
            deadline = time.monotonic() + 12
            for turn in self.turns.values():
                turn.thread.join(max(0, deadline - time.monotonic()))
            require(all(not turn.thread.is_alive() for turn in self.turns.values()))
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
