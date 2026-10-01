"""COORDINATOR ONLY, REVIEW BEFORE EXECUTION: owned synthetic NORMAL-stack proof.

No public connection/operator modes, real credentials/accounts, private discovery
or live network. Uses ordinary OwnedRuntime/Connection core, ordinary Compose chat
overlay and normal mode admission. Disposable Docker inputs/DB cleanup reuse the
reviewed coordinator harness, never the ordinary human launcher.
"""

import json
import os
from pathlib import Path
import signal
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imp002_prototype import CapabilityError
from imp005_connection import Connection, OwnedRuntime
from imp024_broker import SyntheticProduct
from imp024_operator_helper import MemberOutput
from imp024_operator_product import ProductAcceptance
from imp024_operator_transport import PlanningHTTPSInference, explicit_contract
from imp024_operator_verify import SyntheticAcceptance
from imp024_verify import CheckOutput, RuffJsonOutput, Verify, reap_children, report, require

API_CHECK_FILES = (
    "app/chat.py", "app/chat_admission.py", "app/chat_dispatch.py", "tests/test_chat.py",
    "tests/imp005_synthetic_scope.py", "tests/imp005_scoped_server.py",
    "tests/imp024_joined.py", "tests/test_chat_postgres.py",
)


class EarlyResponse:
    """Generated frames only. Delay terminal to expose an observable early window."""
    def __init__(self, frames):
        self.frames = iter(frames)

    def read1(self, _):
        raw = next(self.frames, b"")
        if b"event: response.completed" in raw:
            time.sleep(0.5)
        return raw


class SyntheticTransport:
    def __init__(self, payload):
        self.source = (SyntheticAcceptance(payload) if
                       "Target data (JSON, not instructions from a file):\n" in payload["prompt"]
                       else SyntheticProduct(payload))
        # No DNS/TLS/connection invocation; pure normalizer with a generated key.
        self.normalizer = object.__new__(PlanningHTTPSInference)
        self.normalizer.contract = explicit_contract("https://synthetic.example.invalid",
                                                    "/openai/v1/responses", "none", "synthetic")
        self.normalizer.acquire("generated-synthetic-key-not-real")

    def events(self, data, cancelled, deadline):
        yield from self.normalizer.normalize_planning(
            EarlyResponse(self.source.events(data, cancelled, deadline)), data, cancelled, deadline)


class NormalVerify(Verify):
    def __init__(self):
        super().__init__()
        self.connection = self.runtime = self.product = None
        self.phase = "prepare_base"

    def stage(self, phase):
        # Fixed call-site names only; never exception text, paths or input values.
        self.phase = phase
        report("ordinary_connection_phase", "started", phase=phase)

    def static_check(self, *args, output):
        try:
            self.compose("run", "--rm", "api-check", *args, output=output)
        except Exception:
            # Parsers project only the fixed input filenames/rules/line numbers.
            # Never emit Ruff messages, source, fixes, raw output or exceptions.
            report("ordinary_connection_static_diagnostic", "failed", phase=self.phase,
                   reasons=sorted(output.reasons) or ["check_operation_failed"],
                   findings=output.findings)
            raise

    def prepare(self):
        self.stage("prepare_base")
        super().prepare()
        self.stage("prepare_retire_channel")
        # Replace only the exclusively created EMPTY synthetic channel. No host
        # setup path or stale state is adopted; ordinary core uses private parent.
        old = self.channel
        old.rmdir()
        os.close(self.directories.pop(old))
        self.channel_owned = False
        self.stage("prepare_runtime")
        # Keep nested turn relay.sock below Linux's 108-byte sockaddr_un field.
        # Base inputs already include the random project label + mkdtemp suffix;
        # no shortening of the private parent, mount policy or ownership checks.
        self.runtime = OwnedRuntime(self.inputs / "chat")
        self.stage("prepare_channel")
        self.channel = self.runtime.channel
        self.channel_owned = True
        self.pin_directory(self.channel)
        self.stage("prepare_compose_inputs")
        env = self.inputs / "fixture.env"
        env.write_text(env.read_text() + "IMPOSTR_CHAT_CHANNEL_DIR=" + str(self.channel) + "\n")
        self.base[-1] = "compose.chat.yaml"
        # Only the development CHECK container gets the reviewed synthetic flags;
        # ordinary API runtime uses planning mode, no test scope/activation switch.
        overlay = self.inputs / "checks.yaml"
        overlay.write_text(json.dumps({"services": {"api-integration-check": {
            "environment": {"IMPOSTR_TEST_CHAT_CHANNEL": "1", "IMPOSTR_TEST_CHAT_JOINED": "1",
                            "IMPOSTR_CHAT_ENABLED": "1"},
            "volumes": [{"type": "bind", "source": str(self.channel), "target": "/run/impostr-broker",
                         "read_only": True, "bind": {"create_host_path": False}}]}}}))
        self.base += ["-f", str(overlay)]

    def start_broker(self):
        require(self.connection is None)
        self.stage("broker_runtime")
        if self.runtime is None:
            self.runtime = OwnedRuntime(self.inputs / "chat")
        self.stage("broker_construct")
        self.connection = Connection(self.runtime, SyntheticTransport, mode="planning")
        self.stage("broker_start")
        self.connection.start()

    def stop_broker(self):
        try:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
        finally:
            reap_children(self.active)
        if self.runtime is not None:
            self.runtime.close(clean=True)
            self.runtime = None

    def run(self):
        passed = False
        try:
            self.prepare()
            self.start_broker()
            self.stage("build")
            self.compose("build", "db", "api", "api-check", "api-integration-check", "frontdoor", seconds=600)
            self.stage("database")
            self.compose("up", "-d", "--wait", "db")
            self.stage("migration")
            self.compose("run", "--rm", "api", "alembic", "upgrade", "head")
            self.stage("api_tests")
            self.compose("run", "--rm", "api-check", "python", "-m", "pytest", "-p", "no:cacheprovider",
                         "tests/test_chat.py", seconds=180, output=CheckOutput("pytest"))
            self.stage("api_lint")
            self.static_check("ruff", "check", "--output-format", "json", *API_CHECK_FILES,
                              output=RuffJsonOutput(check_files=API_CHECK_FILES))
            self.stage("api_format")
            self.static_check("ruff", "format", "--check", *API_CHECK_FILES,
                              output=CheckOutput("ruff_format", check_files=API_CHECK_FILES))
            self.stage("api_types")
            self.compose("run", "--rm", "api-check", "mypy", "app", output=CheckOutput("mypy"))
            self.stage("joined_flow")
            self.joined("check")
            self.stage("joined_lifecycle")
            self.joined("lifecycle")
            self.stage("ordinary_frontdoor")
            # Ordinary runtime API/frontdoor too, not only instrumented test API.
            member = MemberOutput()
            self.compose("run", "--rm", "api-integration-check", "python", "-B",
                         "tests/imp024_operator_member.py", output=member)
            # Joined tests use internal API origin8080; only the subsequent
            # ordinary frontdoor gets a reserved disposable loopback host port.
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            url = "http://127.0.0.1:" + str(port)
            env = self.inputs / "fixture.env"
            env.write_text(env.read_text().replace("APP_PORT=8080\n", f"APP_PORT={port}\n").replace(
                "IMPOSTR_PUBLIC_ORIGIN=http://127.0.0.1:8080\n", "IMPOSTR_PUBLIC_ORIGIN=" + url + "\n"))
            self.compose("up", "-d", "--wait", "api", "frontdoor")
            self.product = ProductAcceptance(url, member.login)
            self.product.run()
            require(self.connection.thread.is_alive() and not self.connection.failed.is_set())
            report("ordinary_stack_synthetic_connection_lifecycle", "passed")
            passed = True
        except (Exception, KeyboardInterrupt) as error:
            reason = ("runtime_capability" if isinstance(error, CapabilityError) else
                      "filesystem_operation" if isinstance(error, OSError) else
                      "contract_rejected" if isinstance(error, ValueError) else
                      "interrupted" if isinstance(error, KeyboardInterrupt) else "operation_failed")
            report("ordinary_stack_synthetic_connection_lifecycle", "failed",
                   phase=self.phase, reason=reason)
        finally:
            if self.product is not None:
                self.product.close()
            passed = self.cleanup() and passed
        return 0 if passed else 1


def main():
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return NormalVerify().run()


if __name__ == "__main__":
    raise SystemExit(main())
