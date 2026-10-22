"""COORDINATOR ONLY: exact-input native PDF proof; review BEFORE execution.

Read-only command: --preflight. Execution requires --api-only or --synthetic,
--reviewed-harness and --fingerprint from review of these exact bytes. The latter
mode runs the fixed-path OpenCode -> shim -> broker -> PlanningHTTPSInference.events,
replacing ONLY its connection callable with an in-memory synthetic receiver.
No DNS/TLS/provider, extractor, private settings, host installs or live modes.

Both execution modes build the ordinary pinned API development image and use a
fresh owned PostgreSQL. Sources are frozen before any Docker/worker operation;
the child runs entirely from that snapshot. Output is fixed stage/category JSON,
never bodies, credentials, filenames from uploads, exception text or tracebacks.
Failed checks stop; there is no formatter diagnostic/rebuild/retry loop. Finally
reuse label-scoped stack/image/volume/child cleanup, including generated accounts,
private inputs and broker scratch. Cleanup failure makes the whole check fail.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "api/tests"))
from imp024_verify import CheckOutput, RuffJsonOutput, Unavailable, Verify, report, require
from app.chat_protocol import FAILURE_REASONS

BASELINE = "58bee0944e64ab6f17007a5366c59aa1a5114d32"
CHECKPOINT = "cd13cbf0cc590c239b55c09194f64c05358b0b7d"
# Only owner-approved runtime/stream repair and history bookkeeping may be committed.
# Candidate-only: a native delivery commit needs a separately reviewed checkpoint.
REPAIR_PATHS = frozenset({
    "scripts/imp002_prototype.py", "scripts/test_imp002_prototype.py",
    "scripts/imp023_worker.py", "scripts/test_imp023_session.py",
    "scripts/imp025_verify.py", "scripts/test_imp025_verify.py",
    "scripts/imp024_product_worker.py", "scripts/test_imp025_inline.py",
    "AGENTS.md", "PROJECT.md", "BACKLOG.md", "DONE.md",
    "docs/local-development.md", "docs/local-scope-history.md",
    "docs/agent-history.md",
})
MANIFEST = ".imp025-inputs.json"
# Preserve these superseded IMP-018 files outside native capture/execution.
SUPERSEDED_INPUTS = frozenset({
    "api/tests/test_chat_receipts.py", "api/tests/test_chat_references.py",
    "api/tests/test_chat_references_migration.py", "api/tests/imp018_pytest_diagnostic.py",
    "api/tests/imp018_scoped_server.py", "scripts/imp018_verify.py",
    "scripts/test_imp018_receipts.py", "scripts/test_imp018_verify.py",
})
NEW_INPUTS = (
    "api/app/attachment_cleanup.py", "api/app/chat_receipts.py", "api/app/chat_references.py",
    "api/migrations/versions/20261002_0010_pdf_turn_selections.py",
    "api/migrations/versions/20261014_0011_native_pdf_storage.py",
    "api/migrations/versions/20261014_0012_native_send_authorization.py",
    "api/tests/test_native_pdf_storage.py",
    "api/tests/test_native_pdf_migration.py", "api/tests/test_native_send_authorization.py",
    "api/tests/imp025_native_fixture.py",
    "api/tests/test_imp025_native_integration.py", "scripts/imp018_receipts.py",
    "scripts/test_imp018_references.py",
    "scripts/imp025_verify.py", "scripts/test_imp025_verify.py",
    "scripts/test_imp025_storage.py", "scripts/test_imp025_inline.py",
    "scripts/test_imp025_authorization.py", "scripts/test_imp025_wiring.py",
)
API_FILES = (
    "app/attachments.py", "app/attachment_cleanup.py", "app/chat.py", "app/chat_broker.py",
    "app/chat_dispatch.py", "app/chat_protocol.py", "app/chat_receipts.py", "app/chat_references.py",
    "app/chat_state.py", "app/main.py", "app/models.py", "app/pdf_intake.py",
    "migrations/versions/20261002_0010_pdf_turn_selections.py",
    "migrations/versions/20261014_0011_native_pdf_storage.py",
    "migrations/versions/20261014_0012_native_send_authorization.py",
    "tests/conftest.py", "tests/imp024_http.py", "tests/test_chat.py",
    "tests/test_native_pdf_storage.py", "tests/test_native_pdf_migration.py",
    "tests/test_native_send_authorization.py", "tests/imp025_native_fixture.py",
    "tests/test_imp025_native_integration.py",
)
# Superseded derivative selection/receipt suites are NOT native acceptance. Keep
# ordinary chat, original storage/auth/integrity and new native deletion regressions.
API_TESTS = (
    "tests/test_chat.py", "tests/test_native_pdf_storage.py", "tests/test_native_pdf_migration.py",
    "tests/test_native_send_authorization.py",
    "tests/test_imp025_native_integration.py::test_native_outage_restart_receipt_purge_quotes",
    "tests/test_imp025_native_integration.py::test_native_capture_delete_committed_fence",
    "tests/test_imp025_native_integration.py::test_native_active_delete_conflict_until_confirmed_stop",
)
PG_TESTS = (
    "tests/test_imp025_native_integration.py::test_postgres_native_migrations_preservation_and_legacy_fence",
    "tests/test_imp025_native_integration.py::test_postgres_native_capture_delete_race",
)
STAGES = frozenset({
    "preflight", "frozen_inputs", "build", "database", "postgres", "migration", "api_tests",
    "api_lint", "api_format", "api_types", "member", "broker", "api_start", "native_order",
    "native_history", "native_bound", "native_rejections", "native_outage", "native_purge",
    "native_complete", "snapshot_execution", "imp025_verification",
    "native_diagnostic",
})
NATIVE_OPERATIONS = frozenset({
    "product_request", "upload_first", "upload_second", "upload_response", "upload_identity",
    "send_first", "wait_history", "wait_turn", "wait_terminal", "wait_failure_events", "wait_submission", "wait_deadline",
    "receipt_kind", "receipt_count", "receipt_call", "order_followup", "order_manifest",
    "transport_submission", "transport_events", "transport_normalize", "receiver_route", "receiver_json",
    "receiver_envelope", "receiver_manifest", "receiver_part", "receiver_decode",
    "receiver_original", "receiver_bytes", "receiver_tool", "receiver_binding",
    "receiver_response", "receiver_close",
})
NATIVE_CATEGORIES = frozenset({
    "operation", "assertion", "filesystem", "shape", "missing_field", "http", "http_status",
    "timeout", "missing_turn", "turn_failed", "turn_cancelled", "turn_interrupted",
    "submission_not_sent", "identity", "count", "binding",
})


def native_diagnostic(operation, category, *, reason=None):
    """Fixed call-site labels only, including when private exception text exists."""
    require(operation in NATIVE_OPERATIONS and category in NATIVE_CATEGORIES)
    fields = dict(operation=operation, category=category)
    if reason in FAILURE_REASONS:
        fields["reason"] = reason
    report("native_diagnostic", "failed", **fields)


def native_require(value, operation, category, *, reason=None):
    if not value:
        native_diagnostic(operation, category, reason=reason)
        raise Unavailable()


@contextmanager
def native_probe(operation):
    require(operation in NATIVE_OPERATIONS)
    try:
        yield
    except Exception as error:
        import http.client
        category = ("assertion" if isinstance(error, AssertionError) else
                    "timeout" if isinstance(error, TimeoutError) else
                    "filesystem" if isinstance(error, OSError) else
                    "http" if isinstance(error, http.client.HTTPException) else
                    "missing_field" if isinstance(error, KeyError) else
                    "shape" if isinstance(error, (TypeError, AttributeError, ValueError))
                        and not isinstance(error, Unavailable) else "operation")
        native_diagnostic(operation, category)
        raise


def source_path(name):
    """Only fixed application/build/host-code inputs, not dotenv/log/config trees."""
    return (
        name in {".dockerignore", "compose.yaml", "compose.chat.yaml"}
        or name in {f"overnight-agent/{item}.md.example" for item in ("PROJECT", "AGENTS", "BACKLOG")}
        or (name.startswith(("api/", "db/", "web/"))
            and not any(part.startswith(".env") or part in {"node_modules", "__pycache__", ".git"}
                        for part in Path(name).parts))
        or name.startswith("scripts/") and name.endswith(".py")
    ) and not Path(name).is_absolute() and ".." not in Path(name).parts and name not in SUPERSEDED_INPUTS


def git(*args):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, env={"PATH": "/usr/bin:/bin", "HOME": "/tmp/opencode"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=30, check=False,
    )
    require(result.returncode == 0 and len(result.stdout) <= 4 * 1024 * 1024)
    return result.stdout


def read_source(root, name):
    require(source_path(name))
    path = root / name
    for parent in (path, *path.parents):
        require(not parent.is_symlink())
        if parent == root:
            break
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 4 * 1024 * 1024)
        with os.fdopen(fd, "rb", closefd=False) as source:
            data = source.read(4 * 1024 * 1024 + 1)
        require(len(data) == info.st_size)
        return data
    finally:
        os.close(fd)


def fingerprint(sources, head):
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None)
    rows = [dict(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
            for name, data in sorted(sources.items())]
    metadata = dict(base=BASELINE, head=head, files=rows)
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest(), metadata


def tracked_sources(revision):
    paths = set()
    for row in git("ls-tree", "-r", "-z", revision).split(b"\0"):
        if not row:
            continue
        header, name = row.split(b"\t", 1)
        name = name.decode("utf-8", "strict")
        if source_path(name):
            require(header.split()[0] in (b"100644", b"100755"))
            paths.add(name)
    return paths


def capture():
    head = git("rev-parse", "HEAD").strip().decode("ascii")
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None)
    git("merge-base", "--is-ancestor", BASELINE, CHECKPOINT)
    git("merge-base", "--is-ancestor", CHECKPOINT, head)
    changed = git("diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                  "--name-only", "-z", CHECKPOINT, head).split(b"\0")
    require(all(name.decode("utf-8", "strict") in REPAIR_PATHS for name in changed if name))
    baseline_paths, current_paths = tracked_sources(BASELINE), tracked_sources(head)
    paths = baseline_paths | set(NEW_INPUTS)
    require(baseline_paths <= current_paths <= paths)
    sources = {name: read_source(ROOT, name) for name in sorted(paths)}
    require(sum(map(len, sources.values())) <= 64 * 1024 * 1024)
    # Only declared new candidate/test inputs are admitted. Missing future native
    # code must not silently fall back to baseline or disappear from the fingerprint.
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    require(all(not source_path(name.decode()) or name.decode() in NEW_INPUTS
                for name in untracked if name))
    # Staging an undeclared new source must not hide it from the untracked check.
    indexed = git("ls-files", "--cached", "-z").split(b"\0")
    require(all(not source_path(name.decode()) or name.decode() in paths
                for name in indexed if name))
    require(git("rev-parse", "HEAD").strip().decode("ascii") == head)
    return sources, head


def freeze(destination, sources, metadata):
    destination.mkdir(mode=0o700)
    for name, data in sorted(sources.items()):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        path.write_bytes(data)
        path.chmod(0o444)
    (destination / MANIFEST).write_text(json.dumps(metadata, sort_keys=True), encoding="ascii")
    (destination / MANIFEST).chmod(0o444)


def check_frozen(expected):
    require(ROOT != Path("/home/kemal/projects/impostr") and ROOT.name == "source"
            and ROOT.parent.parent == Path("/tmp/opencode")
            and stat.S_IMODE(ROOT.parent.stat().st_mode) == 0o700
            and ROOT.stat().st_uid == ROOT.stat().st_gid == 1000)
    metadata = json.loads((ROOT / MANIFEST).read_bytes())
    require(set(metadata) == {"base", "head", "files"} and metadata["base"] == BASELINE)
    names = [row["path"] for row in metadata["files"]]
    require(names == sorted(set(names)) and set(NEW_INPUTS) <= set(names))
    # Extra modules/build inputs could change execution without changing a listed
    # file. The snapshot contains only captured files and its bound manifest.
    entries = list(ROOT.rglob("*"))
    require(not any(path.is_symlink() for path in entries))
    require({path.relative_to(ROOT).as_posix() for path in entries if not path.is_dir()}
            == set(names) | {MANIFEST})
    sources = {name: read_source(ROOT, name) for name in names}
    actual, rebuilt = fingerprint(sources, metadata["head"])
    require(rebuilt == metadata and actual == expected)


class ResultOutput(CheckOutput):
    """Require actual pytest execution; skips/errors/empty successful commands fail."""
    def __init__(self, expected=None):
        super().__init__("pytest", check_files=API_FILES)
        self.expected = expected
        self.passes = 0
        self.skipped = False

    def line(self, line):
        super().line(line)
        match = re.search(rb"\b([0-9]+) passed\b", line)
        if match:
            self.passes = int(match.group(1))
        if re.search(rb"\b[1-9][0-9]* skipped\b", line):
            self.skipped = True
        if b"IMP025_STAGE " in line:
            value = line.partition(b"IMP025_STAGE ")[2].decode("ascii", "ignore")
            if value in {"pg_preservation", "pg_legacy_fence", "pg_send_schema", "pg_capture_delete"}:
                report("postgres", "observed", category=value)

    def finish(self):
        require(self.passes > 0 and not self.skipped and not self.reasons
                and (self.expected is None or self.passes == self.expected))


class SafeOutput(CheckOutput):
    def __init__(self):
        super().__init__("snapshot")
        self.success = False

    def line(self, line):
        if len(line) > 4096 or not line.startswith(b"{"):
            return
        try:
            row = json.loads(line)
            check, status = row["check"], row["status"]
            require(check in STAGES or check.startswith("cleanup_") or check in {
                "owned_cleanup", "owned_fixture", "ordinary_connection_phase"})
            require(status in {"started", "prepared", "passed", "failed", "observed"})
            # Child metadata is never forwarded. Fixed child phase/category names
            # only; raw private output (including generated login) cannot survive.
            safe = {}
            if row.get("phase") in STAGES:
                safe["phase"] = row["phase"]
            if row.get("category") in {"operation", "assertion", "database", "filesystem",
                    "pg_preservation", "pg_legacy_fence", "pg_send_schema", "pg_capture_delete",
                    "tests_failed", "test_errors", "test_import_error", "format_mismatch",
                    "lint_findings", "lint_diagnostic_unavailable", "type_errors"}:
                safe["category"] = row["category"]
            if check == "native_diagnostic":
                require(row.get("operation") in NATIVE_OPERATIONS
                        and row.get("category") in NATIVE_CATEGORIES)
                safe.update(operation=row["operation"], category=row["category"])
                if row.get("reason") in FAILURE_REASONS:
                    safe["reason"] = row["reason"]
            if check in {"api_lint", "api_format"} and "file" in row:
                require(row["file"] in API_FILES and isinstance(row.get("code"), str)
                        and (row["code"] == "format_mismatch"
                             or re.fullmatch(r"(?:E|F|I|UP|B)[0-9]{3}", row["code"])))
                safe.update(file=row["file"], code=row["code"])
                if "line" in row:
                    require(type(row["line"]) is int and 1 <= row["line"] <= 10000)
                    safe["line"] = row["line"]
            if check.startswith("cleanup_"):
                require(check in {"cleanup_broker_children", "cleanup_compose_down",
                    "cleanup_container_inventory", "cleanup_volume_inventory", "cleanup_network_inventory",
                    "cleanup_image_inventory", "cleanup_channel_directory", "cleanup_generated_inputs"})
            report(check, status, **safe)
            if check == "imp025_verification" and status == "passed":
                self.success = True
        except Exception:
            raise Unavailable() from None

    def finish(self):
        require(self.success)


class Receiver:
    """No listener. Trusted HTTPS transport's connection callable, not an ACK seam."""
    def __init__(self):
        self.originals = {}
        self.observations = []
        self.lock = threading.Lock()

    def transport(self, metadata):
        from imp024_operator_transport import PlanningHTTPSInference, explicit_contract
        receiver = self

        class NativeTransport(PlanningHTTPSInference):
            def __init__(self):
                # Intentionally skip HTTPSInference.__init__: NO DNS or TLS.
                self.contract = explicit_contract("https://synthetic.example.invalid",
                    "/openai/v1/responses", "none", "synthetic")
                self.acquire("generated-synthetic-key-not-real")

            def events(self, data, cancelled, deadline, *, submission=None):
                native_require(submission is not None and submission.ledger.native,
                               "transport_submission", "identity")
                self.connection = lambda: CapturedConnection(receiver, metadata, submission)
                with native_probe("transport_events"):
                    yield from super().events(data, cancelled, deadline, submission=submission)

            def normalize_planning(self, response, data, cancelled, deadline):
                with native_probe("transport_normalize"):
                    yield from super().normalize_planning(response, data, cancelled, deadline)

        return NativeTransport()

    def inspect(self, metadata, submission, encoded):
        from app.chat_protocol import PDF_DATA_PREFIX, occurrence_filename, MAX_PDF_FRAME, native_occurrence_manifest
        with native_probe("receiver_json"):
            data = json.loads(encoded)
            native_require(data["model"] == "synthetic" and data["store"] is False and data["stream"] is True,
                           "receiver_envelope", "identity")
            parts = [part for item in data["input"] if isinstance(item.get("content"), list)
                     for part in item["content"] if part.get("type") == "input_file"]
        # Turn.run passes binary-free metadata, not the native inline envelope.
        with native_probe("receiver_manifest"):
            manifest = native_occurrence_manifest(metadata)
        native_require(len(parts) == len(manifest) and len(encoded) <= MAX_PDF_FRAME,
                       "receiver_manifest", "count")
        for part, expected in zip(parts, manifest):
            native_require(set(part) == {"type", "filename", "file_data"}
                           and part["filename"] == occurrence_filename(expected)
                           and part["file_data"].startswith(PDF_DATA_PREFIX), "receiver_part", "identity")
            with native_probe("receiver_decode"):
                decoded = base64.b64decode(part["file_data"][len(PDF_DATA_PREFIX):], validate=True)
            with native_probe("receiver_original"):
                original = self.originals[expected["original_sha256"]]
            native_require(decoded == original and len(decoded) == expected["original_size"]
                           and hashlib.sha256(decoded).hexdigest() == expected["original_sha256"],
                           "receiver_bytes", "identity")
        tools = [item for item in data["input"] if item.get("type") == "function_call_output"]
        if metadata["prompt"] == "SYNTHETIC NATIVE TOOL" and tools:
            with native_probe("receiver_tool"):
                native_require(len(tools) == 1 and tools[0]["call_id"] == "call_native_read"
                               and metadata["documents"]["PROJECT.md"]["content"].strip().splitlines()[0]
                                   in tools[0]["output"], "receiver_tool", "identity")
        observation = dict(turn_id=submission.row["turn_id"], call=submission.row["call"],
            request_sha256=hashlib.sha256(encoded).hexdigest(), request_size=len(encoded),
            manifest=manifest, followup=bool(tools),
            authorization_id=submission.row.get("authorization_id"),
            rendered_sha256=submission.row.get("rendered_sha256"),
            manifest_sha256=submission.row.get("manifest_sha256"))
        native_require(observation["request_sha256"] == submission.row["request_sha256"]
                       and observation["request_size"] == submission.row["request_size"],
                       "receiver_binding", "binding")
        with self.lock:
            self.observations.append(observation)  # Metadata only, never request bodies.
        return bool(tools)


class CapturedConnection:
    def __init__(self, receiver, metadata, submission):
        self.receiver, self.metadata, self.submission = receiver, metadata, submission
        self.followup = None

    def request(self, method, route, encoded, headers):
        native_require(method == "POST" and route == "/openai/v1/responses"
                       and headers["api-key"] == "generated-synthetic-key-not-real", "receiver_route", "identity")
        self.followup = self.receiver.inspect(self.metadata, self.submission, encoded)

    def getresponse(self):
        from imp005_verify import EarlyResponse
        from imp024_inference import native_response
        prompt = self.metadata["prompt"]
        if prompt == "SYNTHETIC NATIVE TOOL" and not self.followup:
            calls = [dict(type="function_call", name="read", call_id="call_native_read",
                          arguments=json.dumps({"filePath": "/project/PROJECT.md"}))]
            frames = native_response(calls=calls)
        else:
            frames = native_response("Synthetic native assistant quotation.")

        class Response(EarlyResponse):
            status = 200

            def getheader(self, name, default=None):
                return {"Content-Type": "text/event-stream"}.get(name, default)

            def getheaders(self):
                return [("Content-Type", "text/event-stream")]

            def close(self):
                with native_probe("receiver_close"):
                    # EarlyResponse wraps a LIST iterator, not a generator. Closing
                    # it must release frames without raising after a successful send.
                    close = getattr(self.frames, "close", None)
                    self.frames = iter(())
                    if close is not None:
                        close()

        with native_probe("receiver_response"):
            return Response(frames)

    def abort(self):
        pass

    def close(self):
        pass


class Product:
    def __init__(self, origin, login, receiver, stage):
        from imp024_http import Client
        self.client = Client(origin, timeout=10)
        self.login, self.receiver = login, receiver
        self.stage = stage
        self.base = None

    def request(self, method, path, payload=None, expected=200):
        with native_probe("product_request"):
            response = self.client.request(method, path, json=payload, headers={
                "Origin": self.client.base_url, "X-CSRF-Token": self.client.cookies.get("impostr_csrf", "")})
        native_require(response.status_code in expected if isinstance(expected, tuple)
                       else response.status_code == expected, "product_request", "http_status")
        return response

    def upload(self, body, expected=201):
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", self.client.port, timeout=30)
        try:
            connection.request("POST", self.base + "/attachments/upload?filename=synthetic.pdf", body, {
                "Origin": self.client.base_url, "Content-Type": "application/pdf",
                "X-CSRF-Token": self.client.cookies.get("impostr_csrf", ""),
                "Cookie": "; ".join(name + "=" + self.client.cookies.get(name, "")
                                    for name in ("impostr_session", "impostr_csrf")),
            })
            response = connection.getresponse()
            raw = response.read(8193)
            native_require(response.status == expected and len(raw) <= 8192, "upload_response", "http_status")
            if expected != 201:
                return None
            row = json.loads(raw)
            native_require(row["status"] == "stored" and row["native_available"] is True
                           and row["original_size"] == len(body)
                           and row["original_sha256"] == hashlib.sha256(body).hexdigest(), "upload_identity", "identity")
            self.receiver.originals[row["original_sha256"]] = body
            return dict(attachment_id=row["id"], expected_sha256=row["original_sha256"])
        finally:
            connection.close()

    def send(self, prompt, selections=(), expected=202, request_id=None):
        import uuid
        return self.request("POST", self.base + "/turns", dict(request_id=request_id or str(uuid.uuid4()),
            prompt=prompt, selections=list(selections)), expected).json()

    def wait(self, turn_id):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            with native_probe("wait_history"):
                history = self.request("GET", self.base).json()
                turn = next((item for item in history["turns"] if item["id"] == turn_id), None)
            native_require(turn is not None, "wait_turn", "missing_turn")
            if turn["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                if turn["state"] != "completed":
                    category = "turn_" + turn["state"]
                    native_diagnostic("wait_terminal", category)
                    # Reasons are durable EVENTS, not fields of the turn receipt.
                    # The first-turn slice has at most 256 events (64 per page).
                    # This bounded read is diagnostic only, never a send/reply retry.
                    with native_probe("wait_failure_events"):
                        after = 0
                        for _ in range(5):
                            page = self.request("GET", self.base + "/events?after=" + str(after)).json()
                            reason = next((row["data"].get("reason") for row in page["events"]
                                if row["turn_id"] == turn_id and row["type"] == "failed"
                                and row["data"].get("reason") in FAILURE_REASONS), None)
                            if reason is not None:
                                native_diagnostic("wait_failure_events", category, reason=reason)
                                break
                            if not page["events"]:
                                break
                            native_require(type(page["after"]) is int and page["after"] > after,
                                           "wait_failure_events", "shape")
                            after = page["after"]
                    raise Unavailable()
                native_require(turn["submission"]["status"] == "sent", "wait_submission", "submission_not_sent")
                self.receipt(turn)
                return turn
            time.sleep(0.1)
        native_require(False, "wait_deadline", "timeout")

    def receipt(self, turn):
        from app.chat_protocol import NATIVE_PDF_REFERENCE
        receipt = turn["submission"]
        native_require(receipt["reference_kind"] == NATIVE_PDF_REFERENCE, "receipt_kind", "identity")
        observations = [row for row in self.receiver.observations if row["turn_id"] == turn["id"]]
        native_require(len(observations) == len(receipt["calls"]) > 0, "receipt_count", "count")
        for observed, call in zip(observations, receipt["calls"]):
            with native_probe("receipt_call"):
                native_require(call["status"] == "sent" and call["call"] == observed["call"]
                               and call["request_sha256"] == observed["request_sha256"]
                               and call["request_size"] == observed["request_size"]
                               and call["reference_kind"] == NATIVE_PDF_REFERENCE
                               and call["authorization_id"] == observed["authorization_id"]
                               and observed["authorization_id"] is not None
                               and receipt["rendered_sha256"] == observed["rendered_sha256"]
                               and receipt["manifest_sha256"] == observed["manifest_sha256"], "receipt_call", "binding")

    def start(self):
        csrf = self.request("GET", "/api/auth/csrf").json()["csrf_token"]
        reply = self.client.post("/api/auth/login", json=self.login,
            headers={"Origin": self.client.base_url, "X-CSRF-Token": csrf})
        require(reply.status_code == 200)
        self.login.clear()
        # Normal Member authorization, no test auth/session bypass.
        self.request("GET", "/api/admin/users", expected=403)
        project = self.request("POST", "/api/projects", {"name": "Synthetic native PDF"}, 201).json()["id"]
        self.chat = "/api/projects/" + project + "/chat"
        self.conversation()

    def conversation(self):
        conv = self.request("POST", self.chat, {"title": "Native proof"}, 201).json()["id"]
        self.base = self.chat + "/" + conv

    def main_flow(self):
        from imp017_fixtures import text_pdf
        self.stage("native_order")
        with native_probe("upload_first"):
            first = self.upload(text_pdf())
        with native_probe("upload_second"):
            second = self.upload(text_pdf().replace(b"Synthetic", b"Different"))
        ordered = [second, first, second]
        with native_probe("send_first"):
            started = self.send("SYNTHETIC NATIVE TOOL", ordered)
        turn = self.wait(started["id"])
        observed = [row for row in self.receiver.observations if row["turn_id"] == turn["id"]]
        native_require(len(observed) == 2 and observed[1]["followup"], "order_followup", "count")
        native_require([item["attachment_id"] for item in observed[0]["manifest"]]
                       == [item["attachment_id"] for item in ordered], "order_manifest", "identity")
        report("native_order", "passed")
        self.stage("native_history")
        continued = self.wait(self.send("SYNTHETIC NATIVE HISTORY")["id"])
        history = [row for row in self.receiver.observations if row["turn_id"] == continued["id"]]
        require(len(history) == 1 and [item["attachment_id"] for item in history[0]["manifest"]]
                == [item["attachment_id"] for item in ordered]
                and all(item["message_index"] == 0 for item in history[0]["manifest"]))
        report("native_history", "passed")
        # Exact idempotency includes ordered IDs/hashes, not a new dispatch.
        count = len(self.receiver.observations)
        replay = self.send("SYNTHETIC NATIVE TOOL", ordered, request_id=started["request_id"])
        require(replay["id"] == started["id"] and len(self.receiver.observations) == count)
        return ordered, turn

    def bound_flow(self):
        self.stage("native_bound")
        # Two distinct originals total 49,999,999 bytes. Real receiver admission
        # crosses the large JSON, shim, relay and final host serialization bounds.
        self.conversation()
        files = [self.upload(b"%PDF-1.7\n" + b"x" * (size - 15) + b"\n%%EOF")
                 for size in (24_999_999, 25_000_000)]
        turn = self.wait(self.send("SYNTHETIC NATIVE BOUND", files)["id"])
        observed = [row for row in self.receiver.observations if row["turn_id"] == turn["id"]]
        require(len(observed) == 1 and sum(item["original_size"] for item in observed[0]["manifest"])
                == 49_999_999 and observed[0]["request_size"] > 66_000_000)
        before = len(self.receiver.observations)
        self.send("SYNTHETIC NATIVE OVERFLOW", files, expected=422)  # History charged too.
        require(len(self.receiver.observations) == before)
        report("native_bound", "passed")

    def rejection_flow(self):
        self.stage("native_rejections")
        self.conversation()
        selected = self.upload(b"%PDF-synthetic rejected selection")
        before = len(self.receiver.observations)
        self.send("SYNTHETIC NATIVE ALTERED HASH", [dict(selected, expected_sha256="f" * 64)], expected=409)
        own_base = self.base
        self.conversation()
        self.send("SYNTHETIC NATIVE FOREIGN", [selected], expected=404)
        self.base = own_base
        path = self.base + "/attachments/" + selected["attachment_id"]
        self.request("DELETE", path, expected=204)
        self.send("SYNTHETIC NATIVE DELETED", [selected], expected=404)
        self.upload(b"%PDF-" + b"x" * (50_000_000 - 5), expected=413)
        require(len(self.receiver.observations) == before)
        report("native_rejections", "passed")

    def close(self):
        self.client.close()


class NativeVerify(Verify):
    def __init__(self, synthetic):
        super().__init__()
        self.synthetic = synthetic
        self.phase = "frozen_inputs"
        self.connection = self.runtime = self.product = None
        self.receiver = Receiver()

    def stage(self, name):
        require(name in STAGES)
        self.phase = name
        report(name, "started")

    def prepare(self):
        super().prepare()
        # Base synthetic chat overlay is deliberately omitted: no extractor or
        # fake text transport. API-only does not construct a worker/channel.
        self.base = self.base[:-2]
        from imp017_intake_verify import postgres_owner_overlay
        overlay = self.inputs / "native-checks.yaml"
        overlay.write_text(json.dumps({"services": {"api-integration-check": {"environment": {
            "IMPOSTR_TEST_CHAT_CHANNEL": "1", "IMPOSTR_TEST_CHAT_JOINED": "1", "IMPOSTR_TEST_NATIVE_PDF": "1"}}}}))
        self.base += ["-f", str(overlay)]
        self.owner_overlay = self.inputs / "native-owner.yaml"
        self.owner_overlay.write_text(postgres_owner_overlay(ROOT)
                                      + "      IMPOSTR_TEST_NATIVE_PDF: '1'\n")

    def stop_broker(self):
        from imp024_verify import reap_children
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        reap_children(self.active)
        if self.runtime is not None:
            self.runtime.close(clean=True)
            self.runtime = None

    def check(self, stage, *args, output=None, seconds=300):
        self.stage(stage)
        try:
            self.compose("run", "--rm", "api-check", *args, output=output, seconds=seconds)
        except Exception:
            reasons = sorted(getattr(output, "reasons", ()))
            report(stage, "failed", category=reasons[0] if reasons else "operation")
            # Fixed lint/format filenames and codes from existing parsers only.
            for finding in getattr(output, "findings", ())[:16]:
                report(stage, "failed", **finding)
            raise
        report(stage, "passed")

    def run_native(self):
        import socket
        from imp005_connection import Connection, OwnedRuntime
        from imp024_operator_helper import MemberOutput
        self.stage("member")
        member = MemberOutput()
        self.compose("run", "--rm", "api-integration-check", "python", "-B",
                     "tests/imp024_operator_member.py", output=member)
        self.stage("broker")
        self.runtime = OwnedRuntime(self.inputs / "chat")
        self.connection = Connection(self.runtime, self.receiver.transport, mode="planning")
        self.connection.start()
        env = self.inputs / "fixture.env"
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        origin = "http://127.0.0.1:" + str(port)
        env.write_text(env.read_text().replace("APP_PORT=8080\n", f"APP_PORT={port}\n").replace(
            "IMPOSTR_PUBLIC_ORIGIN=http://127.0.0.1:8080\n", "IMPOSTR_PUBLIC_ORIGIN=" + origin + "\n")
            + "IMPOSTR_CHAT_CHANNEL_DIR=" + str(self.runtime.channel) + "\n")
        self.base += ["-f", str(ROOT / "compose.chat.yaml")]
        self.stage("api_start")
        self.compose("up", "-d", "--wait", "api", "frontdoor")
        self.product = Product(origin, member.login, self.receiver, self.stage)
        self.product.start()
        ordered, sent = self.product.main_flow()
        self.stage("native_outage")
        # Completed turns retain exact sent receipts after real API restart.
        prior_events = self.product.request("GET", self.product.base + "/events").json()["events"]
        prior_requests = len(self.receiver.observations)
        self.compose("restart", "api")
        self.compose("up", "-d", "--wait", "api")
        self.product.wait(sent["id"])
        require(self.product.request("GET", self.product.base + "/events").json()["events"] == prior_events
                and len(self.receiver.observations) == prior_requests)
        retired = self.connection.broker
        self.connection.close()
        require(all(turn.stopped.is_set() and turn.payload is None and turn.scratch is None
                    and turn.relay is None and turn.process is None for turn in retired.turns.values()))
        del retired
        self.connection = None  # Keep the channel inode/broker epoch; no new turn resubmit.
        attachment_path = self.product.base + "/attachments/" + ordered[0]["attachment_id"]
        self.product.request("DELETE", attachment_path, expected=202)
        self.product.send("SYNTHETIC NATIVE FENCED", expected=409)
        self.product.request("GET", attachment_path + "/raw", expected=404)
        self.connection = Connection(self.runtime, self.receiver.transport, mode="planning")
        self.connection.start()
        self.stage("native_purge")
        deadline = time.monotonic() + 130
        while time.monotonic() < deadline:
            result = self.product.request("DELETE", attachment_path, expected=(202, 204))
            if result.status_code == 204:
                break
            time.sleep(0.1)
        else:
            raise Unavailable()
        old = self.product.request("GET", self.product.base).json()
        original = next(row for row in old["turns"] if row["id"] == sent["id"])
        require(original["submission"]["status"] == "sent" and original["prompt"] == "SYNTHETIC NATIVE TOOL")
        # New broker contains only metadata tombstones for the purged turn; owned
        # scratch must have no turn/session/workspace content after the restart.
        require(set(self.runtime.scratch.iterdir()) == {self.runtime.scratch / "connection.lock"})
        require(sent["id"] in self.connection.broker.aborted_unknown)
        for turn in self.connection.broker.turns.values():
            require(turn.purged and turn.payload is None and not turn.events)
        events = self.product.request("GET", self.product.base + "/events").json()["events"]
        require(events == prior_events)
        require(any(row["data"].get("text") == "Synthetic native assistant quotation."
                    for row in events))
        before = len(self.receiver.observations)
        self.product.wait(sent["id"])
        require(len(self.receiver.observations) == before)
        future = self.product.wait(self.product.send("SYNTHETIC NATIVE DELETED HISTORY")["id"])
        files = [item for row in self.receiver.observations if row["turn_id"] == future["id"]
                 for item in row["manifest"]]
        require(files and all(item["attachment_id"] != ordered[0]["attachment_id"] for item in files))
        unavailable = [item for turn in old["turns"] for item in turn["references"]
                       if item["attachment_id"] == ordered[0]["attachment_id"]]
        require(unavailable and all(item["availability"] == "unavailable" for item in unavailable))
        report("native_outage", "passed")
        self.product.rejection_flow()
        self.product.bound_flow()
        require(self.connection.thread.is_alive() and not self.connection.failed.is_set())
        report("native_complete", "passed")

    def cleanup(self):
        if self.base is not None and hasattr(self, "owner_overlay"):
            self.base += ["-f", str(self.owner_overlay)]
        closed = True
        try:
            if self.product is not None:
                self.product.close()
        except Exception:
            closed = False
        finally:
            self.product = None
        return super().cleanup() and closed

    def run(self):
        passed = False
        try:
            self.prepare()
            self.stage("build")
            services = ("db", "api", "api-check", "api-integration-check")
            self.compose("build", *services, *(("frontdoor",) if self.synthetic else ()), seconds=600)
            self.stage("database")
            self.compose("up", "-d", "--wait", "db")
            self.stage("postgres")
            self.compose_used = True
            self.command(self.base + ["-f", str(self.owner_overlay), "run", "--build", "--rm",
                "api-integration-owner-check", "python", "-m", "pytest", "-p", "no:cacheprovider",
                "--tb=no", "--show-capture=no", "--color=no", "-s", *PG_TESTS],
                seconds=360, output=ResultOutput(expected=2))
            self.stage("migration")
            self.compose("run", "--rm", "api", "alembic", "upgrade", "head")
            self.check("api_tests", "python", "-m", "pytest", "-p", "no:cacheprovider",
                "--tb=no", "--show-capture=no", "--color=no", *API_TESTS, output=ResultOutput())
            self.check("api_lint", "ruff", "check", "--output-format", "json", *API_FILES,
                output=RuffJsonOutput(check_files=API_FILES))
            self.check("api_format", "ruff", "format", "--check", *API_FILES,
                output=CheckOutput("ruff_format", check_files=API_FILES))
            self.check("api_types", "mypy", "app", output=CheckOutput("mypy", check_files=API_FILES))
            if self.synthetic:
                self.run_native()
            passed = True
        except (Exception, KeyboardInterrupt) as error:
            category = ("assertion" if isinstance(error, AssertionError) else
                        "filesystem" if isinstance(error, OSError) else "operation")
            report("imp025_verification", "failed", phase=self.phase, category=category)
        finally:
            passed = self.cleanup() and passed
        report("imp025_verification", "passed" if passed else "failed")
        return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--api-only", action="store_true")
    mode.add_argument("--synthetic", action="store_true")
    parser.add_argument("--reviewed-harness", action="store_true")
    parser.add_argument("--fingerprint")
    parser.add_argument("--frozen", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.preflight:
        if args.reviewed_harness or args.fingerprint or args.frozen:
            parser.error("preflight forbids execution flags")
    elif not args.reviewed_harness or not re.fullmatch(r"[0-9a-f]{64}", args.fingerprint or ""):
        parser.error("execution requires reviewed harness and exact fingerprint")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    parent = None
    try:
        if args.frozen:
            check_frozen(args.fingerprint)
            return NativeVerify(args.synthetic).run()
        sources, head = capture()
        actual, metadata = fingerprint(sources, head)
        if args.preflight:
            report("preflight", "passed", baseline=BASELINE, head=head, fingerprint=actual, files=len(sources),
                   boundary_executed=False)
            return 0
        require(actual == args.fingerprint)
        parent = Verify()
        parent.prepare()
        snapshot = parent.inputs / "source"
        freeze(snapshot, sources, metadata)
        require(fingerprint(*capture())[0] == actual)  # Concurrent review/source drift rejects.
        parent.command(["/usr/bin/python3", "-I", "-B", str(snapshot / "scripts/imp025_verify.py"),
            "--synthetic" if args.synthetic else "--api-only", "--reviewed-harness", "--fingerprint", actual,
            "--frozen"], seconds=1800, output=SafeOutput())
        return 0
    except (Exception, KeyboardInterrupt):
        report("snapshot_execution", "failed", category="operation")
        return 1
    finally:
        if parent is not None and not parent.cleanup():
            # Cleanup failure is never hidden by a successful return above.
            raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
