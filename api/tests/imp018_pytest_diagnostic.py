"""Opt-in fixed pytest diagnostics for the coordinator's focused IMP-018 check.

Only exception identity, allowlisted code stages, source-known assertion lines and
fixed HTTP status pairs survive.
Never format an exception/longrepr or print messages, parameters, paths or SQL.
This plugin does not alter test execution, report outcomes or output capture.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

MARKER = "IMPOSTR_IMP018_PYTEST "
FOCUSED_FILES = (
    "tests/test_attachments.py",
    "tests/test_attachments_migration.py",
    "tests/test_chat.py",
    "tests/test_chat_receipts.py",
    "tests/test_chat_references.py",
    "tests/test_chat_references_migration.py",
)
POSTGRES_TEST_STAGES = {
    (
        "tests/test_chat_postgres.py",
        "test_postgres_chat_migration_preserves_preexisting_identity_and_documents",
    ): "pg_migration_preservation",
    (
        "tests/test_chat_postgres.py",
        "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads",
    ): "pg_turn_reservation_concurrency",
}
POSTGRES_TEST_SUBSTAGES = {
    (
        "tests/test_chat_postgres.py",
        "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads",
    ): frozenset(
        {
            "submit_idempotency",
            "leaseclaim",
            "otherwriter",
            "abort",
            "upload",
            "capture_delete_race",
            "capture_integrity",
            "purge_cleanup",
        }
    ),
}
EXCEPTIONS = frozenset(
    {
        "ImportError",
        "ModuleNotFoundError",
        "NameError",
        "UnboundLocalError",
        "AssertionError",
        "IntegrityError",
        "OperationalError",
        "ProgrammingError",
        "DatabaseError",
        "DBAPIError",
        "DataError",
        "InterfaceError",
        "SQLAlchemyError",
        "NoResultFound",
        "PendingRollbackError",
        "SerializationFailure",
        "DeadlockDetected",
        "AttributeError",
        "KeyError",
        "TypeError",
        "ValueError",
        "ChannelError",
        "PDFError",
        "FixtureLookupError",
        "Failed",
        "HTTPException",
        "IndexError",
    }
)
STAGES = {
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
DETAILS = frozenset({"unknown", "fixture_missing", "table_missing", "table_columns"})
OUTAGE_TEST = (
    "tests/test_chat_receipts.py",
    "test_delete_outage_is_fenced_pending_and_purge_recovers_without_scrubbing_quotes",
)
OUTAGE_ASSERTION_STAGES = (
    "delete_request_pending",
    "delete_replay_pending",
    "future_send_fenced",
    "deleted_raw_denied",
    "deleted_preview_denied",
    "deletion_fence_pending",
    "purge_unconfirmed",
    "user_quote_retained",
    "broker_payload_purged",
    "delete_cleanup_complete",
    "future_send_accepted",
    "user_quote_history",
    "assistant_quote_history",
    "submission_retained",
)
PROPERTY = "imp018_fixed_diagnostic"
CAPTURE_DELETE_PROPERTY = "imp018_capture_delete_pair"
CAPTURE_DELETE_MARKER = "IMPOSTR_IMP018_CAPTURE_DELETE "
CAPTURE_DELETE_STATUSES = frozenset(
    {200, 201, 202, 204, 400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 503}
)
CAPTURE_DELETE_PAIRS = {
    (202, 409): "captured_then_conflict",
    (404, 204): "deleted_then_notfound",
    (409, 204): "fenced_then_conflict",
    (409, 202): "queued_cleanup",
}


def fixed_capture_delete_pair(capture_status, delete_status):
    # Response bodies, headers and arbitrary integers never enter the diagnostic.
    capture = (
        capture_status
        if (type(capture_status) is int and capture_status in CAPTURE_DELETE_STATUSES)
        else "unknown"
    )
    removed = (
        delete_status
        if (type(delete_status) is int and delete_status in CAPTURE_DELETE_STATUSES)
        else "unknown"
    )
    return {
        "capture": capture,
        "delete": removed,
        "outcome": CAPTURE_DELETE_PAIRS.get((capture, removed), "other"),
    }


def fixed_detail(excinfo, exception):
    if exception == "FixtureLookupError":
        return "fixture_missing"
    if exception not in {"OperationalError", "ProgrammingError"}:
        return "unknown"
    # Examine only an existing bounded DBAPI string, never str(exception), which
    # may render statements/parameters. The string itself is never retained.
    original = getattr(excinfo.value, "orig", None)
    args = getattr(original, "args", ())
    if type(args) is tuple and args and type(args[0]) is str and len(args[0]) <= 2048:
        message = args[0].lower()
        if message.startswith("no such table:"):
            return "table_missing"
        if message.startswith("no such column:") or "has no column named" in message:
            return "table_columns"
    return "unknown"


class DiagnosticPlugin:
    def __init__(self, root=None):
        self.root = root or Path(__file__).resolve().parents[1]
        self.names = {}
        self.outage_assertions = {}
        for filename in FOCUSED_FILES + ("tests/test_chat_postgres.py",):
            tree = ast.parse((self.root / filename).read_bytes())
            self.names[filename] = frozenset(
                node.name
                for node in tree.body
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name.startswith("test_")
            )
            if filename == OUTAGE_TEST[0]:
                function = next(
                    node
                    for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == OUTAGE_TEST[1]
                )
                assertions = sorted(
                    (node for node in ast.walk(function) if isinstance(node, ast.Assert)),
                    key=lambda node: node.lineno,
                )
                if len(assertions) != len(OUTAGE_ASSERTION_STAGES):
                    raise ValueError("Outage assertion mapping changed")
                self.outage_assertions = {
                    line: (node.lineno, stage)
                    for node, stage in zip(assertions, OUTAGE_ASSERTION_STAGES, strict=True)
                    for line in range(node.lineno, node.end_lineno + 1)
                }
        self.frames = {
            (str(self.root / filename), name): stage for (filename, name), stage in STAGES.items()
        }
        self.emitted = 0
        self.race_emitted = 0

    def project(self, nodeid, phase, excinfo):
        parts = nodeid.split("::")
        if len(parts) != 2 or phase not in {"setup", "call", "teardown"}:
            return None
        filename, test = parts[0], parts[1].split("[", 1)[0]
        if test not in self.names.get(filename, ()):
            return None
        name = excinfo.type.__name__
        exception = name if name in EXCEPTIONS else "unknown"
        stage = POSTGRES_TEST_STAGES.get((filename, test), "test_" + phase)
        assertion_line = None
        traceback = excinfo.value.__traceback__
        # Use code identity and the one allowlisted stage local, never traceback text.
        for _ in range(128):
            if traceback is None:
                break
            code = traceback.tb_frame.f_code
            if (
                (filename, test) == OUTAGE_TEST
                and phase == "call"
                and exception == "AssertionError"
                and code.co_name == test
                and code.co_filename == str(self.root / filename)
                and traceback.tb_lineno in self.outage_assertions
            ):
                assertion_line, stage = self.outage_assertions[traceback.tb_lineno]
            if (
                code.co_name == test
                and code.co_filename == str(self.root / filename)
                and filename == "tests/test_chat_postgres.py"
            ):
                candidates = POSTGRES_TEST_SUBSTAGES.get((filename, test), frozenset())
                candidate = traceback.tb_frame.f_locals.get("imp018_diagnostic_stage")
                if isinstance(candidate, str) and candidate in candidates:
                    stage = candidate
            known = self.frames.get((code.co_filename, code.co_name))
            if known is not None:
                stage = known
            traceback = traceback.tb_next
        value = {
            "file": filename,
            "test": test,
            "phase": phase,
            "stage": stage,
            "exception": exception,
            "detail": fixed_detail(excinfo, exception),
        }
        if assertion_line is not None:
            value["line"] = assertion_line
        return value

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        if report.failed and call.excinfo is not None:
            value = self.project(item.nodeid, report.when, call.excinfo)
            if value is not None:
                report.user_properties.append((PROPERTY, value))

    def pytest_runtest_logreport(self, report):
        # record_property preserves the measured pair even if the assertion passes;
        # it is an observation, never a replacement for the test's integrity checks.
        if (
            getattr(report, "when", None) == "call"
            and self.race_emitted < 1
            and getattr(report, "nodeid", None)
            == (
                "tests/test_chat_postgres.py::"
                "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads"
            )
        ):
            for key, value in report.user_properties:
                if (
                    key == CAPTURE_DELETE_PROPERTY
                    and type(value) is dict
                    and set(value) == {"capture", "delete", "outcome"}
                ):
                    projected = fixed_capture_delete_pair(value["capture"], value["delete"])
                    if value != projected:
                        continue
                    terminal = self.config.pluginmanager.getplugin("terminalreporter")
                    if terminal is not None:
                        terminal.write_line(
                            CAPTURE_DELETE_MARKER + json.dumps(projected, separators=(",", ":"))
                        )
                        self.race_emitted += 1
                    break
        if not report.failed or self.emitted >= 128:
            return
        for key, value in report.user_properties:
            if key == PROPERTY:
                terminal = self.config.pluginmanager.getplugin("terminalreporter")
                if terminal is not None:
                    terminal.write_line(MARKER + json.dumps(value, separators=(",", ":")))
                    self.emitted += 1
                break

    def pytest_configure(self, config):
        self.config = config
