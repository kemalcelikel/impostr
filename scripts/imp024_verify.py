"""COORDINATOR ONLY: disposable synthetic joined/lifecycle/workflow orchestration.

Never run by product workers/developers. No operator/live modes, ambient settings,
checkout .env, raw output forwarding, shell input or Docker socket worker mount.
Independent review required before execution. Import/tests have no side effects.
"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PARENT = Path("/tmp/opencode")
PROMPTS = (
    b"ACTION: SIGTERM owned broker; wait for exit/worker cleanup; restart with --persistent-directory; then press Enter: ",
    b"ACTION: SIGTERM owned broker and leave stopped; then press Enter: ",
    b"ACTION: restart owned broker with --persistent-directory; then press Enter: ",
    b"ACTION: stop owned Compose db; then press Enter: ",
    b"ACTION: start owned Compose db; wait for healthy; then press Enter: ",
)
CHECK_PASSES = (
    "joined native flow, API process restart, concurrent inference/save conflict",
    "PostgreSQL human-save/import race and provenance",
    "real matching-head agent import invalidates existing approvals",
    "actual API crash after start ACK: uncertain dispatch not repeated",
    "actual API crash after reply ACK: no duplicate reply",
    "joined active HTTP stream/session revocation, stale/queued reply denial",
    "joined revocation after native completion prevents durable import",
)
LIFECYCLE_PASSES = (
    "full API/broker/worker restart: unknown interrupted, no redispatch",
    "channel outage/restoration without false import or duplicate start",
    "actual DB outage/recovery: unavailable, no false completion/import or redispatch",
)
WORKFLOW_PASSES = (
    "agent pair/backlog imports, human readiness/approvals, exact three downloads",
    "native agent readiness change rejected without imports or approval drift",
    "agent pair change invalidates both gates; explicit exact reapproval",
    "reconnect/full restart interruption, new successful turn, backlog-only invalidation and exact reapproval",
)
OWNED_CLEANUP = "owned API child/account/project/test-state cleanup; broker/stack cleanup still coordinator-owned"
CHECK_FILES = (
    "app/chat_protocol.py",
    "app/chat_state.py",
    "app/chat_dispatch.py",
    "tests/imp024_joined.py",
    "tests/imp024_http.py",
    "tests/test_chat.py",
)
FOCUSED_CHECKS = (
    ("pytest", ("python", "-m", "pytest", "-p", "no:cacheprovider", "tests/test_chat.py")),
    ("ruff_lint", ("ruff", "check", "--output-format", "json") + CHECK_FILES),
    ("ruff_format", ("ruff", "format", "--check") + CHECK_FILES),
    ("mypy", ("mypy", "app")),
)
FAILURES = {
    b"FAIL Timed out: native pending permission": "pending_permission_timeout",
    b"FAIL Timed out: post-restart native poll ACK": "recovery_poll_timeout",
    b"FAIL turn ended before native interaction": "turn_ended_before_interaction",
    b"FAIL same-epoch recovery did not retain running turn": "recovery_turn_ended",
    b"FAIL unexpected durable turn outcome": "unexpected_terminal",
    b"FAIL fixture operation failed": "fixture_operation_failed",
}


class Unavailable(Exception):
    """No raw exception/command/output details may escape this helper."""


def require(value):
    if not value:
        raise Unavailable()


def report(check, status, **safe):
    print(json.dumps({"check": check, "status": status, **safe}), flush=True)


class Output:
    """Bounded incremental recognition, including input() prompts without newline.

    Only fixed PASS/failure strings and allowlisted summary fields survive. All
    other bytes are discarded, including build logs and raw assertion details. Never use output as a
    command: the prompt index selects one of five fixed coordinator actions;
    workflow mode uses only the existing first broker-restart action.
    """

    def __init__(self, action=None):
        self.action = action
        self.next_prompt = 0
        self.buffer = b""
        self.passed = set()
        self.total = 0

    def feed(self, block):
        self.total += len(block)
        require(self.total <= 32 * 1024 * 1024)
        self.buffer += block
        while self.buffer:
            matches = [(self.buffer.find(marker), index) for index, marker in enumerate(PROMPTS)]
            matches = [pair for pair in matches if pair[0] >= 0]
            prompt = min(matches) if matches else None
            newline = self.buffer.find(b"\n")
            if prompt and (newline < 0 or prompt[0] < newline):
                offset, index = prompt
                require(offset == 0 and self.action is not None and index == self.next_prompt)
                self.buffer = self.buffer[len(PROMPTS[index]) :]
                self.action(index)
                self.next_prompt += 1
            elif newline >= 0:
                self.line(self.buffer[:newline].rstrip(b"\r"))
                self.buffer = self.buffer[newline + 1 :]
            else:
                # Long/unrecognized output cannot become an unbounded transcript.
                require(len(self.buffer) <= 64 * 1024)
                break

    def line(self, line):
        for text in CHECK_PASSES + LIFECYCLE_PASSES + WORKFLOW_PASSES + (OWNED_CLEANUP,):
            if line == ("PASS " + text).encode():
                self.passed.add(text)
                report(text, "passed")
        if line in FAILURES:
            report("joined_assertion", "failed", reason=FAILURES[line])
        if line.startswith(b'{"diagnostic":') and len(line) <= 8192:
            self.diagnostic(line)

    @staticmethod
    def diagnostic(line):
        try:
            value = json.loads(line)
            if value.get("diagnostic") == "unavailable":
                report("joined_diagnostic", "unavailable")
                return
            require(value.get("diagnostic") == "joined_turn")
            states = {
                "queued",
                "dispatching",
                "running",
                "cancelling",
                "completed",
                "failed",
                "cancelled",
                "interrupted",
                "unknown",
            }
            require(value.get("state") in states)
            # Construct anew; do not forward any arbitrary field from child JSON.
            safe = {"state": value["state"]}
            for key, maximum in (
                ("lease_remaining_seconds", 20),
                ("broker_cursor", 256),
                ("largest_poll_gap_seconds", 600),
            ):
                if key in value:
                    require(type(value[key]) in (int, float) and 0 <= value[key] <= maximum)
                    safe[key] = value[key]
            reasons = value.get("failure_reasons", [])
            allowed = {
                "native_stream_timeout",
                "native_stream_invalid",
                "native_session_error",
                "worker_deadline",
                "worker_error",
                "broker_worker_error",
                "unspecified",
            }
            require(
                isinstance(reasons, list)
                and len(reasons) <= 256
                and all(reason in allowed for reason in reasons)
            )
            safe["failure_reasons"] = reasons
            interactions = value.get("interactions", [])
            require(isinstance(interactions, list) and len(interactions) <= 256)
            safe["interactions"] = []
            for row in interactions:
                require(
                    row.get("kind") in ("question", "permission", "unknown")
                    and row.get("state")
                    in ("pending", "replying", "replied", "interrupted", "unknown")
                    and type(row.get("dispatched")) is bool
                )
                safe["interactions"].append(
                    {key: row[key] for key in ("kind", "state", "dispatched")}
                )
            safe["calls"] = {}
            for op in ("start", "reply", "poll", "abort"):
                safe["calls"][op] = {}
                for stage in ("before", "after"):
                    count = value["calls"][op][stage]
                    require(type(count) is int and 0 <= count <= 10000)
                    safe["calls"][op][stage] = count
            report("joined_diagnostic", "observed", **safe)
        except Exception:
            report("joined_diagnostic", "unavailable")


def stop_process(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def adopted_children():
    # Only this helper's children, never host cmdline/environ or all-process scans.
    return [int(pid) for pid in Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()]


def reap_children(exclude=()):
    # Linux subreaper adopts detached broker worker descendants after broker exit.
    # pidfds bind signals to the owned child, avoiding a reused-PID target.
    deadline = time.monotonic() + 5
    while set(adopted_children()) - set(exclude) and time.monotonic() < deadline:
        # Repeat for descendants adopted when a detached child is killed.
        for pid in set(adopted_children()) - set(exclude):
            try:
                fd = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                try:
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            finally:
                os.close(fd)
            for pid in set(adopted_children()) - set(exclude):
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass
        time.sleep(0.05)
    require(not (set(adopted_children()) - set(exclude)))


class EmptyOutput:
    stdout_only = True

    def feed(self, block):
        require(not block)


class CheckOutput(Output):
    def __init__(self, check):
        super().__init__()
        self.check = check
        self.reasons = set()
        self.findings = []

    def line(self, line):
        # Recognize shapes, never arbitrary filenames/test names/error messages.
        if self.check == "pytest":
            for shape, reason in (
                (rb"\b[1-9][0-9]* failed\b", "tests_failed"),
                (rb"\b[1-9][0-9]* errors?\b", "test_errors"),
                (rb"^ImportError while loading conftest", "test_import_error"),
            ):
                if re.search(shape, line):
                    self.reasons.add(reason)
        elif self.check == "ruff_format" and line.startswith(b"Would reformat:"):
            self.reasons.add("format_mismatch")
            path = line.removeprefix(b"Would reformat:").strip().decode("utf-8", errors="replace")
            if path in CHECK_FILES:
                self.findings.append({"file": path, "code": "format_mismatch"})
        elif self.check == "ruff_lint" and re.search(rb"\b(?:E|F|I|UP|B)[0-9]{3}\b", line):
            self.reasons.add("lint_findings")
        elif self.check == "mypy" and b": error:" in line:
            self.reasons.add("type_errors")


class RuffJsonOutput:
    stdout_only = True

    def __init__(self):
        self.buffer = bytearray()
        self.reasons = set()
        self.findings = []

    def feed(self, block):
        require(len(self.buffer) + len(block) <= 512 * 1024)
        self.buffer.extend(block)

    def finish(self):
        try:
            rows = json.loads(self.buffer)
            require(isinstance(rows, list) and len(rows) <= 256)
            projected = []
            filenames = {name: name for name in CHECK_FILES}
            filenames.update({"/app/" + name: name for name in CHECK_FILES})
            for row in rows:
                require(isinstance(row, dict))
                filename, code = row.get("filename"), row.get("code")
                require(isinstance(filename, str) and filename in filenames)
                require(isinstance(code, str) and re.fullmatch(r"(?:E|F|I|UP|B)[0-9]{3}", code))
                location = row.get("location")
                require(isinstance(location, dict))
                line = location.get("row")
                require(type(line) is int and 1 <= line <= 10000)
                projected.append({"file": filenames[filename], "code": code, "line": line})
            # Atomic projection: malformed rows never produce a partial raw report.
            self.findings = projected
            if projected:
                self.reasons.add("lint_findings")
        except Exception:
            self.reasons.add("lint_diagnostic_unavailable")
            raise Unavailable() from None
        finally:
            self.buffer.clear()  # No messages/snippets/fix contents retained or emitted.


class Verify:
    def __init__(self):
        self.project = "imp024-verify-" + secrets.token_hex(6)
        self.channel = PARENT / self.project
        self.inputs = None
        self.broker = None
        self.runs = []
        self.compose_used = False
        self.environment = None
        self.base = None
        self.active = set()
        self.channel_owned = False
        self.directories = {}

    def pin_directory(self, path, mode=None):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(info.st_uid == info.st_gid == 1000)
            if mode is not None:
                os.fchmod(fd, mode)  # Only a newly created per-run child, never PARENT.
            else:
                # Approved synthetic scratch, NOT the private credential-reader
                # ancestor policy. Shared-group writes are allowed here only.
                require(not info.st_mode & 0o002)
            self.directories[path] = fd
        except BaseException:
            os.close(fd)
            raise

    def check_directories(self):
        for path, fd in self.directories.items():
            current, held = path.lstat(), os.fstat(fd)
            require(
                stat.S_ISDIR(current.st_mode)
                and (current.st_dev, current.st_ino) == (held.st_dev, held.st_ino)
                and current.st_uid == current.st_gid == 1000
            )

    def prepare(self):
        require(os.getuid() == os.geteuid() == os.getgid() == 1000)
        self.pin_directory(PARENT)
        require(ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0)  # CHILD_SUBREAPER
        # Exclusively reserve the broker path; never clean up a colliding path.
        self.channel.mkdir(mode=0o711)
        self.channel_owned = True
        self.pin_directory(self.channel, 0o711)
        self.inputs = Path(tempfile.mkdtemp(prefix=self.project + "-inputs-", dir=PARENT))
        self.pin_directory(self.inputs, 0o700)
        self.check_directories()
        self.environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(self.inputs)}
        env = self.inputs / "fixture.env"
        values = {
            "POSTGRES_DB": "impostr",
            "POSTGRES_USER": "impostr_owner",
            "DB_USER": "impostr_app",
            "POSTGRES_PASSWORD": secrets.token_hex(32),
            "DB_PASSWORD": secrets.token_hex(32),
            "IMPOSTR_RATE_LIMIT_KEY": secrets.token_hex(32),
            "APP_PORT": "8080",
            "IMPOSTR_PUBLIC_ORIGIN": "http://127.0.0.1:8080",
            "IMPOSTR_SYNTHETIC_BROKER_DIR": str(self.channel),
        }
        fd = os.open(
            "fixture.env",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.directories[self.inputs],
        )
        with os.fdopen(fd, "w") as output:
            output.write("".join(key + "=" + value + "\n" for key, value in values.items()))
        self.base = [
            "docker",
            "--host",
            "unix:///var/run/docker.sock",
            "compose",
            "--env-file",
            str(env),
            "-p",
            self.project,
            "-f",
            "compose.yaml",
            "-f",
            "compose.chat-synthetic.yaml",
        ]
        report(
            "owned_fixture", "prepared", project=self.project
        )  # Resource label, not credentials.

    def command(self, args, *, seconds=180, output=None):
        self.check_directories()
        process = subprocess.Popen(
            args,
            cwd=ROOT,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if getattr(output, "stdout_only", False) else subprocess.STDOUT,
            start_new_session=True,
        )
        self.active.add(process.pid)
        parser = output or Output()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        if process.stderr is not None:
            selector.register(process.stderr, selectors.EVENT_READ)
        stderr_bytes = 0
        deadline = time.monotonic() + seconds
        try:
            while selector.get_map():
                require(time.monotonic() < deadline)
                for key, _ in selector.select(0.1):
                    block = os.read(key.fileobj.fileno(), 4096)
                    if block:
                        if key.fileobj is process.stdout:
                            parser.feed(block)
                        else:
                            stderr_bytes += len(block)
                            require(stderr_bytes <= 1024 * 1024)
                    else:
                        selector.unregister(key.fileobj)
            status = process.wait(timeout=5)
            if hasattr(parser, "finish"):
                parser.finish()
            require(status == 0)
            return parser
        finally:
            selector.close()
            stop_process(process)
            process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            self.active.discard(process.pid)

    def compose(self, *args, **kwargs):
        self.compose_used = True
        return self.command(self.base + list(args), **kwargs)

    def start_broker(self):
        require(self.broker is None)
        self.check_directories()
        self.broker = subprocess.Popen(
            [
                "/usr/bin/python3",
                "-I",
                "-B",
                "scripts/imp024_broker.py",
                "synthetic",
                "--directory",
                str(self.channel),
                "--persistent-directory",
            ],
            cwd=ROOT,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            require(self.broker.poll() is None)
            try:
                info = (self.channel / "channel.sock").lstat()
                if stat.S_ISSOCK(info.st_mode) and info.st_uid == 1000:
                    return
            except FileNotFoundError:
                pass
            time.sleep(0.05)
        raise Unavailable()

    def stop_broker(self):
        if self.broker is not None:
            process, self.broker = self.broker, None
            stop_process(process)
        # Exclude the still-running joined Docker CLI during lifecycle actions.
        reap_children(self.active)
        if self.channel_owned:
            require(not (self.channel / "channel.sock").exists())

    def joined(self, mode):
        self.check_directories()
        name = self.project + "-" + mode
        self.runs.append(name)
        args = self.base + ["run", "--rm", "--name", name]
        if mode in ("lifecycle", "workflow"):
            args += ["-i"]  # Piped input, NOT a pseudo-terminal.
        args += ["api-integration-check", "python", "-B", "tests/imp024_joined.py", mode]
        process = subprocess.Popen(
            args,
            cwd=ROOT,
            env=self.environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.active.add(process.pid)

        def action(index):
            if index in (0, 1):
                self.stop_broker()
            if index in (0, 2):
                self.start_broker()
            if index == 3:
                self.compose("stop", "db")
            if index == 4:
                self.compose("start", "db")
                self.compose("up", "-d", "--wait", "db")
            process.stdin.write(b"\n")
            process.stdin.flush()

        parser = Output(action if mode in ("lifecycle", "workflow") else None)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 600
        try:
            while selector.get_map():
                require(time.monotonic() < deadline)
                for _, _ in selector.select(0.1):
                    block = os.read(process.stdout.fileno(), 4096)
                    if block:
                        parser.feed(block)
                    else:
                        selector.unregister(process.stdout)
            require(process.wait(timeout=5) == 0)
            expected = {
                "check": CHECK_PASSES,
                "lifecycle": LIFECYCLE_PASSES,
                "workflow": WORKFLOW_PASSES,
            }[mode]
            require(set(expected + (OWNED_CLEANUP,)) <= parser.passed)
            require(parser.next_prompt == {"check": 0, "lifecycle": 5, "workflow": 1}[mode])
        finally:
            selector.close()
            stop_process(process)
            process.stdin.close()
            process.stdout.close()
            self.active.discard(process.pid)

    def cleanup(self):
        okay = True

        def step(label, operation):
            nonlocal okay
            try:
                operation()
                report("cleanup_" + label, "passed")
            except Exception:
                okay = False
                report("cleanup_" + label, "failed")

        # A stopped Docker CLI can leave its container/API child alive. Remove only
        # our explicitly named runs, then the labeled disposable Compose stack.
        for name in self.runs:
            try:
                self.command(["docker", "--host", "unix:///var/run/docker.sock", "rm", "-f", name])
            except Exception:
                pass  # Normal --rm success already removed the name; verify below.
        step("broker_children", self.stop_broker)
        if self.compose_used:
            step(
                "compose_down",
                lambda: self.compose(
                    "--profile",
                    "checks",
                    "--profile",
                    "integration",
                    "down",
                    "-v",
                    "--remove-orphans",
                    "--rmi",
                    "local",
                ),
            )
            for kind in ("container", "volume", "network"):

                def inventory(kind=kind):
                    # Verify label-scoped inventory only; don't expose IDs/names.
                    args = [
                        "docker",
                        "--host",
                        "unix:///var/run/docker.sock",
                        kind,
                        "ls",
                        "-q",
                        "--filter",
                        "label=com.docker.compose.project=" + self.project,
                    ]
                    if kind == "container":
                        args.append("-a")  # Stopped leaked check containers count too.
                    self.command(args, seconds=20, output=EmptyOutput())

                step(kind + "_inventory", inventory)

            def images():
                self.command(
                    [
                        "docker",
                        "--host",
                        "unix:///var/run/docker.sock",
                        "image",
                        "ls",
                        "-q",
                        "--filter",
                        "reference=" + self.project + "-*",
                    ],
                    seconds=20,
                    output=EmptyOutput(),
                )

            step("image_inventory", images)

        def channel():
            if self.channel_owned:
                self.check_directories()
                self.channel.rmdir()  # Never unlink/adopt an arbitrary stale socket.
                os.close(self.directories.pop(self.channel))

        step("channel_directory", channel)

        def inputs():
            if self.inputs is not None:
                self.check_directories()
                shutil.rmtree(self.inputs)  # Only this mkdtemp's env/generated Docker client state.

        step("generated_inputs", inputs)
        for fd in self.directories.values():
            os.close(fd)
        self.directories.clear()
        report("owned_cleanup", "passed" if okay else "failed", project=self.project)
        return okay

    def run(self, *, phase_four_only=False):
        stage = "prepare"
        passed = False
        try:
            self.prepare()
            stage = "broker_start"
            self.start_broker()
            for stage, args, seconds in (
                ("build", ("build", "db", "api", "api-check", "api-integration-check"), 600),
                ("database", ("up", "-d", "db"), 180),
                ("migration", ("run", "--rm", "api", "alembic", "upgrade", "head"), 180),
            ):
                self.compose(*args, seconds=seconds)
                report(stage, "passed")
            for stage, args in FOCUSED_CHECKS:
                if phase_four_only and stage in ("pytest", "mypy"):
                    continue  # Delivered backend behavior unchanged; reuse its verified evidence.
                output = RuffJsonOutput() if stage == "ruff_lint" else CheckOutput(stage)
                try:
                    self.compose("run", "--rm", "api-check", *args, seconds=300, output=output)
                except Exception:
                    report(
                        stage + "_diagnostic",
                        "failed",
                        reasons=sorted(output.reasons) or ["check_operation_failed"],
                        findings=output.findings,
                    )
                    raise
                report(stage, "passed")
            for stage in (("workflow",) if phase_four_only else ("check", "lifecycle")):
                self.joined(stage)
                report(stage, "passed")
            passed = True
        except (Exception, KeyboardInterrupt):
            report(stage, "failed")
        finally:
            passed = self.cleanup() and passed
        check = "synthetic_workflow_verification" if phase_four_only else "synthetic_joined_verification"
        report(check, "passed" if passed else "failed")
        return 0 if passed else 1


if __name__ == "__main__":

    def interrupted(*_):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase-four-only", action="store_true",
        help="Run integrated workflow/recovery proof, reusing delivered backend gates",
    )
    args = parser.parse_args()
    raise SystemExit(Verify().run(phase_four_only=args.phase_four_only))
