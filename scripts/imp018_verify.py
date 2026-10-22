"""COORDINATOR ONLY: reviewed IMP-018 API gates and synthetic PDF/chat proof.

--api-only performs pinned API/migration/fresh-PostgreSQL/static checks without
starting a product runtime. --full additionally reconstructs only the unchanged,
validated extractor image when absent, starts the owned local synthetic stack,
and proves the real PDF lifecycle through the ordinary chat broker/inference seam.
Never reads checkout .env or private/operator inputs. Captured test output is
bounded and projected to fixed diagnostics; no raw output or PDF text is emitted.
The one fixed synthetic test's format diff is emitted only after source/comment/AST validation.
Independent review is required before either mode; full mode is boundary execution.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import tokenize
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))

from imp005_verify import EarlyResponse, NormalVerify  # noqa: E402
from imp017_intake_verify import POSTGRES_OWNER_SERVICE  # noqa: E402
from imp017_lifecycle_verify import (  # noqa: E402
    LifecycleVerify,
    VERIFIED_BUILD_SHA256,
)
from imp024_operator_helper import MemberOutput  # noqa: E402
from imp024_operator_transport import PlanningHTTPSInference, explicit_contract  # noqa: E402
from imp024_verify import (  # noqa: E402
    CheckOutput,
    ROOT as VERIFY_ROOT,
    Unavailable,
    Verify,
    report,
    require,
    RuffJsonOutput,
)
from app.chat_protocol import (  # noqa: E402
    digest,
    has_pdf_references,
    manifest_digest,
    resolved_prompt_text,
)
from imp018_receipts import native_user_text  # noqa: E402
from imp024_broker import SyntheticProduct  # noqa: E402
from imp024_inference import native_response  # noqa: E402

BASELINE = "4d46a4047678e44b2d37bd8904dca7b636a6c0fd"
HEAD_EXPECTATION = b"4d46a4047678e44b2d37bd8904dca7b636a6c0fd\n"
VERIFY_SOURCE_SHA256 = "68aa8a836da423c71b6e70498b48b6257526ef41534f2e05d4d7475b0b532126"
API_FILES = (
    "app/attachments.py",
    "app/attachment_cleanup.py",
    "app/chat.py",
    "app/chat_dispatch.py",
    "app/chat_protocol.py",
    "app/chat_receipts.py",
    "app/chat_references.py",
    "app/chat_state.py",
    "app/models.py",
    "migrations/versions/20261002_0010_pdf_turn_selections.py",
    "tests/imp018_scoped_server.py",
    "tests/imp018_pytest_diagnostic.py",
    "tests/conftest.py",
    "tests/imp024_http.py",
    "tests/test_attachments_migration.py",
    "tests/test_chat.py",
    "tests/test_chat_postgres.py",
    "tests/test_chat_receipts.py",
    "tests/test_chat_references.py",
    "tests/test_chat_references_migration.py",
)
FOCUSED_TESTS = (
    "tests/test_attachments.py",
    "tests/test_attachments_migration.py",
    "tests/test_chat.py",
    "tests/test_chat_receipts.py",
    "tests/test_chat_references.py",
    "tests/test_chat_references_migration.py",
)
PG_TESTS = ("tests/test_attachments_postgres.py", "tests/test_chat_postgres.py")
EXPECTED_PASSES = 3  # One attachment migration test + two joined PostgreSQL chat tests.
PG_TEST_STAGES = {
    (
        "tests/test_chat_postgres.py",
        "test_postgres_chat_migration_preserves_preexisting_identity_and_documents",
    ): "pg_migration_preservation",
    (
        "tests/test_chat_postgres.py",
        "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads",
    ): "pg_turn_reservation_concurrency",
}
PG_TEST_SUBSTAGES = {
    (
        "tests/test_chat_postgres.py",
        "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads",
    ): frozenset(
        {
            "submit_idempotency", "leaseclaim", "otherwriter", "abort", "upload",
            "capture_delete_race", "capture_integrity", "purge_cleanup",
        }
    ),
}
PG_STAGES = frozenset(
    {
        "schema_create", "preservation_base_migration", "preservation_seed",
        "preservation_snapshot", "preservation_upgrade", "preservation_history",
        "preservation_original", "preservation_retained_downgrade",
        "preservation_constraint_size_cap", "preservation_constraint_size_match",
        "preservation_constraint_failed_blob", "preservation_constraint_ready",
        "preservation_constraint_lease", "preservation_delete",
        "preservation_empty_downgrade", "preservation_reupgrade", "schema_types",
        "schema_conversation_fk", "api_account", "api_startup", "api_setup",
        "roundtrip_upload", "roundtrip_stored_original", "roundtrip_raw",
        "roundtrip_pending_metadata", "roundtrip_derivative_commit", "roundtrip_preview",
        "roundtrip_delete", "overcap_upload", "overcap_discarded_blob", "overcap_metadata",
        "overcap_recovery", "api_shutdown", "owned_cleanup", "unknown",
        *next(iter(PG_TEST_SUBSTAGES.values())),
    }
)
PG_CATEGORIES = frozenset(
    {"assertion", "expected_exception_missing", "integrity", "database", "filesystem", "unexpected"}
)
CAPTURE_DELETE_STATUSES = frozenset({
    200, 201, 202, 204, 400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 503,
})
CAPTURE_DELETE_PAIRS = {
    (202, 409): "captured_then_conflict",
    (404, 204): "deleted_then_notfound",
    (409, 204): "fenced_then_conflict",
    (409, 202): "queued_cleanup",
}
PINNED_SOURCES: dict[str, str] = {
    "api/tests/imp018_pytest_diagnostic.py": "e0cb494e912cf6505c324e9f02826ff2bb5f5549fd1b4abc085166c40b7b0905",
    "api/tests/conftest.py": "5521bb75de2a56298f9d056103cc1c1dcfdeaa14f7514727829c7a6792e8f266",
    "api/app/attachments.py": "75210563c69d277190d3e41088595245f10cfe7a8a8ab0fc9b945eee03c9486e",
    "api/app/attachment_cleanup.py": "23d31e4b1f505deb78ff9ad7d2ae12f593bd4f451d415e40f114e301f4f15e99",
    "api/app/chat.py": "a3455a36f086bc7dbdfbcc83b483e04d75c3223cb1e0a625af45018e4caf37f2",
    "api/app/chat_dispatch.py": "08db9ede0e33673371df326f10d7456a638e8479365a4595125faff29ec52266",
    "api/app/chat_protocol.py": "5709c90e3f2502d57310614303b9d001721bf93990dc50a14c69b0ae5698c0e6",
    "api/app/chat_receipts.py": "abba9343411eb62288274d1036735cdd4066dfe9208822a8c5f20bca0826cba4",
    "api/app/chat_references.py": "0af105cf20f221fad8d877ad55a57e190449c708d13d6c2130946671deb6ab36",
    "api/app/chat_state.py": "4656545d3c4b9d931141ded0333307cc050b2da51486c34c9f7b1de14d2c4468",
    "api/app/models.py": "f323c8f5db6f9563c915e811dd13af79e34cac9f11c14372c30c183984805dcb",
    "api/migrations/versions/20261002_0010_pdf_turn_selections.py": "6b9a04968ffc5a95cd6367a27faf79de8b84f6d0aa6bed8cdba3dc751b5baa2a",
    "api/tests/imp018_scoped_server.py": "0ce9f16deef9d108365cd3d32566a6c57c55571e0b8342e43a0dc0b6371c1d77",
    "api/tests/test_attachments.py": "623d722333a4c38205246462ed2ebcc274e8017ce2c0dcd28eb8035eacb440fd",
    "api/tests/imp024_http.py": "79bfb73fd2d26cfbfad565c7f3f6c1d1b0addb008a20f9a0c5e988328e4e5936",
    "api/tests/test_attachments_migration.py": "5531fb2adab91a799781f7b0bb5ba9fdbf4e7356c132378d5cf253e5df170e12",
    "api/tests/test_chat.py": "f9d7ee4e195b56e607eda094a061ff51c9428e47d7397e2834c9e3c236a0bc49",
    "api/tests/test_chat_postgres.py": "f00ce6466d8931c6942ab6ac43aca4c4ecfe0d27bbdb078f5133afcae04dea61",
    "api/tests/test_chat_receipts.py": "6e61cfe2c3ae8365f98990a8f60b463cfd40d882b233f24bfbc54ee9132b9987",
    "api/tests/test_chat_references.py": "a7b2ac22c80984ce498e0aa5cea74ca59677b175ff6f2aa5c485bcb757ddb23f",
    "api/tests/test_chat_references_migration.py": "8e84e118cc9752e81e80d79feded2de4185a471f42aaf907ed299f312da233b7",
    "scripts/imp002_relay.py": "f30e4381463e40e7f6406b60b747c81dfaee12f332363248a23bfc52c7fc838b",
    "scripts/imp005_verify.py": "aa8b4df38214478d28d2b1143ad0ca84e3185a28b3f4ce7e2981845820098ade",
    "scripts/imp018_receipts.py": "002087c0f504b0770b26d9f5fea41048eae3d1941250ac2bb575a9e02c0311ed",
    "scripts/imp024_broker.py": "7325f627994c2a30a22184a6350619b747085668fee801fc93dbfea7813c1a49",
    "scripts/imp024_inference.py": "f8005669fd5049f23294c0868de7f9318a2225b08f272d5fd9618b720fde7e9c",
    "scripts/imp024_operator_transport.py": "15c081651023411db9ad4d26862883224e94111af5ae09918084a81defb46b75",
    "scripts/imp024_product_worker.py": "750eaccfc3b8d12544d24000989c4e520d0743fdc5afcf018fcfa1137426267c",
    "scripts/test_imp018_receipts.py": "55130acfd5ea94e5b11d495b6516ea2b42a7e5142d249f236a1aa7644b5cf0d5",
    "scripts/test_imp018_references.py": "44378a7cceacafeb825afd27190d22fb38d97125d35e0f8b9d4b59eeadc7b29e",
    "scripts/test_imp018_verify.py": "3d873052ee9070cc15c9625f8903ea518b722ad8fe6cae65476ace57d7469f51",
}


REFERENCE_FORMAT_CAPTURE = '''\
import hashlib
import json
from pathlib import Path
import subprocess
import sys

source_match = False
returncode = None
stdout_bytes = stderr_bytes = 0
try:
    source = Path('/app/tests/test_chat_references.py').read_bytes()
    source_match = hashlib.sha256(source).hexdigest() == EXPECTED_SOURCE_HASH
    if source_match:
        result = subprocess.run(
            ['ruff', 'format', '--no-cache', '--stdin-filename',
             'tests/test_chat_references.py', '-'],
            input=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd='/app', timeout=20, check=False,
        )
        returncode = result.returncode
        stdout_bytes = min(len(result.stdout), 65537)
        stderr_bytes = min(len(result.stderr), 65537)
        if returncode == 0 and 0 < stdout_bytes <= 65536 and stderr_bytes <= 65536:
            sys.stdout.buffer.write(result.stdout)
            sys.stdout.buffer.flush()
            sys.exit(0)
except Exception:
    pass
print('IMPOSTR_IMP018_FORMAT_CAPTURE ' + json.dumps({
    'source_match': source_match, 'returncode': returncode,
    'stdout_bytes': stdout_bytes, 'stderr_bytes': stderr_bytes,
}, separators=(',', ':')))
'''.replace('EXPECTED_SOURCE_HASH', repr(PINNED_SOURCES['api/tests/test_chat_references.py']))


def require_source_mapping() -> None:
    require(ROOT == VERIFY_ROOT)
    own_source = (ROOT / "scripts/imp018_verify.py").read_bytes()
    marker = b'VERIFY_SOURCE_SHA256 = "' + VERIFY_SOURCE_SHA256.encode("ascii") + b'"'
    require(own_source.count(marker) == 1)
    canonical = own_source.replace(
        marker,
        b'VERIFY_SOURCE_SHA256 = "' + b"0" * 64 + b'"',
        1,
    )
    require(hashlib.sha256(canonical).hexdigest() == VERIFY_SOURCE_SHA256)
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=10, check=False,
    )
    require(process.returncode == 0 and process.stdout == HEAD_EXPECTATION)
    require(len(PINNED_SOURCES) == 31)
    for relative, expected in PINNED_SOURCES.items():
        path = ROOT / relative
        require(not path.is_symlink() and path.is_file())
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected)
    report("exact_source_mapping", "passed", baseline=BASELINE,
           files=len(PINNED_SOURCES))


class ReferenceFormatDiffOutput:
    """Validate fixed-test formatted stdout and generate a source-only diff locally."""

    stdout_only = True
    FILE = "tests/test_chat_references.py"
    MAX_BYTES = 64 * 1024
    CAPTURE_MARKER = b"IMPOSTR_IMP018_FORMAT_CAPTURE "

    def __init__(self):
        self.buffer = bytearray()
        self.path = ROOT / "api" / self.FILE
        self.source = self.path.read_bytes()
        require(hashlib.sha256(self.source).hexdigest() == PINNED_SOURCES["api/" + self.FILE])
        self.diff = None
        self.reason = "command_incomplete"
        self.shape = None
        self.capture = None

    def feed(self, block):
        if len(self.buffer) + len(block) > self.MAX_BYTES:
            self.reason = "output_limit"
            self.buffer.clear()
            raise Unavailable()
        self.buffer.extend(block)

    @staticmethod
    def source_shape(source):
        crlf = source.count(b"\r\n")
        return {
            "bytes": len(source),
            "empty": not source,
            "terminal_lf": source.endswith(b"\n"),
            "crlf": crlf,
            "bare_cr": source.count(b"\r") - crlf,
            "bare_lf": source.count(b"\n") - crlf,
            "nul": b"\x00" in source,
        }

    @staticmethod
    def source_comments(source):
        # AST equality covers names, literal values, operators and grouping, while
        # allowing Ruff's trailing commas/quote normalization. Comments aren't in
        # the AST: require their exact ordered text to prevent arbitrary injection.
        return [
            token.string
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.COMMENT
        ]

    def finish(self):
        try:
            self.shape = self.source_shape(self.buffer)
            self.reason = "source_drift"
            require(self.path.read_bytes() == self.source)  # Reject concurrent source drift.
            if self.buffer.startswith(self.CAPTURE_MARKER):
                self.reason = "capture_diagnostic_invalid"
                value = json.loads(bytes(self.buffer[len(self.CAPTURE_MARKER):]))
                require(type(value) is dict and set(value) == {
                    "source_match", "returncode", "stdout_bytes", "stderr_bytes",
                })
                require(type(value["source_match"]) is bool)
                require(value["returncode"] is None or (
                    type(value["returncode"]) is int and -255 <= value["returncode"] <= 255
                ))
                require(all(type(value[key]) is int and 0 <= value[key] <= self.MAX_BYTES + 1
                            for key in ("stdout_bytes", "stderr_bytes")))
                self.capture = value
                self.reason = "formatter_capture"
                raise Unavailable()
            self.reason = "source_encoding"
            after = self.buffer.decode("utf-8", errors="strict")
            before = self.source.decode("utf-8", errors="strict")
            self.reason = "source_shape"
            require(
                self.shape["terminal_lf"] and not self.shape["nul"]
                and self.shape["bare_cr"] == 0
                and not (self.shape["crlf"] and self.shape["bare_lf"])
            )
            # Accept uniform LF or CRLF only, normalizing representation for the
            # AST/comments/local diff. The original byte fingerprint stays exact.
            after = after.replace("\r\n", "\n")
            before = before.replace("\r\n", "\n")
            self.reason = "unchanged_source"
            require(after != before)
            self.reason = "python_syntax"
            original_ast, proposed_ast = ast.parse(before), ast.parse(after)
            self.reason = "ast_changed"
            require(ast.dump(original_ast) == ast.dump(proposed_ast))
            self.reason = "comments_changed"
            require(self.source_comments(before) == self.source_comments(after))
            # No runtime diff headers are accepted or forwarded. Only reconstruct
            # from the pinned original and the complete validated formatted source.
            self.diff = "".join(difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=self.FILE, tofile=self.FILE,
            ))
            self.reason = None
        except Exception:
            self.diff = None
            raise Unavailable() from None
        finally:
            self.buffer.clear()


class HeadOutput:
    """Accept the exact current Alembic head while ignoring ancillary log lines."""

    def __init__(self):
        self.buffer = bytearray()
        self.found = False

    def feed(self, block):
        self.buffer.extend(block)
        require(len(self.buffer) <= 64 * 1024)
        while b"\n" in self.buffer:
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer[:] = rest
            self.line(line.rstrip(b"\r"))

    def line(self, line):
        if line.strip() == b"20261002_0010 (head)":
            self.found = True

    def finish(self):
        if self.buffer:
            self.line(bytes(self.buffer).rstrip(b"\r"))
        require(self.found)
        self.buffer.clear()


class FocusedTestOutput(CheckOutput):
    """Accept exact fixed hook records; summaries are lower-priority fallbacks."""

    EXCEPTION_CATEGORIES = {
        "ImportError": "import",
        "ModuleNotFoundError": "import",
        "NameError": "name",
        "UnboundLocalError": "name",
        "AssertionError": "assertion",
        "IntegrityError": "db",
        "OperationalError": "db",
        "ProgrammingError": "db",
        "DatabaseError": "db",
        "DBAPIError": "db",
        "DataError": "db",
        "InterfaceError": "db",
        "SQLAlchemyError": "db",
        "NoResultFound": "db",
        "PendingRollbackError": "db",
        "SerializationFailure": "db",
        "DeadlockDetected": "db",
        "AttributeError": "attribute",
        "KeyError": "key",
        "TypeError": "type",
        "ValueError": "value",
        "ChannelError": "channel",
        "PDFError": "pdf",
        "FixtureLookupError": "fixture",
        "Failed": "assertion",
        "HTTPException": "http",
        "IndexError": "index",
    }
    TRACE_STAGES = {
        ("tests/conftest.py", "engine"): "fixture_schema",
        ("tests/conftest.py", "client"): "fixture_client",
        ("tests/conftest.py", "create_account"): "fixture_account",
        ("tests/test_chat.py", "chat_setup"): "fixture_chat",
        ("tests/test_chat_references.py", "selected_pdf"): "fixture_pdf",
        ("tests/test_attachments.py", "upload"): "pdf_upload",
        ("tests/test_attachments.py", "ready_derivative"): "pdf_derivative_setup",
        ("tests/test_chat_references.py", "submit_pdf"): "pdf_submit",
        ("app/attachments.py", "upload"): "pdf_upload",
        ("app/chat.py", "submit"): "turn_capture",
        ("app/chat.py", "turn_view"): "turn_view",
        ("app/chat_state.py", "context"): "context_capture",
        ("app/chat_references.py", "capture_references"): "reference_capture",
        ("app/chat_references.py", "derivative"): "reference_validation",
        ("app/chat_references.py", "resolve_context"): "reference_resolution",
        ("app/chat_dispatch.py", "advance"): "dispatch",
        ("app/chat_dispatch.py", "persist_receipts"): "receipt_commit",
        ("app/chat_dispatch.py", "poll_receipts"): "receipt_poll",
        ("tests/test_attachments_migration.py", "seed_history"): "migration_seed",
        ("tests/test_attachments_migration.py", "check_preservation"): "migration_check",
        ("tests/test_attachments_migration.py", "history"): "migration_snapshot",
        ("tests/test_attachments_migration.py", "migrate"): "migration_upgrade",
    }
    MARKER = b"IMPOSTR_IMP018_PYTEST "
    DETAILS = frozenset({"unknown", "fixture_missing", "table_missing", "table_columns"})
    MAX_FINDINGS = 64
    OUTAGE_TEST = (
        "tests/test_chat_receipts.py",
        "test_delete_outage_is_fenced_pending_and_purge_recovers_without_scrubbing_quotes",
    )
    OUTAGE_ASSERTION_STAGES = (
        "delete_request_pending", "delete_replay_pending", "future_send_fenced",
        "deleted_raw_denied", "deleted_preview_denied", "deletion_fence_pending",
        "purge_unconfirmed", "user_quote_retained", "broker_payload_purged",
        "delete_cleanup_complete", "future_send_accepted", "user_quote_history",
        "assistant_quote_history", "submission_retained",
    )

    def __init__(self):
        super().__init__("pytest", check_files=API_FILES)
        self.test_names = {}
        self.outage_assertions = {}
        for filename in FOCUSED_TESTS:
            try:
                tree = ast.parse((ROOT / "api" / filename).read_bytes())
            except (OSError, SyntaxError):
                continue
            self.test_names[filename] = frozenset(
                node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )
            if filename == self.OUTAGE_TEST[0]:
                function = next(node for node in tree.body
                                if isinstance(node, ast.FunctionDef)
                                and node.name == self.OUTAGE_TEST[1])
                assertions = sorted(
                    (node for node in ast.walk(function) if isinstance(node, ast.Assert)),
                    key=lambda node: node.lineno,
                )
                require(len(assertions) == len(self.OUTAGE_ASSERTION_STAGES))
                self.outage_assertions = {
                    node.lineno: stage
                    for node, stage in zip(assertions, self.OUTAGE_ASSERTION_STAGES)
                }
        self.findings = [{"file": "unknown", "test": "unknown", "category": "unknown"}]

    def feed(self, block):
        self.total += len(block)
        require(self.total <= 32 * 1024 * 1024)
        self.buffer += block
        while b"\n" in self.buffer:
            line, _, self.buffer = self.buffer.partition(b"\n")
            self.line(line.rstrip(b"\r"))
        require(len(self.buffer) <= 64 * 1024)

    def finish(self):
        if self.buffer:
            self.line(self.buffer.rstrip(b"\r"))
        self.buffer = b""

    @classmethod
    def category(cls, detail):
        if re.match(rb"(?:AssertionError\b|assert(?: |$))", detail):
            return "assertion"
        match = re.match(rb"^(?:[A-Za-z_][A-Za-z0-9_]*\.)*([A-Z][A-Za-z0-9_]*)(?::|$)", detail)
        if match is None:
            return "unknown"
        exception = match.group(1).decode("ascii")
        return cls.EXCEPTION_CATEGORIES.get(exception, "unknown")

    def line(self, line):
        super().line(line)
        if len(line) > 4096:
            return
        if line.startswith(self.MARKER):
            try:
                value = json.loads(line[len(self.MARKER):])
                fields = {
                    "file", "test", "phase", "stage", "exception", "detail",
                }
                require(isinstance(value, dict) and set(value) in (fields, fields | {"line"}))
                require(all(isinstance(value[key], str) for key in fields))
                require(value["test"] in self.test_names.get(value["file"], ()))
                require(value["phase"] in {"setup", "call", "teardown"})
                if "line" in value:
                    require((value["file"], value["test"]) == self.OUTAGE_TEST)
                    require(value["phase"] == "call" and value["exception"] == "AssertionError")
                    require(type(value["line"]) is int)
                    require(self.outage_assertions.get(value["line"]) == value["stage"])
                elif value["file"] == "tests/test_chat_postgres.py":
                    key = (value["file"], value["test"])
                    stages = PG_TEST_SUBSTAGES.get(key, frozenset())
                    require(value["stage"] in stages or value["stage"] == PG_TEST_STAGES.get(key))
                else:
                    require(value["stage"] in set(self.TRACE_STAGES.values()) | {
                        "test_setup", "test_call", "test_teardown",
                    })
                require(value["exception"] in set(self.EXCEPTION_CATEGORIES) | {"unknown"})
                require(value["detail"] in self.DETAILS)
                self.remember({**value, "category": self.EXCEPTION_CATEGORIES.get(
                    value["exception"], "unknown",
                )})
            except (ValueError, TypeError, Unavailable):
                self.reasons.add("diagnostic_invalid")
            return
        match = re.fullmatch(
            rb"(?:FAILED|ERROR) (tests/[a-z0-9_]+\.py)::(test_[a-z0-9_]+)"
            rb"(?:\[[^\r\n\]]{0,256}\])?(?: - ([^\r\n]{0,512}))?",
            line,
        )
        if match is None:
            return
        filename, test = (value.decode("ascii") for value in match.group(1, 2))
        if test not in self.test_names.get(filename, ()):
            return
        finding = {
            "file": filename,
            "test": test,
            "category": self.category(match.group(3) or b""),
        }
        # Hook reports take precedence over detail-free summaries, in either order.
        if any(row["file"] == filename and row["test"] == test and "stage" in row
               for row in self.findings):
            return
        self.remember(finding)

    def remember(self, finding):
        if self.findings and self.findings[0]["file"] == "unknown":
            self.findings.clear()
        if "phase" in finding:
            self.findings = [row for row in self.findings if "phase" in row or
                             (row["file"], row["test"]) != (finding["file"], finding["test"])]
        if finding not in self.findings:
            self.findings.append(finding)
        # New-test direct reports first, then other direct reports, then fallbacks.
        new_files = {"tests/test_chat_receipts.py", "tests/test_chat_references.py"}
        self.findings.sort(key=lambda row: ("phase" not in row, row["file"] not in new_files))
        del self.findings[self.MAX_FINDINGS:]


class PostgresOutput:
    """Project fixed pytest hooks, intake stages, and bounded result counts."""

    MARKER = b"IMPOSTR_IMP018_PYTEST "
    CAPTURE_DELETE_MARKER = b"IMPOSTR_IMP018_CAPTURE_DELETE "
    SUMMARY = re.compile(
        rb"(?:=+\s*)?((?:[0-9]{1,6} (?:passed|failed|skipped|errors?|warnings?))"
        rb"(?:, [0-9]{1,6} (?:passed|failed|skipped|errors?|warnings?))*)"
        rb"(?: in [0-9.]+s)?(?:\s*=+)?"
    )
    COUNTS = re.compile(rb"([0-9]{1,6}) (passed|failed|skipped|errors?|warnings?)")
    DETAILS = frozenset({"unknown", "fixture_missing", "table_missing", "table_columns"})

    def __init__(self):
        self.buffer = bytearray()
        self.counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0,
                       "warnings": 0}
        self.summary_seen = False
        self.findings = []
        self.command_failure = None
        self.capture_delete = []

    @property
    def passed(self):
        return (self.summary_seen and self.counts["passed"] == EXPECTED_PASSES
                and not any(self.counts[key] for key in ("failed", "skipped", "errors")))

    def failure_category(self):
        if self.counts["failed"] or self.counts["errors"]:
            return "test_failure"
        if self.findings:
            return "diagnostic_failure"
        if not self.summary_seen:
            return "summary_missing"
        if self.counts["skipped"] or self.counts["passed"] != EXPECTED_PASSES:
            return "unexpected_test_counts"
        return self.command_failure or "command_failure"

    def feed(self, block):
        self.buffer.extend(block)
        require(len(self.buffer) <= 1024 * 1024)
        while b"\n" in self.buffer:
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer[:] = rest
            self.line(line)

    def line(self, line):
        stripped = line.strip()
        match = self.SUMMARY.fullmatch(stripped)
        if match is not None:
            counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0,
                      "warnings": 0}
            for count, label in self.COUNTS.findall(match.group(1)):
                key = label.decode("ascii").rstrip("s")
                if key == "error":
                    key = "errors"
                if key == "warning":
                    key = "warnings"
                counts[key] += int(count)
            self.counts = counts
            self.summary_seen = True
        if len(line) > 2048:
            return
        if stripped.startswith(self.CAPTURE_DELETE_MARKER):
            self.parse_capture_delete(stripped[len(self.CAPTURE_DELETE_MARKER):])
            return
        if stripped.startswith(self.MARKER):
            self.parse_hook(stripped[len(self.MARKER):])
            return
        if b'"diagnostic":"imp017_intake_postgres"' not in line:
            return
        try:
            row = json.loads(stripped)
            require(row.get("stage") in PG_STAGES and row.get("category") in PG_CATEGORIES)
            value = {"stage": row["stage"], "category": row["category"]}
            if value not in self.findings and len(self.findings) < 8:
                self.findings.append(value)
        except Exception:
            self.findings.append({"stage": "unknown", "category": "unexpected"})

    def parse_capture_delete(self, body):
        try:
            row = json.loads(body)
            require(type(row) is dict and set(row) == {"capture", "delete", "outcome"})
            require(all((type(row[key]) is int and row[key] in CAPTURE_DELETE_STATUSES)
                        or (type(row[key]) is str and row[key] == "unknown")
                        for key in ("capture", "delete")))
            require(row["outcome"] == CAPTURE_DELETE_PAIRS.get(
                (row["capture"], row["delete"]), "other",
            ))
            if row not in self.capture_delete and len(self.capture_delete) < 8:
                self.capture_delete.append(row)
        except Exception:
            finding = {"stage": "capture_delete_race", "category": "unexpected"}
            if finding not in self.findings and len(self.findings) < 8:
                self.findings.append(finding)

    def parse_hook(self, body):
        try:
            row = json.loads(body)
            require(isinstance(row, dict) and set(row) == {
                "file", "test", "phase", "stage", "exception", "detail",
            })
            require(row["file"] == "tests/test_chat_postgres.py")
            key = (row["file"], row["test"])
            expected_stage = PG_TEST_STAGES.get(key)
            require(
                expected_stage is not None
                and row["stage"] in (PG_TEST_SUBSTAGES.get(key, frozenset()) | {expected_stage})
            )
            require(row["phase"] in {"setup", "call", "teardown"})
            require(row["exception"] in set(FocusedTestOutput.EXCEPTION_CATEGORIES) | {"unknown"})
            require(row["detail"] in self.DETAILS)
            category = FocusedTestOutput.EXCEPTION_CATEGORIES.get(row["exception"], "unknown")
            finding = {key: row[key] for key in ("file", "test", "phase", "stage", "detail")}
            finding["category"] = category
            if finding not in self.findings and len(self.findings) < 8:
                self.findings.append(finding)
        except Exception:
            finding = {"stage": "unknown", "category": "unexpected"}
            if finding not in self.findings and len(self.findings) < 8:
                self.findings.append(finding)

    def finish(self):
        if self.buffer:
            self.line(bytes(self.buffer))
        self.buffer.clear()
        require(self.passed and not self.findings)


class PDFNativeProduct(SyntheticProduct):
    """Credential-free native inference that proves exact rendered reference bytes."""

    def __init__(self, payload, observations, lock):
        super().__init__(payload)
        self.observations = observations
        self.lock = lock

    def events(self, data, cancelled, deadline, *, submission=None):
        rendered = resolved_prompt_text(self.payload)
        require(native_user_text(data) == rendered)
        require(submission is not None and not cancelled.is_set() and time.monotonic() < deadline)
        prompt = self.payload["prompt"]
        outcome = {
            "SYNTHETIC PDF FAIL BEFORE WRITE": "failed-before-send",
            "SYNTHETIC PDF PARTIAL WRITE": "uncertain",
        }.get(prompt, "sent")
        contains_pdf = has_pdf_references(self.payload)
        references = []
        attachment_ids = []
        available = 0
        for groups in self.payload.get("history", []):
            for item in groups.get("references", []):
                attachment_ids.append(item["reference"]["attachment_id"])
                references.append(item["reference"]["text_sha256"])
                available += item.get("availability") == "available"
        for item in self.payload.get("references", []):
            attachment_ids.append(item["reference"]["attachment_id"])
            references.append(item["reference"]["text_sha256"])
            available += item.get("availability") == "available"
        with self.lock:
            self.observations.append(
                {
                    "contains_pdf": contains_pdf,
                    "available": available,
                    "attachment_ids": tuple(attachment_ids),
                    "reference_hashes": tuple(references),
                    "submission_status": outcome,
                    "rendered_sha256": digest(rendered),
                    "manifest_sha256": manifest_digest(self.payload),
                }
            )

        if prompt == "SYNTHETIC PDF FAIL BEFORE WRITE":
            raise ValueError("synthetic before-write failure")
        if prompt == "SYNTHETIC PDF PARTIAL WRITE":
            submission.attempting()
            raise OSError("synthetic partial request write")
        if prompt == "SYNTHETIC PDF POST-SEND FAILURE":
            submission.consumed(data)
            raise ValueError("synthetic response failure after submission")
        submission.consumed(data)
        if prompt == "SYNTHETIC PDF WAIT FOR DELETE":
            question = {
                "type": "function_call",
                "name": "question",
                "call_id": "call_pdf_wait",
                "arguments": json.dumps(
                    {
                        "questions": [
                            {
                                "question": "Stop the synthetic attachment turn?",
                                "header": "Cleanup",
                                "options": [{"label": "Stop", "description": "Synthetic cleanup"}],
                            }
                        ]
                    },
                    separators=(",", ":"),
                ),
            }
            yield from native_response(calls=[question])
            return
        yield from native_response("Synthetic PDF reference checked.")


class PDFNativeTransport:
    observations: list[dict[str, object]] = []
    lock = threading.Lock()

    def __init__(self, payload):
        self.source = PDFNativeProduct(payload, self.observations, self.lock)
        self.normalizer = object.__new__(PlanningHTTPSInference)
        self.normalizer.contract = explicit_contract(
            "https://synthetic.example.invalid", "/openai/v1/responses", "none", "synthetic"
        )
        self.normalizer.acquire("generated-synthetic-key-not-real")

    def events(self, data, cancelled, deadline, *, submission=None):
        yield from self.normalizer.normalize_planning(
            EarlyResponse(self.source.events(data, cancelled, deadline, submission=submission)),
            data,
            cancelled,
            deadline,
        )


class Product:
    """Normal generated-Member API flow; only synthetic PDFs and one loopback origin."""

    def __init__(self, origin: str, login: dict[str, str]):
        from imp024_http import Client

        self.client = Client(origin, timeout=5)
        self.login = login
        self.project = self.conversation = self.base = self.attachment = None
        self.pdf_turns: list[str] = []

    def request(self, method, path, payload=None, expected=200):
        headers = {
            "Origin": self.client.base_url,
            "X-CSRF-Token": self.client.cookies.get("impostr_csrf", ""),
        }
        response = self.client.request(method, path, json=payload, headers=headers)
        require(response.status_code == expected)
        return response

    def get(self, path):
        response = self.client.get(path)
        require(response.status_code == 200)
        return response.json()

    @staticmethod
    def verify_native_receipt(turn, expected_status):
        receipt = turn["submission"]
        require(receipt["status"] == expected_status)
        matching = [
            observation
            for observation in PDFNativeTransport.observations
            if observation["rendered_sha256"] == receipt["rendered_sha256"]
            and observation["manifest_sha256"] == receipt["manifest_sha256"]
            and observation["submission_status"] == expected_status
        ]
        require(len(matching) == 1)

    def upload_pdf(self):
        import http.client

        from imp017_fixtures import text_pdf

        path = self.base + "/attachments/upload?filename=synthetic-reference.pdf"
        body = text_pdf()
        connection = http.client.HTTPConnection("127.0.0.1", self.client.port, timeout=5)
        try:
            cookie = "; ".join(
                name + "=" + self.client.cookies.get(name, "")
                for name in ("impostr_session", "impostr_csrf")
            )
            connection.request(
                "POST",
                path,
                body,
                {
                    "Origin": self.client.base_url,
                    "X-CSRF-Token": self.client.cookies.get("impostr_csrf", ""),
                    "Cookie": cookie,
                    "Content-Type": "application/pdf",
                    "Content-Length": str(len(body)),
                },
            )
            response = connection.getresponse()
            raw = response.read(8193)
            require(response.status == 201 and len(raw) <= 8192)
            value = json.loads(raw)
            require(value.get("status") == "pending" and value.get("included_in_model") is False)
            self.attachment = value["id"]
            return value
        finally:
            connection.close()

    def ready(self, attachment):
        path = self.base + "/attachments/" + attachment["id"]
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            value = self.get(path)
            if value["status"] == "ready":
                require(value["provenance"]["build_sha256"] == VERIFIED_BUILD_SHA256)
                require(value["text_sha256"] and value["page_count"] == 1)
                return value
            require(value["status"] == "pending" and value["failure_code"] is None)
            time.sleep(0.2)
        raise Unavailable()

    def send(self, prompt, selection=None):
        request_id = str(uuid.uuid4())
        payload = {"request_id": request_id, "prompt": prompt}
        if selection is not None:
            payload["selections"] = [selection]
        response = self.request("POST", self.base + "/turns", payload, expected=202)
        turn_id = response.json()["id"]
        if selection is not None:
            self.pdf_turns.append(turn_id)
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            history = self.get(self.base)
            turn = next(row for row in history["turns"] if row["id"] == turn_id)
            if turn["state"] in ("completed", "failed", "cancelled", "interrupted"):
                expected = {
                    "SYNTHETIC PDF FAIL BEFORE WRITE": "failed-before-send",
                    "SYNTHETIC PDF PARTIAL WRITE": "uncertain",
                }.get(prompt, "sent")
                self.verify_native_receipt(turn, expected)
                return turn
            time.sleep(0.15)
        raise Unavailable()

    def wait_interaction(self, turn_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            value = self.get(self.base)
            interaction = next(
                (row for row in value["interactions"]
                 if row["turn_id"] == turn_id and row["state"] == "pending"),
                None,
            )
            if interaction is not None:
                return interaction
            time.sleep(0.1)
        raise Unavailable()

    def run(self):
        csrf = self.get("/api/auth/csrf")["csrf_token"]
        response = self.client.post(
            "/api/auth/login",
            json=self.login,
            headers={"Origin": self.client.base_url, "X-CSRF-Token": csrf},
        )
        require(response.status_code == 200)
        root = self.request("POST", "/api/projects", {"name": "Synthetic PDF receipt"}, 201)
        self.project = root.json()["id"]
        chat = "/api/projects/" + self.project + "/chat"
        conversation = self.request("POST", chat, {"title": "PDF receipt"}, 201)
        self.conversation = conversation.json()["id"]
        self.base = chat + "/" + self.conversation

        uploaded = self.upload_pdf()
        ready = self.ready(uploaded)
        selected = {"attachment_id": uploaded["id"], "expected_sha256": ready["text_sha256"]}
        first = self.send("SYNTHETIC PDF INCLUDED", selected)
        require(first["state"] == "completed" and first["submission"]["status"] == "sent")
        calls = first["submission"]["calls"]
        require(
            len(calls) == 1
            and calls[0]["call"] == 1
            and calls[0]["status"] == "sent"
            and re.fullmatch(r"[0-9a-f]{64}", calls[0]["request_sha256"])
        )
        continuation = self.send("SYNTHETIC PDF CONTINUATION")
        require(continuation["state"] == "completed" and continuation["submission"]["status"] == "sent")
        self.pdf_turns.append(continuation["id"])

        for prompt, expected in (
            ("SYNTHETIC PDF FAIL BEFORE WRITE", "failed-before-send"),
            ("SYNTHETIC PDF PARTIAL WRITE", "uncertain"),
            ("SYNTHETIC PDF POST-SEND FAILURE", "sent"),
        ):
            turn = self.send(prompt, selected)
            require(turn["state"] in ("failed", "interrupted"))
            require(turn["submission"]["status"] == expected)
            require(len(turn["submission"]["calls"]) == 1)

        lost_ack = self.send("SYNTHETIC PDF LOST START ACK", selected)
        require(lost_ack["state"] == "interrupted" and lost_ack["submission"]["status"] == "sent")
        require(len(lost_ack["submission"]["calls"]) == 1)

        waiting = self.request(
            "POST",
            self.base + "/turns",
            {"request_id": str(uuid.uuid4()), "prompt": "SYNTHETIC PDF WAIT FOR DELETE",
             "selections": [selected]},
            expected=202,
        ).json()["id"]
        self.pdf_turns.append(waiting)
        interaction = self.wait_interaction(waiting)
        active = next(row for row in self.get(self.base)["turns"] if row["id"] == waiting)
        self.verify_native_receipt(active, "sent")
        require(self.request("DELETE", self.base + "/attachments/" + uploaded["id"],
                             expected=409).status_code == 409)
        self.request("POST", self.base + "/turns/" + waiting + "/abort", expected=200)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            current = next(
                row for row in self.get(self.base)["turns"] if row["id"] == waiting
            )
            if current["state"] == "cancelled":
                break
            time.sleep(0.1)
        require(current["state"] == "cancelled")
        require(self.request("DELETE", self.base + "/attachments/" + uploaded["id"],
                             expected=204).status_code == 204)

        # Deleted historical references remain metadata-only/unavailable and cannot
        # become a future derivative send. The native boundary records zero text entries.
        future = self.send("SYNTHETIC PDF DELETED FUTURE")
        require(future["state"] == "completed" and future["submission"]["status"] == "sent")
        history = self.get(self.base)
        old_reference = next(
            reference
            for turn in history["turns"]
            for reference in turn["references"]
            if reference["attachment_id"] == uploaded["id"]
        )
        require(old_reference["availability"] == "unavailable")
        return {
            "attachment_id": uploaded["id"],
            "text_sha256": ready["text_sha256"],
            "turn_ids": tuple(self.pdf_turns),
            "first": first,
            "continuation": continuation,
            "future": future,
            "waiting_interaction": interaction["id"],
        }

    def close(self):
        self.client.close()


class Phase5Verify(NormalVerify, LifecycleVerify):
    def __init__(self, api_only: bool):
        NormalVerify.__init__(self)
        self.api_only = api_only
        self.phase = "source_mapping"
        self.postgres_owner_overlay = None
        self.extractor_image = None
        self.reconstructed_tag = None
        self.reconstructed_image = None
        self.product = None
        self.pdf_overlay = None
        self.observation_start = 0

    def write_phase5_overlay(self):
        if self.api_only:
            return
        name = "imp018-pdf-chat.compose.yaml"
        content = (
            "services:\n"
            "  api:\n"
            "    command: [python, -B, tests/imp018_scoped_server.py]\n"
            "    environment:\n"
            "      IMPOSTR_TEST_POSTGRES: '1'\n"
            "      IMPOSTR_TEST_CHAT_CHANNEL: '1'\n"
            "      IMPOSTR_TEST_CHAT_JOINED: '1'\n"
            "      IMPOSTR_TEST_PDF_LIFECYCLE: '1'\n"
            "      IMPOSTR_CHAT_ENABLED: '1'\n"
            "      IMPOSTR_PDF_ENABLED: '1'\n"
            "  api-integration-check:\n"
            "    environment:\n"
            "      IMPOSTR_PDF_ENABLED: '1'\n"
            "      IMPOSTR_TEST_PDF_LIFECYCLE: '1'\n"
        )
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.directories[self.inputs],
        )
        with os.fdopen(fd, "w", encoding="ascii") as output:
            output.write(content)
        self.pdf_overlay = self.inputs / name
        # Enable PDF on the disposable API only. The channel volume, converter
        # service and dependency are attached after immutable image verification.
        self.base += ["-f", str(self.pdf_overlay)]

    def prepare_chat_connection(self):
        self.stage("prepare_retire_channel")
        old = self.channel
        old.rmdir()
        os.close(self.directories.pop(old))
        self.channel_owned = False

        from imp005_connection import OwnedRuntime

        self.stage("prepare_runtime")
        self.runtime = OwnedRuntime(self.inputs / "chat")
        self.stage("prepare_channel")
        self.channel = self.runtime.channel
        self.channel_owned = True
        self.pin_directory(self.channel)
        self.stage("prepare_compose_inputs")
        env = self.inputs / "fixture.env"
        env.write_text(env.read_text() + "IMPOSTR_CHAT_CHANNEL_DIR=" + str(self.channel) + "\n")
        self.base[-1] = "compose.chat.yaml"
        overlay = self.inputs / "checks.yaml"
        overlay.write_text(json.dumps({"services": {"api-integration-check": {
            "environment": {"IMPOSTR_TEST_CHAT_CHANNEL": "1", "IMPOSTR_TEST_CHAT_JOINED": "1",
                            "IMPOSTR_CHAT_ENABLED": "1"},
            "volumes": [{"type": "bind", "source": str(self.channel),
                         "target": "/run/impostr-broker", "read_only": True,
                         "bind": {"create_host_path": False}}]}}}))
        self.base += ["-f", str(overlay)]

    def prepare(self):
        self.stage("prepare_base")
        # Avoid sibling prepare() dispatch: NormalVerify.super() enters the
        # lifecycle/PDF overlay under this multiple-inheritance MRO.
        Verify.prepare(self)
        self.prepare_chat_connection()
        self.write_phase5_overlay()
        self.write_postgres_owner_overlay()

    def attach_verified_extractor(self):
        require(self.extractor_image is not None)
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", self.extractor_image))
        pinned = self.base[-2:]
        require(
            pinned[0] == "-f"
            and Path(pinned[1]).parent == self.inputs
            and Path(pinned[1]).name == "extractor-pinned.compose.yaml"
        )
        # compose.pdf-app.yaml adds the converter service/dependency. Keep the
        # immutable-ID override after that file so the mutable build tag cannot win.
        self.base = self.base[:-2] + ["-f", str(ROOT / "compose.pdf-app.yaml")] + pinned

    def start_broker(self):
        require(self.connection is None)
        self.stage("broker_runtime")
        if self.runtime is None:
            from imp005_connection import OwnedRuntime, Connection

            self.runtime = OwnedRuntime(self.inputs / "chat")
        self.stage("broker_construct")
        from imp005_connection import Connection

        self.connection = Connection(self.runtime, PDFNativeTransport, mode="planning")
        self.stage("broker_start")
        self.connection.start()

    def check_api(self, stage, *args, output, seconds=300):
        self.stage(stage)
        try:
            self.compose("run", "--rm", *args, seconds=seconds, output=output)
        except Exception:
            report(stage + "_diagnostic", "failed",
                   reasons=sorted(getattr(output, "reasons", ())) or ["check_operation_failed"],
                   findings=getattr(output, "findings", []))
            raise
        report(stage, "passed")

    def postgres_check(self):
        output = PostgresOutput()
        self.stage("api_fresh_postgres")
        try:
            require(self.postgres_owner_overlay is not None)
            self.compose_used = True
            self.command(
                self.base + [
                    "-f", str(self.postgres_owner_overlay), "run", "--build", "--rm",
                    POSTGRES_OWNER_SERVICE, "python", "-m", "pytest", "-p",
                    "no:cacheprovider", "--capture=tee-sys", "--imp018-diagnostics",
                    "--tb=no", "--show-capture=no", "--color=no", *PG_TESTS,
                ],
                seconds=360, output=output,
            )
            require(output.passed)
        except Exception:
            report("api_fresh_postgres_diagnostic", "failed", findings=output.findings,
                   counts=output.counts, command_failure=output.failure_category(),
                   capture_delete=output.capture_delete)
            raise
        report("api_fresh_postgres", "passed", tests=EXPECTED_PASSES,
               capture_delete=output.capture_delete)

    def reference_format_diff(self):
        output = ReferenceFormatDiffOutput()
        try:
            # Existing just-built owned check image, before normal cleanup. No
            # build, image reconstruction, arbitrary path or formatter write.
            # Supply exact pinned input directly inside the check container;
            # Compose stdin and shell redirection are not part of Ruff transport.
            self.compose(
                "run", "--rm", "--no-deps", "--no-build", "--pull", "never", "-T",
                "api-check", "python", "-I", "-B", "-c", REFERENCE_FORMAT_CAPTURE,
                seconds=60, output=output,
            )
        except Exception:
            # Stdin formatting succeeds with status 0. Even validated bytes from
            # a failed command aren't evidence of a successful formatter run.
            if output.diff is not None:
                output.diff = None
                output.reason = "command_failed"
        if output.diff is None:
            if output.capture is not None:
                report("api_reference_formatter_capture", "unavailable", file=output.FILE,
                       **output.capture)
            report("api_reference_format_diff", "unavailable", file=output.FILE,
                   reason=output.reason, shape=output.shape)
        else:
            report("api_reference_format_diff", "observed", file=output.FILE, diff=output.diff)

    def focused_api(self):
        self.stage("build_api_and_db")
        self.compose("build", "db", "api", "api-check", "api-integration-check", "frontdoor",
                     seconds=600)
        self.stage("database")
        self.compose("up", "-d", "--wait", "db", seconds=180)
        self.stage("migration")
        self.compose("run", "--rm", "api", "alembic", "upgrade", "head", seconds=180)
        output = HeadOutput()
        self.stage("migration_current")
        self.compose("run", "--rm", "api", "alembic", "current", output=output)
        report("api_migration", "passed", head="20261002_0010")

        self.check_api(
            "api_focused_tests", "api-check", "python", "-m", "pytest", "-p",
            "no:cacheprovider", "--imp018-diagnostics", "--tb=no", "--show-capture=no",
            "--color=no", *FOCUSED_TESTS,
            output=FocusedTestOutput(), seconds=300,
        )
        self.postgres_check()
        self.check_api(
            "api_ruff", "api-check", "ruff", "check", "--output-format", "json", *API_FILES,
            output=RuffJsonOutput(check_files=API_FILES),
        )
        format_output = CheckOutput("ruff_format", check_files=API_FILES)
        try:
            self.check_api(
                "api_format", "api-check", "ruff", "format", "--check", *API_FILES,
                output=format_output,
            )
        except Exception:
            if {"file": ReferenceFormatDiffOutput.FILE, "code": "format_mismatch"} in (
                format_output.findings
            ):
                self.reference_format_diff()
            raise  # Diagnostics never replace or waive the actual format gate.
        self.check_api("api_mypy", "api-check", "mypy", "app",
                       output=CheckOutput("mypy", check_files=API_FILES))

    def run_full(self):
        self.ensure_extractor()
        self.attach_verified_extractor()
        self.stage("api_stack_ready")
        self.stage("extractor_volume")
        self.compose("create", "--no-build", "--pull", "never", "pdf-extractor", seconds=60)
        self.stage("pdf_started")
        self.compose("up", "-d", "--wait", "pdf-extractor", seconds=60)

        member = MemberOutput()
        self.stage("generated_member")
        self.compose(
            "run", "--rm", "api-integration-check", "python", "-B",
            "tests/imp024_operator_member.py", output=member,
        )
        require(member.login is not None)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        origin = "http://127.0.0.1:" + str(port)
        env = self.inputs / "fixture.env"
        value = env.read_text(encoding="ascii")
        value = value.replace("APP_PORT=8080\n", f"APP_PORT={port}\n").replace(
            "IMPOSTR_PUBLIC_ORIGIN=http://127.0.0.1:8080\n",
            "IMPOSTR_PUBLIC_ORIGIN=" + origin + "\n",
        )
        env.write_text(value, encoding="ascii")
        self.stage("ordinary_api")
        self.compose("up", "-d", "--wait", "api", "frontdoor", seconds=180)
        self.product = Product(origin, member.login)
        with PDFNativeTransport.lock:
            PDFNativeTransport.observations.clear()
        self.observation_start = 0
        result = self.product.run()
        observations = PDFNativeTransport.observations[self.observation_start:]
        require(len(observations) >= 8)
        current = [row for row in observations if row["contains_pdf"]]
        for response in (result["first"], result["continuation"]):
            submission = response["submission"]
            require(any(
                row["manifest_sha256"] == submission["manifest_sha256"]
                and row["rendered_sha256"] == submission["rendered_sha256"]
                and result["attachment_id"] in row["attachment_ids"]
                and result["text_sha256"] in row["reference_hashes"]
                and row["available"] >= 1
                for row in current
            ))
        deleted = observations[-1]
        require(
            deleted["contains_pdf"]
            and deleted["available"] == 0
            and result["attachment_id"] in deleted["attachment_ids"]
            and deleted["manifest_sha256"] == result["future"]["submission"]["manifest_sha256"]
            and deleted["rendered_sha256"] == result["future"]["submission"]["rendered_sha256"]
        )
        require(all(row["rendered_sha256"] and row["manifest_sha256"] for row in observations))
        for turn_id in result["turn_ids"]:
            turn = self.connection.broker.turns.get(turn_id)
            require(turn is not None and turn.purged and turn.payload is None and not turn.events)
        report("ordinary_synthetic_pdf_chat", "passed", native_requests=len(observations),
               extractor_build_sha256=VERIFIED_BUILD_SHA256)

    def cleanup(self):
        if self.product is not None:
            try:
                self.product.close()
            except Exception:
                pass
            self.product = None
        # LifecycleVerify adds cleanup for only its exclusively reconstructed tag;
        # IntakeVerify adds the generated DB-owner overlay to Compose down.
        return LifecycleVerify.cleanup(self)

    def run(self):
        passed = False
        try:
            require_source_mapping()
            self.prepare()
            if not self.api_only:
                self.start_broker()
            self.focused_api()
            if not self.api_only:
                self.stage("synthetic_receipt_state_tests")
                self.command(
                    ["/usr/bin/python3", "-I", "-B", "-m", "unittest", "discover",
                     "-s", "scripts", "-p", "test_imp018_*.py"],
                    seconds=180, output=CheckOutput("unittest", check_files=()),
                )
                report("synthetic_receipt_state_tests", "passed")
                self.run_full()
            passed = True
        except (Exception, KeyboardInterrupt):
            report("imp018_stage", "failed", phase=self.phase)
        finally:
            cleaned = self.cleanup()
            report("owned_cleanup", "passed" if cleaned else "failed")
            passed = passed and cleaned
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--api-only", action="store_true")
    mode.add_argument("--full", action="store_true")
    parser.add_argument(
        "--reviewed-full",
        action="store_true",
        help="Required only after independent review before full boundary execution",
    )
    args = parser.parse_args()
    if args.full != args.reviewed_full:
        parser.error("--full requires --reviewed-full; API-only forbids it")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        return Phase5Verify(api_only=args.api_only).run()
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
