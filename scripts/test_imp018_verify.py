"""IMP-018 verifier fixture/parser checks; no Docker, runtime or private inputs."""

from __future__ import annotations

import ast
import difflib
import json
from contextlib import redirect_stderr
import io
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api"))

import imp018_verify as verifier
from app.chat_protocol import digest, resolved_prompt_text
from test_imp018_receipts import ledger, native, resolved
from imp018_verify import PDFNativeProduct


def diagnostic_module():
    # Host has no pytest installation; load only this test-only hook with a
    # no-op decorator, then exercise actual Python exceptions/report doubles.
    spec = importlib.util.spec_from_file_location(
        "imp018_pytest_diagnostic", ROOT / "api/tests/imp018_pytest_diagnostic.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"pytest": SimpleNamespace(
        hookimpl=lambda **_: lambda function: function,
    )}):
        spec.loader.exec_module(module)
    return module


class VerifierProjectionTests(unittest.TestCase):
    def test_runtime_source_inputs_are_the_reviewed_baseline_mapping(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            verifier.require_source_mapping()
        self.assertIn('"check": "exact_source_mapping"', stdout.getvalue())
        self.assertEqual(len(verifier.PINNED_SOURCES), 31)

    def test_outage_retention_assertion_targets_sent_identity_when_created_at_ties(self):
        # SQLite's actual timestamp precision and API's UUID tiebreak can put the
        # queued follow-up first. Execute the source assertion (not a substitute)
        # in both deterministic ID orders and prove losing the old status fails.
        tree = ast.parse((ROOT / "api/tests/test_chat_receipts.py").read_bytes())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == verifier.FocusedTestOutput.OUTAGE_TEST[1])
        selection = next(node for node in function.body if isinstance(node, ast.Assign)
                         and any(isinstance(target, ast.Name) and target.id == "original_history"
                                 for target in node.targets))
        assertion = [node for node in function.body if isinstance(node, ast.Assert)][-1]
        checked = compile(ast.Module(body=[selection, assertion], type_ignores=[]),
                          "<outage-retention-assertion>", "exec")
        ids = ("00000000-0000-0000-0000-000000000001",
               "ffffffff-ffff-ffff-ffff-ffffffffffff")
        for original, continued in (ids, ids[::-1]):
            with self.subTest(original=original), sqlite3.connect(":memory:") as db:
                db.execute("CREATE TABLE turns (id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
                           "submission_state TEXT)")
                db.execute("INSERT INTO turns (id, submission_state) VALUES (?, 'sent')", (original,))
                db.execute("INSERT INTO turns (id, created_at, submission_state) "
                           "SELECT ?, created_at, 'queued' FROM turns WHERE id = ?",
                           (continued, original))

                def response():
                    return {"turns": [
                        {"id": row[0], "submission": {"status": row[1]}}
                        for row in db.execute("SELECT id, submission_state FROM turns "
                                              "ORDER BY created_at, id")
                    ]}

                if original > continued:
                    # Deterministically reproduce the exact previous assertion.
                    with self.assertRaises(AssertionError):
                        assert response()["turns"][0]["submission"]["status"] == "sent"
                client = SimpleNamespace(get=lambda _: SimpleNamespace(json=response))
                submitted = SimpleNamespace(json=lambda: {"id": original})
                scope = {"client": client, "response": submitted, "base": "/synthetic", "conv": "id"}
                exec(checked, scope)
                self.assertEqual(scope["original_history"]["id"], original)
                db.execute("UPDATE turns SET submission_state = 'queued' WHERE id = ?", (original,))
                with self.assertRaises(AssertionError):
                    exec(checked, scope)  # Never hide a genuine loss of durable sent status.

    @staticmethod
    def reference_formatted(after=None):
        filename = verifier.ReferenceFormatDiffOutput.FILE
        before = (ROOT / "api" / filename).read_text()
        if after is None:
            after = before.replace(
                "    assert response.status_code == 202\n",
                "    assert (\n        response.status_code == 202\n    )\n", 1,
            )
        return after.encode()

    @classmethod
    def reference_diff(cls, after=None):
        filename = verifier.ReferenceFormatDiffOutput.FILE
        before = (ROOT / "api" / filename).read_text()
        return "".join(difflib.unified_diff(
            before.splitlines(keepends=True),
            cls.reference_formatted(after).decode().splitlines(keepends=True),
            fromfile=filename, tofile=filename,
        )).encode()

    def test_reference_format_diff_is_atomic_and_keeps_assertions_and_literals(self):
        output = verifier.ReferenceFormatDiffOutput()
        diff = self.reference_diff()
        formatted = self.reference_formatted()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            for offset in range(0, len(formatted), 17):
                output.feed(formatted[offset:offset + 17])
            self.assertIsNone(output.diff)
            output.finish()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(output.diff.encode(), diff)
        self.assertEqual(output.buffer, bytearray())

    def test_reference_format_diff_accepts_trailing_comma_in_exact_owned_fixture(self):
        before = (ROOT / "api" / verifier.ReferenceFormatDiffOutput.FILE).read_text()
        # Exercise the actual long call in the pinned fixture, including Ruff's
        # legitimate added trailing comma, not an invented substitute test source.
        after = before.replace(
            '            f"{base}/{conv}/attachments/{first[\'attachment_id\']}", headers=headers\n',
            '            f"{base}/{conv}/attachments/{first[\'attachment_id\']}",\n'
            '            headers=headers,\n',
            1,
        )
        self.assertNotEqual(before, after)
        self.assertEqual(ast.dump(ast.parse(before)), ast.dump(ast.parse(after)))
        output = verifier.ReferenceFormatDiffOutput()
        diff = self.reference_diff(after)
        output.feed(self.reference_formatted(after))
        output.finish()
        self.assertEqual(output.diff.encode(), diff)
        self.assertIsNone(output.reason)

    def test_reference_formatter_uniform_crlf_normalizes_to_same_local_diff(self):
        formatted = self.reference_formatted().replace(b"\n", b"\r\n")
        output = verifier.ReferenceFormatDiffOutput()
        output.feed(formatted)
        output.finish()
        self.assertEqual(output.diff.encode(), self.reference_diff())
        self.assertIsNone(output.reason)
        self.assertEqual(output.shape, {
            "bytes": len(formatted), "empty": False, "terminal_lf": True,
            "crlf": formatted.count(b"\r\n"), "bare_cr": 0, "bare_lf": 0, "nul": False,
        })
        self.assertEqual(output.source, (ROOT / "api" / output.FILE).read_bytes())

    def test_reference_formatter_invalid_shapes_report_only_fixed_metrics(self):
        formatted = self.reference_formatted()
        crlf = formatted.replace(b"\n", b"\r\n")
        for source in (
            b"", formatted[:-1], formatted.replace(b"\n", b"\r", 1),
            crlf.replace(b"\r\n", b"\n", 1), b"\x00" + formatted,
        ):
            output = verifier.ReferenceFormatDiffOutput()
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                output.feed(source)
                with self.assertRaises(verifier.Unavailable):
                    output.finish()
            self.assertIsNone(output.diff)
            self.assertEqual(output.reason, "source_shape")
            self.assertEqual(output.shape, output.source_shape(source))
            self.assertEqual(set(output.shape), {
                "bytes", "empty", "terminal_lf", "crlf", "bare_cr", "bare_lf", "nul",
            })
            self.assertTrue(all(type(value) in (bool, int) for value in output.shape.values()))
            self.assertEqual(output.buffer, bytearray())
            self.assertEqual(stdout.getvalue(), "")

    def test_reference_format_diff_rejects_source_substitution_and_unrelated_output(self):
        filename = verifier.ReferenceFormatDiffOutput.FILE
        before = (ROOT / "api" / filename).read_text()
        changed_assertion = before.replace("assert response.status_code == 202",
                                            "assert response.status_code == 204", 1)
        injected_comment = before.replace("import json", "# private payload\nimport json", 1)
        for formatted, reason in (
            (self.reference_formatted(changed_assertion), "ast_changed"),
            (self.reference_formatted(injected_comment), "comments_changed"),
            (self.reference_diff(), "python_syntax"),  # Never parse runtime diff headers.
            (self.reference_formatted() + b"private stderr payload\n", "python_syntax"),
            (b"private output, no source\n", "python_syntax"),
            (self.reference_formatted()[:-1], "source_shape"),
            (before.encode(), "unchanged_source"),
        ):
            output = verifier.ReferenceFormatDiffOutput()
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                output.feed(formatted)
                with self.assertRaises(verifier.Unavailable):
                    output.finish()
            self.assertIsNone(output.diff)
            self.assertEqual(output.reason, reason)
            self.assertEqual(output.buffer, bytearray())
            self.assertEqual(stdout.getvalue(), "")

    def test_reference_format_diff_rejects_source_drift_and_oversized_output(self):
        output = verifier.ReferenceFormatDiffOutput()
        output.feed(self.reference_formatted())
        with patch.object(Path, "read_bytes", return_value=b"changed source"):
            with self.assertRaises(verifier.Unavailable):
                output.finish()
        self.assertIsNone(output.diff)
        self.assertEqual(output.reason, "source_drift")
        self.assertEqual(output.buffer, bytearray())
        output = verifier.ReferenceFormatDiffOutput()
        with self.assertRaises(verifier.Unavailable):
            output.feed(b"x" * (output.MAX_BYTES + 1))
        self.assertEqual(output.buffer, bytearray())
        self.assertEqual(output.reason, "output_limit")

    def test_reference_format_diff_runs_before_failed_gate_returns_and_never_passes_gate(self):
        runner = verifier.Phase5Verify(api_only=True)
        runner.postgres_check = Mock()
        runner.stage = lambda _: None
        diff = self.reference_diff()
        calls = []

        def compose(*args, **kwargs):
            calls.append(args)
            if "--check" in args:
                kwargs["output"].line(
                    b"Would reformat: " + verifier.ReferenceFormatDiffOutput.FILE.encode()
                )
                raise verifier.Unavailable()
            if verifier.REFERENCE_FORMAT_CAPTURE in args:
                kwargs["output"].feed(self.reference_formatted())
                kwargs["output"].finish()

        runner.compose = compose
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            with self.assertRaises(verifier.Unavailable):
                runner.focused_api()
        self.assertEqual(calls[-1], (
            "run", "--rm", "--no-deps", "--no-build", "--pull", "never", "-T",
            "api-check", "python", "-I", "-B", "-c", verifier.REFERENCE_FORMAT_CAPTURE,
        ))
        reports = [json.loads(line) for line in stdout.getvalue().splitlines()]
        projected = next(row for row in reports if row["check"] == "api_reference_format_diff")
        self.assertEqual(projected["diff"].encode(), diff)
        self.assertEqual(projected["status"], "observed")
        self.assertFalse(any(row["check"] == "api_format" and row["status"] == "passed"
                             for row in reports))

    def test_reference_formatter_command_pipes_only_stdout_and_discards_stderr(self):
        # Exercise reference_format_diff -> inherited compose -> inherited command
        # -> Popen -> container Python -> Ruff subprocess stdin. Only Docker/Ruff
        # executables are replaced by synthetic child processes; neither helper,
        # collector, feed nor finish is mocked. No Docker or file writes occur.
        runner = verifier.Phase5Verify(api_only=True)
        runner.environment = {"PATH": "/usr/bin:/bin"}
        formatter = (
            "import hashlib,sys; source=sys.stdin.buffer.read(); "
            "assert hashlib.sha256(source).hexdigest()=="
            f"{verifier.PINNED_SOURCES['api/tests/test_chat_references.py']!r}; "
            "formatted=source.replace(b'    assert response.status_code == 202\\n', "
            "b'    assert (\\n        response.status_code == 202\\n    )\\n', 1); "
            "assert formatted != source; sys.stdout.buffer.write(formatted); "
            "sys.stdout.buffer.flush(); "
            "sys.stderr.write('1 file reformatted\\r\\nprivate stderr not forwarded\\r\\n')"
        )
        expected = (
            "run", "--rm", "--no-deps", "--no-build", "--pull", "never", "-T",
            "api-check", "python", "-I", "-B", "-c", verifier.REFERENCE_FORMAT_CAPTURE,
        )
        child = (
            "import subprocess,sys; "
            f"assert tuple(sys.argv[1:]) == {expected!r}; "
            "script=sys.argv[-1]; "
            f"bootstrap={self.reference_capture_bootstrap(formatter)!r}; "
            "result=subprocess.run([sys.executable,'-I','-B','-c',bootstrap,script],check=False); "
            "sys.exit(result.returncode)"
        )
        runner.base = [sys.executable, "-I", "-B", "-c", child]
        real_popen = verifier.subprocess.Popen
        with patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                patch.object(verifier.subprocess, "Popen", wraps=real_popen) as popen:
            runner.reference_format_diff()
        self.assertIs(popen.call_args.kwargs["stdout"], verifier.subprocess.PIPE)
        self.assertIs(popen.call_args.kwargs["stderr"], verifier.subprocess.PIPE)
        projected = json.loads(stdout.getvalue())
        self.assertEqual(projected, {
            "check": "api_reference_format_diff", "status": "observed",
            "file": verifier.ReferenceFormatDiffOutput.FILE,
            "diff": self.reference_diff().decode(),
        })
        self.assertNotIn("private stderr", stdout.getvalue())
        self.assertTrue(runner.compose_used)
        self.assertEqual(runner.active, set())

    @staticmethod
    def reference_capture_bootstrap(formatter, source_override=None):
        # Test-only remapping of the one literal /app path and fixed Ruff argv.
        # Production capture code is executed unchanged, with real input PIPEs.
        source = (ROOT / "api/tests/test_chat_references.py").read_bytes()
        return (
            "import pathlib,subprocess,sys; from unittest.mock import patch; "
            "real_run=subprocess.run; "
            f"source={source if source_override is None else source_override!r}; "
            f"formatter={formatter!r}; "
            "expected=['ruff','format','--no-cache','--stdin-filename',"
            "'tests/test_chat_references.py','-']; "
            "read=lambda p: source if str(p)=='/app/tests/test_chat_references.py' "
            "else (_ for _ in ()).throw(AssertionError()); "
            "run=lambda args,**kw: real_run([sys.executable,'-I','-B','-c',formatter],"
            "**dict(kw,cwd=None)) if args==expected and kw.get('cwd')=='/app' "
            "else (_ for _ in ()).throw(AssertionError()); "
            "p=patch.object(pathlib.Path,'read_bytes',read); "
            "r=patch.object(subprocess,'run',run); p.start(); r.start(); "
            "exec(compile(sys.argv[1],'<fixed-container-capture>','exec'))"
        )

    def test_reference_capture_reports_empty_failed_and_wrong_source_without_raw_output(self):
        cases = (
            ("import sys; sys.stdin.buffer.read(); sys.stderr.write('private error');",
             None, True, 0, 0, len(b"private error")),
            ("import sys; sys.stdin.buffer.read(); sys.stdout.write('private output'); "
             "sys.stderr.write('private error'); sys.exit(2)",
             None, True, 2, len(b"private output"), len(b"private error")),
            ("raise AssertionError('must not execute Ruff')", b"different source",
             False, None, 0, 0),
        )
        for formatter, source, matched, status, out_bytes, err_bytes in cases:
            runner = verifier.Phase5Verify(api_only=True)
            runner.environment = {"PATH": "/usr/bin:/bin"}
            bootstrap = self.reference_capture_bootstrap(formatter, source)
            child = "import sys; " + bootstrap.replace("sys.argv[1]", "sys.argv[-1]")
            runner.base = [sys.executable, "-I", "-B", "-c", child]
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                runner.reference_format_diff()
            rows = [json.loads(line) for line in stdout.getvalue().splitlines()]
            self.assertEqual(rows[0], {
                "check": "api_reference_formatter_capture", "status": "unavailable",
                "file": verifier.ReferenceFormatDiffOutput.FILE, "source_match": matched,
                "returncode": status, "stdout_bytes": out_bytes, "stderr_bytes": err_bytes,
            })
            self.assertEqual(rows[1]["reason"], "formatter_capture")
            self.assertNotIn("private", stdout.getvalue())
            self.assertEqual(runner.active, set())

    def test_reference_capture_metric_projection_rejects_extra_fields_and_nonfixed_values(self):
        valid = {"source_match": True, "returncode": 0, "stdout_bytes": 0, "stderr_bytes": 0}
        for change in ({"source_match": "private"}, {"returncode": True},
                       {"stdout_bytes": -1}, {"stderr_bytes": 65538}, {"secret": "private"}):
            output = verifier.ReferenceFormatDiffOutput()
            output.feed(output.CAPTURE_MARKER + json.dumps(dict(valid, **change)).encode() + b"\n")
            with self.assertRaises(verifier.Unavailable):
                output.finish()
            self.assertIsNone(output.capture)
            self.assertIsNone(output.diff)
            self.assertEqual(output.reason, "capture_diagnostic_invalid")

    def test_reference_format_diff_rejects_invalid_command_output_without_raw_printing(self):
        runner = verifier.Phase5Verify(api_only=True)

        def compose(*args, **kwargs):
            kwargs["output"].feed(b"private command output\n")
            kwargs["output"].finish()

        runner.compose = compose
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            runner.reference_format_diff()
        self.assertEqual(json.loads(stdout.getvalue()), {
            "check": "api_reference_format_diff", "status": "unavailable",
            "file": verifier.ReferenceFormatDiffOutput.FILE,
            "reason": "python_syntax",
            "shape": verifier.ReferenceFormatDiffOutput.source_shape(b"private command output\n"),
        })

    def test_reference_formatter_nonzero_status_never_emits_validated_source(self):
        runner = verifier.Phase5Verify(api_only=True)

        def compose(*args, **kwargs):
            kwargs["output"].feed(self.reference_formatted())
            kwargs["output"].finish()
            raise verifier.Unavailable()

        runner.compose = compose
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            runner.reference_format_diff()
        self.assertEqual(json.loads(stdout.getvalue()), {
            "check": "api_reference_format_diff", "status": "unavailable",
            "file": verifier.ReferenceFormatDiffOutput.FILE, "reason": "command_failed",
            "shape": verifier.ReferenceFormatDiffOutput.source_shape(self.reference_formatted()),
        })

    def test_focused_pdf_tests_use_the_centrally_registered_existing_chat_fixture(self):
        # Preserve actual fixture discovery rather than deleting an import solely
        # to silence F811. API runtime collection is coordinator-owned.
        central = ast.parse((ROOT / "api/tests/conftest.py").read_bytes())
        plugins = next(ast.literal_eval(node.value) for node in central.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "pytest_plugins"
                               for target in node.targets))
        self.assertEqual(plugins, ("test_chat",))
        shared = ast.parse((ROOT / "api/tests/test_chat.py").read_bytes())
        fixture = next(node for node in shared.body
                       if isinstance(node, ast.FunctionDef) and node.name == "chat_setup")
        self.assertTrue(any(isinstance(node, ast.Attribute)
                            and isinstance(node.value, ast.Name) and node.value.id == "pytest"
                            and node.attr == "fixture" for node in fixture.decorator_list))
        for relative in ("tests/test_chat_receipts.py", "tests/test_chat_references.py"):
            tree = ast.parse((ROOT / "api" / relative).read_bytes())
            self.assertFalse(any(isinstance(node, ast.ImportFrom)
                                 and any(alias.name == "chat_setup" for alias in node.names)
                                 for node in tree.body))
            self.assertTrue(any(isinstance(node, ast.FunctionDef)
                                and any(arg.arg == "chat_setup" for arg in node.args.args)
                                for node in tree.body))

    def test_outage_assertion_projects_actual_source_line_and_fixed_stage_without_values(self):
        diagnostic = diagnostic_module()
        plugin = diagnostic.DiagnosticPlugin(ROOT / "api")
        output = verifier.FocusedTestOutput()
        self.assertEqual(diagnostic.OUTAGE_TEST, output.OUTAGE_TEST)
        self.assertEqual(diagnostic.OUTAGE_ASSERTION_STAGES, output.OUTAGE_ASSERTION_STAGES)
        filename, test = diagnostic.OUTAGE_TEST
        tree = ast.parse((ROOT / "api" / filename).read_bytes())
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == test)
        assertions = sorted((node for node in ast.walk(function) if isinstance(node, ast.Assert)),
                            key=lambda node: node.lineno)
        # A real exception with the exact code filename/name/line; neither exception
        # text nor the test frame's private local is formatted or transported.
        for assertion, stage in zip(assertions, diagnostic.OUTAGE_ASSERTION_STAGES):
            body = ast.parse("raise AssertionError('private PDF/account data')").body[0]
            ast.increment_lineno(body, assertion.lineno - 1)
            isolated = ast.FunctionDef(
                name=test,
                args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[],
                                   defaults=[]),
                body=[body], decorator_list=[],
            )
            module = ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[]))
            namespace = {}
            exec(compile(module, str(ROOT / "api" / filename), "exec"), namespace)
            try:
                namespace[test]()
            except AssertionError as error:
                value = plugin.project(f"{filename}::{test}", "call", SimpleNamespace(
                    type=type(error), value=error,
                ))
            self.assertEqual(value["line"], assertion.lineno)
            self.assertEqual(value["stage"], stage)
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                output.feed(output.MARKER + json.dumps(value).encode() + b"\n")
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(output.findings[-1], dict(value, category="assertion"))
            self.assertNotIn("private", json.dumps(output.findings))

    def test_outage_line_projection_rejects_spoofed_lines_stages_and_extra_fields(self):
        output = verifier.FocusedTestOutput()
        filename, test = output.OUTAGE_TEST
        line, stage = next(iter(output.outage_assertions.items()))
        value = dict(file=filename, test=test, phase="call", stage=stage,
                     exception="AssertionError", detail="unknown", line=line)
        for change in (
            {"line": 987654}, {"line": True}, {"line": "private line"},
            {"stage": "private stage"}, {"stage": "submission_retained"},
            {"phase": "setup"}, {"exception": "KeyError"}, {"test": "test_private"},
            {"secret": "private data"},
        ):
            with self.subTest(change=change):
                invalid = verifier.FocusedTestOutput()
                invalid.feed(invalid.MARKER + json.dumps(dict(value, **change)).encode() + b"\n")
                self.assertIn("diagnostic_invalid", invalid.reasons)
                self.assertEqual(invalid.findings, [
                    {"file": "unknown", "test": "unknown", "category": "unknown"},
                ])

    def test_outage_hook_line_diagnostic_preserves_the_actual_failed_report(self):
        diagnostic = diagnostic_module()
        plugin = diagnostic.DiagnosticPlugin(ROOT / "api")
        filename, test = diagnostic.OUTAGE_TEST
        line, (start, stage) = next(iter(plugin.outage_assertions.items()))
        error = SimpleNamespace(__traceback__=SimpleNamespace(
            tb_frame=SimpleNamespace(f_code=SimpleNamespace(
                co_name=test, co_filename=str(ROOT / "api" / filename),
            ), f_locals={"private": "private payload"}), tb_lineno=line, tb_next=None,
        ))
        terminal = Mock()
        plugin.pytest_configure(SimpleNamespace(pluginmanager=SimpleNamespace(
            getplugin=lambda _: terminal,
        )))
        report = SimpleNamespace(failed=True, when="call", user_properties=[],
                                 longrepr="private assertion traceback not read")
        hook = plugin.pytest_runtest_makereport(
            SimpleNamespace(nodeid=f"{filename}::{test}"),
            SimpleNamespace(excinfo=SimpleNamespace(type=AssertionError, value=error)),
        )
        next(hook)
        with self.assertRaises(StopIteration):
            hook.send(SimpleNamespace(get_result=lambda: report))
        plugin.pytest_runtest_logreport(report)
        marker = terminal.write_line.call_args.args[0]
        output = verifier.FocusedTestOutput()
        output.feed(marker.encode() + b"\n")
        output.feed(b"=================== 1 failed in 0.1s ===================\n")
        self.assertEqual(output.findings[0]["line"], start)
        self.assertEqual(output.findings[0]["stage"], stage)
        self.assertIn("tests_failed", output.reasons)
        self.assertTrue(report.failed)
        self.assertEqual(report.longrepr, "private assertion traceback not read")
        self.assertNotIn("private", marker)

    def test_shared_fake_poll_requires_a_retained_start_and_does_not_send(self):
        # Exercise the actual test double without importing API/pytest/DB packages
        # absent on the host. Only this dependency-free class is executed.
        import uuid

        tree = ast.parse((ROOT / "api/tests/test_chat.py").read_bytes())
        broker_class = next(node for node in tree.body
                            if isinstance(node, ast.ClassDef) and node.name == "FakeBroker")
        namespace = {
            "uuid": uuid, "digest": digest, "resolved_prompt_text": resolved_prompt_text,
            "manifest_digest": verifier.manifest_digest,
        }
        exec(compile(ast.Module(body=[broker_class], type_ignores=[]),
                     "<shared-fake-broker>", "exec"), namespace)
        broker = namespace["FakeBroker"]()
        poll = {"op": "poll", "after": 0}
        self.assertFalse(broker.call(poll)["known"])
        payload = resolved()
        broker.call({"op": "start", "payload": payload, "epoch": broker.epoch,
                     **{key: str(uuid.uuid4()) for key in
                        ("project_id", "conversation_id", "turn_id")}})
        calls = len(broker.calls)
        for _ in range(2):
            reply = broker.call(poll)
            self.assertTrue(reply["known"])
            self.assertFalse(reply["stopped"])
        self.assertTrue(all(call["op"] == "poll" for call in broker.calls[calls:]))
        self.assertEqual(sum(call["op"] == "start" for call in broker.calls), 1)
        self.assertFalse(any(call["op"] == "reply" for call in broker.calls))
        broker.known = False
        self.assertFalse(broker.call(poll)["known"])

    def test_focused_test_output_projects_only_source_known_names_and_fixed_categories(self):
        output = verifier.FocusedTestOutput()
        filename = "tests/test_chat.py"
        test = "test_committed_idempotency_reservation_ordered_replay_and_restart"
        rows = (
            f"FAILED {filename}::{test}[private-param] - AssertionError: private-value\n"
            f"ERROR {filename}::{test} - sqlalchemy.exc.IntegrityError: private-db-value\n"
            f"FAILED {filename}::{test} - ImportError: private-import-value\n"
            f"FAILED {filename}::{test} - NameError: private-name-value\n"
            f"FAILED {filename}::{test} - UnexpectedPrivateError: private-unknown-value\n"
            f"FAILED {filename}::test_unapproved - NameError: private-name\n"
            "FAILED tests/test_secret.py::test_secret - AssertionError: secret\n"
            "=================== 3 failed, 1 error in 1.0s ===================\n"
        ).encode()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            for offset in range(0, len(rows), 13):
                output.feed(rows[offset : offset + 13])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(output.reasons, {"tests_failed", "test_errors"})
        self.assertEqual(
            output.findings,
            [
                {"file": filename, "test": test, "category": "assertion"},
                {"file": filename, "test": test, "category": "db"},
                {"file": filename, "test": test, "category": "import"},
                {"file": filename, "test": test, "category": "name"},
                {"file": filename, "test": test, "category": "unknown"},
            ],
        )
        for row in output.findings:
            self.assertNotIn("private", json.dumps(row))

    def test_postgres_hook_projects_only_known_chat_tests_and_fixed_stages(self):
        diagnostic = diagnostic_module()
        plugin = diagnostic.DiagnosticPlugin(ROOT / "api")
        filename = "tests/test_chat_postgres.py"
        test = "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads"
        error = AssertionError("private assertion data")
        value = plugin.project(f"{filename}::{test}", "call", SimpleNamespace(
            type=type(error), value=error,
        ))
        self.assertEqual(value["stage"], "pg_turn_reservation_concurrency")
        output = verifier.PostgresOutput()
        output.feed(output.MARKER + json.dumps(value).encode() + b"\n")
        self.assertEqual(output.findings, [{
            "file": filename, "test": test, "phase": "call",
            "stage": "pg_turn_reservation_concurrency", "detail": "unknown",
            "category": "assertion",
        }])
        invalid = dict(value, stage="private stage")
        output.feed(output.MARKER + json.dumps(invalid).encode() + b"\n")
        self.assertEqual(len(output.findings), 2)
        self.assertEqual(output.findings[-1], {"stage": "unknown", "category": "unexpected"})
        self.assertNotIn("private assertion data", json.dumps(output.findings))
        self.assertIsNone(plugin.project(f"{filename}::test_unknown", "call", SimpleNamespace(
            type=type(error), value=error,
        )))
        self.assertEqual(diagnostic.POSTGRES_TEST_STAGES, verifier.PG_TEST_STAGES)
        self.assertEqual(diagnostic.POSTGRES_TEST_SUBSTAGES, verifier.PG_TEST_SUBSTAGES)

    def test_postgres_hook_reads_only_fixed_local_substage_for_concurrency_test(self):
        diagnostic = diagnostic_module()
        plugin = diagnostic.DiagnosticPlugin(ROOT / "api")
        filename = "tests/test_chat_postgres.py"
        test = "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads"
        error = AssertionError("private assertion data")

        class Frame:
            f_code = SimpleNamespace(
                co_filename=str(ROOT / "api/tests/test_chat_postgres.py"), co_name=test,
            )
            f_locals = {"imp018_diagnostic_stage": "capture_delete_race"}

        class Traceback:
            tb_frame = Frame()
            tb_next = None

        traced_error = SimpleNamespace(__traceback__=Traceback())
        value = plugin.project(f"{filename}::{test}", "call", SimpleNamespace(
            type=type(error), value=traced_error,
        ))
        self.assertEqual(value["stage"], "capture_delete_race")
        traced_error.__traceback__.tb_frame.f_locals[
            "imp018_diagnostic_stage"
        ] = "private value"
        value = plugin.project(f"{filename}::{test}", "call", SimpleNamespace(
            type=type(error), value=traced_error,
        ))
        self.assertEqual(value["stage"], "pg_turn_reservation_concurrency")
        self.assertNotIn("private value", json.dumps(value))

    def test_capture_delete_hook_measures_fixed_pair_on_pass_and_failure_without_bodies(self):
        diagnostic = diagnostic_module()
        self.assertEqual(diagnostic.CAPTURE_DELETE_STATUSES, verifier.CAPTURE_DELETE_STATUSES)
        self.assertEqual(diagnostic.CAPTURE_DELETE_PAIRS, verifier.CAPTURE_DELETE_PAIRS)
        for failed, statuses, outcome in (
            (False, (202, 409), "captured_then_conflict"),
            (False, (404, 204), "deleted_then_notfound"),
            (False, (409, 204), "fenced_then_conflict"),
            (False, (409, 202), "queued_cleanup"),
            (True, (202, 204), "other"),  # A reproduced unsafe capture is NOT hidden.
            (True, (503, 500), "other"),
            (True, ("private response", 987654), "other"),
        ):
            with self.subTest(statuses=statuses):
                plugin = diagnostic.DiagnosticPlugin(ROOT / "api")
                terminal = Mock()
                plugin.pytest_configure(SimpleNamespace(pluginmanager=SimpleNamespace(
                    getplugin=lambda _: terminal,
                )))
                pair = diagnostic.fixed_capture_delete_pair(*statuses)
                self.assertEqual(pair["outcome"], outcome)
                report = SimpleNamespace(
                    failed=failed, when="call", nodeid=(
                        "tests/test_chat_postgres.py::"
                        "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads"
                    ), user_properties=[(diagnostic.CAPTURE_DELETE_PROPERTY, pair)],
                    longrepr="private response/traceback not read",
                )
                plugin.pytest_runtest_logreport(report)
                marker = terminal.write_line.call_args.args[0]
                self.assertNotIn("private", marker)
                output = verifier.PostgresOutput()
                for offset in range(0, len(marker), 7):
                    output.feed(marker[offset:offset + 7].encode())
                output.feed(b"\n")
                self.assertEqual(output.capture_delete, [pair])
                self.assertEqual(report.failed, failed)
                self.assertEqual(report.longrepr, "private response/traceback not read")
                plugin.pytest_runtest_logreport(report)
                terminal.write_line.assert_called_once()  # Bounded, one observation.

    def test_capture_delete_projection_rejects_arbitrary_or_mislabeled_records(self):
        for pair in (
            {"capture": "private body", "delete": 204, "outcome": "other"},
            {"capture": 987654, "delete": 204, "outcome": "other"},
            {"capture": 409, "delete": 204, "outcome": "private category"},
            {"capture": 202, "delete": 204, "outcome": "captured_then_conflict"},
            {"capture": True, "delete": 204, "outcome": "other"},
            {"capture": 409, "delete": 204, "outcome": "fenced_then_conflict",
             "body": "private response"},
        ):
            output = verifier.PostgresOutput()
            output.feed(output.CAPTURE_DELETE_MARKER + json.dumps(pair).encode() + b"\n")
            self.assertEqual(output.capture_delete, [])
            self.assertEqual(output.findings, [{
                "stage": "capture_delete_race", "category": "unexpected",
            }])
            self.assertNotIn("private", json.dumps(output.findings))

    def test_capture_delete_pair_does_not_replace_a_failed_postgres_assertion(self):
        output = verifier.PostgresOutput()
        output.feed(output.CAPTURE_DELETE_MARKER + json.dumps({
            "capture": 202, "delete": 204, "outcome": "other",
        }).encode() + b"\n")
        output.feed(b"=================== 1 failed, 2 passed in 0.1s ===================\n")
        with self.assertRaises(Exception):
            output.finish()
        self.assertFalse(output.passed)
        self.assertEqual(output.failure_category(), "test_failure")
        self.assertEqual(output.capture_delete, [{
            "capture": 202, "delete": 204, "outcome": "other",
        }])

    def test_actual_postgres_race_assertion_still_rejects_capture_plus_deletion(self):
        tree = ast.parse((ROOT / "api/tests/test_chat_postgres.py").read_bytes())
        test = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == (
                        "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads"
                    ))
        assertion = next(node for node in ast.walk(test) if isinstance(node, ast.Assert)
                         and isinstance(node.test, ast.Compare)
                         and isinstance(node.test.left, ast.Name) and node.test.left.id == "pair")
        code = compile(ast.Module(body=[assertion], type_ignores=[]),
                       "<actual-pg-capture-delete-assertion>", "exec")
        for pair in ((202, 409), (404, 204), (409, 204), (409, 202)):
            exec(code, {"pair": pair})
        for pair in ((202, 204), (202, 202), (404, 409), (503, 204), (500, 500)):
            with self.subTest(pair=pair), self.assertRaises(AssertionError):
                exec(code, {"pair": pair})

    def test_postgres_output_accepts_only_allowlisted_concurrency_substages(self):
        filename = "tests/test_chat_postgres.py"
        test = "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads"
        for stage in ("capture_delete_race", "purge_cleanup"):
            output = verifier.PostgresOutput()
            output.feed(output.MARKER + json.dumps({
                "file": filename, "test": test, "phase": "call", "stage": stage,
                "exception": "AssertionError", "detail": "unknown",
            }).encode() + b"\n")
            self.assertEqual(output.findings[0]["stage"], stage)
        output = verifier.PostgresOutput()
        output.feed(output.MARKER + json.dumps({
            "file": filename, "test": test, "phase": "call", "stage": "private value",
            "exception": "AssertionError", "detail": "unknown",
        }).encode() + b"\n")
        self.assertEqual(output.findings, [{"stage": "unknown", "category": "unexpected"}])

    def test_postgres_output_reports_bounded_counts_and_fixed_command_failure(self):
        output = verifier.PostgresOutput()
        output.feed(b"=================== 1 failed, 1 passed, 1 skipped, 2 warnings in 1.2s ===================\n")
        self.assertEqual(output.counts, {
            "passed": 1, "failed": 1, "skipped": 1, "errors": 0, "warnings": 2,
        })
        self.assertTrue(output.summary_seen)
        self.assertFalse(output.passed)
        self.assertEqual(output.failure_category(), "test_failure")
        output = verifier.PostgresOutput()
        output.feed(b"private command output\n")
        self.assertEqual(output.failure_category(), "summary_missing")
        self.assertEqual(output.counts["passed"], 0)

    def test_postgres_check_emits_only_fixed_failure_counts_and_stage(self):
        runner = verifier.Phase5Verify(api_only=True)
        runner.base = ["-f", "compose.yaml"]
        runner.postgres_owner_overlay = Path("/tmp/owned/postgres-owner.compose.yaml")
        runner.stage = lambda _: None
        finding = {
            "file": "tests/test_chat_postgres.py",
            "test": "test_postgres_two_submitters_reserve_one_committed_turn_and_preserve_heads",
            "phase": "call", "stage": "pg_turn_reservation_concurrency",
            "exception": "AssertionError", "detail": "unknown",
        }

        def fail_after_capture(_args, *, output, **_kwargs):
            output.feed(output.MARKER + json.dumps(finding).encode() + b"\n")
            output.feed(b"=================== 1 failed, 2 passed in 0.1s ===================\n")
            output.finish()

        runner.command = Mock(side_effect=fail_after_capture)
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            with self.assertRaises(Exception):
                runner.postgres_check()
        row = json.loads(stdout.getvalue())
        self.assertEqual(row["check"], "api_fresh_postgres_diagnostic")
        self.assertEqual(row["counts"], {
            "passed": 2, "failed": 1, "skipped": 0, "errors": 0, "warnings": 0,
        })
        self.assertEqual(row["command_failure"], "test_failure")
        self.assertEqual(row["capture_delete"], [])
        self.assertEqual(row["findings"], [{
            "file": finding["file"], "test": finding["test"], "phase": "call",
            "stage": finding["stage"], "detail": "unknown", "category": "assertion",
        }])
        self.assertNotIn("private", stdout.getvalue())

    def test_postgres_owner_overlay_inherits_fresh_test_profile_and_only_overrides_owner_login(self):
        from imp017_intake_verify import postgres_owner_overlay

        overlay = postgres_owner_overlay(ROOT)
        self.assertIn("service: api-integration-check", overlay)
        self.assertIn("DB_USER: ${POSTGRES_USER:?Set POSTGRES_USER in fixture}", overlay)
        self.assertIn("DB_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in fixture}", overlay)
        self.assertNotIn("IMPOSTR_TEST_POSTGRES", overlay)
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn('IMPOSTR_TEST_POSTGRES: "1"', compose)
        postgres_test = (ROOT / "api/tests/test_chat_postgres.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("IMPOSTR_TEST_POSTGRES") != "1"', postgres_test)

    def test_hook_emits_actual_setup_exception_without_trace_or_private_fields(self):
        diagnostic = diagnostic_module()
        plugin = diagnostic.DiagnosticPlugin(ROOT / "api")
        terminal = Mock()
        plugin.pytest_configure(SimpleNamespace(pluginmanager=SimpleNamespace(
            getplugin=lambda _: terminal,
        )))
        namespace = {}
        exec(compile("def chat_setup():\n    raise KeyError('private account data')\n",
                     str(ROOT / "api/tests/test_chat.py"), "exec"), namespace)
        try:
            namespace["chat_setup"]()
        except KeyError as error:
            excinfo = SimpleNamespace(type=type(error), value=error)
        output = verifier.FocusedTestOutput()
        filename = "tests/test_chat_references.py"
        test = "test_ordered_capture_has_no_text_copies_and_dispatch_resolves_exact_bytes"
        report = SimpleNamespace(failed=True, when="setup", user_properties=[],
                                 longrepr="private traceback not read")
        hook = plugin.pytest_runtest_makereport(
            SimpleNamespace(nodeid=f"{filename}::{test}[private-param]"),
            SimpleNamespace(excinfo=excinfo),
        )
        next(hook)
        with self.assertRaises(StopIteration):
            hook.send(SimpleNamespace(get_result=lambda: report))
        plugin.pytest_runtest_logreport(report)
        marker = terminal.write_line.call_args.args[0]
        self.assertNotIn("private", marker)
        rows = (marker + "\n" + f"ERROR {filename}::{test}[private-param]\n").encode()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            for offset in range(0, len(rows), 7):
                output.feed(rows[offset:offset + 7])
            output.finish()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(output.findings, [{
            "file": filename, "test": test, "phase": "setup", "stage": "fixture_chat",
            "exception": "KeyError", "category": "key", "detail": "unknown",
        }])
        self.assertNotIn("private", json.dumps(output.findings))
        self.assertTrue(report.failed)
        self.assertEqual(report.longrepr, "private traceback not read")
        report.failed = False
        plugin.pytest_runtest_logreport(report)
        terminal.write_line.assert_called_once()
        report.failed = True
        plugin.emitted = 128
        plugin.pytest_runtest_logreport(report)
        terminal.write_line.assert_called_once()

    def test_hook_scopes_tests_and_projects_missing_fixture_and_db_shapes(self):
        diagnostic = diagnostic_module()
        plugin = diagnostic.DiagnosticPlugin(ROOT / "api")
        filename = "tests/test_chat_receipts.py"
        test = "test_lost_start_ack_reconciles_receipt_without_second_inference"
        fixture_error = type("FixtureLookupError", (Exception,), {})("private fixture name")
        info = SimpleNamespace(type=type(fixture_error), value=fixture_error)
        projected = plugin.project(f"{filename}::{test}", "setup", info)
        self.assertEqual(projected["exception"], "FixtureLookupError")
        self.assertEqual(projected["detail"], "fixture_missing")
        self.assertIsNone(plugin.project(f"{filename}::test_private", "setup", info))
        self.assertIsNone(plugin.project(f"tests/private.py::{test}", "setup", info))
        db_error = type("OperationalError", (Exception,), {})("private SQL not formatted")
        db_error.orig = Exception("no such table: private_table")
        info = SimpleNamespace(type=type(db_error), value=db_error)
        self.assertEqual(plugin.project(f"{filename}::{test}", "call", info)["detail"],
                         "table_missing")
        db_error.orig = Exception("table private_table has no column named private_column")
        self.assertEqual(plugin.project(f"{filename}::{test}", "call", info)["detail"],
                         "table_columns")
        db_error.orig = Exception("private other database failure")
        self.assertEqual(plugin.project(f"{filename}::{test}", "call", info)["detail"],
                         "unknown")
        self.assertEqual(plugin.emitted, 0)
        self.assertEqual(diagnostic.FOCUSED_FILES, verifier.FOCUSED_TESTS)
        self.assertEqual(set(diagnostic.STAGES.values()), set(verifier.FocusedTestOutput.TRACE_STAGES.values()))
        self.assertEqual(diagnostic.EXCEPTIONS, frozenset(verifier.FocusedTestOutput.EXCEPTION_CATEGORIES))

    def test_deleted_history_tied_timestamps_use_identity_and_project_index_error(self):
        diagnostic = diagnostic_module()
        plugin = diagnostic.DiagnosticPlugin(ROOT / "api")
        filename = "tests/test_chat_references.py"
        test = "test_deleted_history_explicitly_retained_and_dispatches_unavailable_metadata"
        # SQLite CURRENT_TIMESTAMP can tie, leaving UUID order to put the empty
        # continuation before the original. Execute the actual corrected test
        # assertion on that response without importing unavailable API packages.
        history = {"turns": [
            {"id": "continuation", "references": []},
            {"id": "original", "references": [{"availability": "unavailable"}]},
        ]}
        try:
            history["turns"][0]["references"][0]["availability"]
        except IndexError as error:
            value = plugin.project(f"{filename}::{test}", "call", SimpleNamespace(
                type=type(error), value=error,
            ))
        output = verifier.FocusedTestOutput()
        output.feed(output.MARKER + json.dumps(value).encode() + b"\n")
        self.assertEqual(output.findings, [{
            "file": filename, "test": test, "phase": "call", "stage": "test_call",
            "exception": "IndexError", "category": "index", "detail": "unknown",
        }])
        tree = ast.parse((ROOT / "api" / filename).read_bytes())
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == test)
        assignment = next(node for node in function.body
                          if isinstance(node, ast.Assign)
                          and isinstance(node.targets[0], ast.Name)
                          and node.targets[0].id == "original_history")
        position = function.body.index(assignment)
        assertion = function.body[position + 1]
        self.assertIsInstance(assertion, ast.Assert)
        exec(compile(ast.Module(body=[assignment, assertion], type_ignores=[]),
                     "<deleted-history-assertion>", "exec"),
             {"history": history, "original": "original"})
        with self.assertRaises(AssertionError):
            history["turns"][1]["references"][0]["availability"] = "available"
            exec(compile(ast.Module(body=[assignment, assertion], type_ignores=[]),
                         "<deleted-history-assertion>", "exec"),
                 {"history": history, "original": "original"})

    def test_marker_projection_prioritizes_all_new_reports_after_summary_saturation(self):
        output = verifier.FocusedTestOutput()
        for filename, names in output.test_names.items():
            for test in sorted(names):
                output.feed(f"FAILED {filename}::{test}\n".encode())
                if filename not in {"tests/test_chat_receipts.py", "tests/test_chat_references.py"}:
                    for phase in ("setup", "call", "teardown"):
                        value = {"file": filename, "test": test, "phase": phase,
                                 "stage": "test_" + phase, "exception": "AssertionError",
                                 "detail": "unknown"}
                        output.feed(output.MARKER + json.dumps(value).encode() + b"\n")
        self.assertEqual(len(output.findings), output.MAX_FINDINGS)
        direct = []
        for filename in ("tests/test_chat_receipts.py", "tests/test_chat_references.py"):
            for test in sorted(output.test_names[filename]):
                value = {"file": filename, "test": test, "phase": "setup",
                         "stage": "test_setup", "exception": "FixtureLookupError",
                         "detail": "fixture_missing"}
                direct.append(value)
                output.feed(output.MARKER + json.dumps(value).encode() + b"\n")
        self.assertGreater(len(direct), 16)
        self.assertEqual(output.findings[:len(direct)], [
            dict(row, category="fixture") for row in direct
        ])
        self.assertLessEqual(len(output.findings), output.MAX_FINDINGS)
        before = output.findings.copy()
        invalid = dict(direct[0], stage="private stage")
        output.feed(output.MARKER + json.dumps(invalid).encode() + b"\n")
        output.feed(output.MARKER + json.dumps(dict(direct[0], secret="private")).encode() + b"\n")
        self.assertEqual(output.findings, before)
        self.assertIn("diagnostic_invalid", output.reasons)
        self.assertNotIn("private stage", json.dumps(output.findings))
        self.assertNotIn('"secret"', json.dumps(output.findings))

    def test_raw_trace_and_runtime_prompt_output_are_not_interpreted(self):
        output = verifier.FocusedTestOutput()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            output.feed(b'E   NameError: private value\n{"diagnostic":"unavailable"}\n')
            output.finish()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(output.findings, [
            {"file": "unknown", "test": "unknown", "category": "unknown"},
        ])
        self.assertEqual(output.buffer, b"")

    def test_focused_api_opts_in_to_hook_without_relaxing_output_suppression(self):
        runner = verifier.Phase5Verify(api_only=True)
        runner.compose = Mock()
        runner.postgres_check = Mock()
        runner.stage = lambda _: None
        with patch("sys.stdout", new_callable=io.StringIO):
            runner.focused_api()
        pytest_call = next(
            call for call in runner.compose.call_args_list if "pytest" in call.args
        )
        self.assertIn("--imp018-diagnostics", pytest_call.args)
        self.assertIn("--tb=no", pytest_call.args)
        self.assertIn("--show-capture=no", pytest_call.args)
        self.assertIn("--color=no", pytest_call.args)
        self.assertIsInstance(pytest_call.kwargs["output"], verifier.FocusedTestOutput)

    def test_api_only_prepare_bypasses_sibling_lifecycle_prepare_and_pdf_overlay(self):
        runner = verifier.Phase5Verify(api_only=True)
        runner.base = ["-f", "compose.yaml", "-f", "compose.chat-synthetic.yaml"]
        runner.stage = lambda _: None
        with patch.object(verifier.Verify, "prepare") as base_prepare, \
                patch.object(runner, "prepare_chat_connection") as chat_prepare, \
                patch.object(runner, "write_postgres_owner_overlay"), \
                patch.object(verifier.NormalVerify, "prepare") as normal_prepare, \
                patch.object(verifier.LifecycleVerify, "prepare") as lifecycle_prepare:
            runner.prepare()
        base_prepare.assert_called_once_with(runner)
        chat_prepare.assert_called_once_with()
        normal_prepare.assert_not_called()
        lifecycle_prepare.assert_not_called()
        self.assertNotIn("compose.pdf-app.yaml", runner.base)
        self.assertIsNone(runner.pdf_overlay)

    def test_api_only_overlay_writer_does_not_create_pdf_overlay_or_service(self):
        runner = verifier.Phase5Verify(api_only=True)
        runner.base = ["-f", "compose.yaml"]
        runner.write_phase5_overlay()
        self.assertEqual(runner.base, ["-f", "compose.yaml"])
        self.assertIsNone(runner.pdf_overlay)

    def test_api_only_run_never_starts_broker_or_pdf_provenance_runtime(self):
        runner = verifier.Phase5Verify(api_only=True)
        runner.prepare = Mock()
        runner.start_broker = Mock()
        runner.focused_api = Mock()
        runner.ensure_extractor = Mock()
        runner.cleanup = Mock(return_value=True)
        with patch.object(verifier, "require_source_mapping"), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(runner.run(), 0)
        runner.prepare.assert_called_once_with()
        runner.focused_api.assert_called_once_with()
        runner.start_broker.assert_not_called()
        runner.ensure_extractor.assert_not_called()
        runner.cleanup.assert_called_once_with()

    def test_full_pdf_channel_overlay_has_no_converter_dependency_before_provenance(self):
        import tempfile

        runner = verifier.Phase5Verify(api_only=False)
        runner.base = ["-f", "compose.yaml"]
        with tempfile.TemporaryDirectory(prefix="imp018-compose-test-") as directory:
            runner.inputs = Path(directory)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            runner.directories[runner.inputs] = fd
            try:
                runner.write_phase5_overlay()
                overlay = runner.pdf_overlay.read_text(encoding="ascii")
            finally:
                os.close(fd)
        self.assertIn("IMPOSTR_PDF_ENABLED", overlay)
        self.assertNotIn("pdf-channel:", overlay)
        self.assertNotIn("pdf-extractor:", overlay)
        self.assertNotIn("depends_on:", overlay)
        self.assertNotIn("compose.pdf-app.yaml", runner.base)

    def test_full_attaches_converter_only_after_immutable_provenance_and_pins_last(self):
        class StopBeforeCompose(RuntimeError):
            pass

        runner = verifier.Phase5Verify(api_only=False)
        runner.inputs = Path("/tmp/imp018-owned-fixture")
        runner.base = ["-f", "compose.yaml", "-f", "phase5-overlay.yaml"]
        runner.stage = lambda _: None
        events = []
        pinned_path = runner.inputs / "extractor-pinned.compose.yaml"

        def ensure():
            events.append("immutable-provenance-verified")
            runner.extractor_image = "sha256:" + "a" * 64
            runner.base += ["-f", str(pinned_path)]

        def compose(*args, **kwargs):
            events.append(("compose", args, tuple(runner.base)))
            raise StopBeforeCompose()

        runner.ensure_extractor = ensure
        runner.compose = compose
        with self.assertRaises(StopBeforeCompose):
            runner.run_full()
        self.assertEqual(events[0], "immutable-provenance-verified")
        action = events[1]
        self.assertEqual(action[0], "compose")
        self.assertEqual(action[1][:5], ("create", "--no-build", "--pull", "never", "pdf-extractor"))
        base = action[2]
        self.assertLess(base.index(str(verifier.ROOT / "compose.pdf-app.yaml")),
                        base.index(str(pinned_path)))
        self.assertEqual(base[-2:], ("-f", str(pinned_path)))

    def test_owner_postgres_command_includes_exact_generated_overlay_and_fails_closed(self):
        runner = verifier.Phase5Verify(api_only=True)
        runner.base = ["-f", "compose.yaml"]
        runner.postgres_owner_overlay = Path("/tmp/owned/postgres-owner.compose.yaml")
        runner.stage = lambda _: None

        def execute(args, *, output, **_):
            output.feed(b"=================== 3 passed in 0.1s ===================\n")
            output.finish()

        runner.command = Mock(side_effect=execute)
        runner.postgres_check()
        args = runner.command.call_args.args[0]
        overlay_index = args.index(str(runner.postgres_owner_overlay))
        self.assertEqual(args[overlay_index - 1], "-f")
        self.assertEqual(args[overlay_index + 1:overlay_index + 4],
                         ["run", "--build", "--rm"])
        self.assertIn(verifier.POSTGRES_OWNER_SERVICE, args)
        self.assertTrue(runner.compose_used)

        runner.postgres_owner_overlay = None
        runner.command.reset_mock()
        with patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaises(Exception):
                runner.postgres_check()
        runner.command.assert_not_called()

    def test_full_boundary_mode_requires_an_explicit_review_marker(self):
        with patch("sys.argv", ["imp018_verify.py", "--full"]), \
                redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                verifier.main()
        self.assertEqual(caught.exception.code, 2)
        with patch("sys.argv", ["imp018_verify.py", "--api-only", "--reviewed-full"]), \
                redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                verifier.main()
        self.assertEqual(caught.exception.code, 2)

    def test_postgres_output_requires_all_expected_tests_and_projects_fixed_diagnostics(self):
        output = verifier.PostgresOutput()
        output.feed(
            b'{"diagnostic":"imp017_intake_postgres","stage":"schema_types",'
            b'"category":"database","detail":"private value"}\n'
        )
        output.feed(b"=================== 3 passed, 1 warning in 0.1s ===================\n")
        with self.assertRaises(Exception):
            output.finish()
        self.assertTrue(output.passed)
        self.assertEqual(output.findings, [{"stage": "schema_types", "category": "database"}])

        output = verifier.PostgresOutput()
        output.feed(b"=================== 3 passed in 0.1s ===================\n")
        output.finish()
        self.assertTrue(output.passed)

    def test_owner_postgres_command_enables_fixed_hook_without_changing_overlay_scope(self):
        runner = verifier.Phase5Verify(api_only=True)
        runner.base = ["-f", "compose.yaml"]
        runner.postgres_owner_overlay = Path("/tmp/owned/postgres-owner.compose.yaml")
        runner.stage = lambda _: None
        runner.command = Mock(side_effect=lambda args, *, output, **_: (
            output.feed(b"=================== 3 passed in 0.1s ===================\n"),
            output.finish(),
        ))
        runner.postgres_check()
        args = runner.command.call_args.args[0]
        pytest_args = args[args.index("pytest"):]
        self.assertIn("--imp018-diagnostics", pytest_args)
        self.assertIn("--show-capture=no", pytest_args)
        self.assertEqual(pytest_args[-2:], list(verifier.PG_TESTS))

    def test_head_output_ignores_ancillary_lines_and_accepts_a_split_exact_head(self):
        output = verifier.HeadOutput()
        output.feed(b"INFO [alembic.runtime.migration] Context impl PostgresqlImpl.\r\n")
        output.feed(b"20261002_00")
        output.feed(b"10 (head)\nINFO [alembic.runtime.migration] Running upgrade\n")
        output.finish()
        for body in (
            b"INFO [alembic.runtime.migration] Context impl PostgresqlImpl.\n",
            b"20261002_0009 (head)\n",
        ):
            output = verifier.HeadOutput()
            output.feed(body)
            with self.assertRaises(Exception):
                output.finish()

    def test_failed_acceptance_does_not_misreport_successful_owned_cleanup(self):
        runner = verifier.Phase5Verify(api_only=True)
        runner.prepare = Mock()
        runner.focused_api = Mock(side_effect=RuntimeError("synthetic failure"))
        runner.cleanup = Mock(return_value=True)
        with patch.object(verifier, "require_source_mapping"), \
                patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(runner.run(), 1)
        reports = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertIn(
            {"check": "imp018_stage", "status": "failed", "phase": "source_mapping"},
            reports,
        )
        self.assertIn({"check": "owned_cleanup", "status": "passed"}, reports)


class NativeInferenceFixtureTests(unittest.TestCase):
    def test_native_request_and_receipt_are_bound_to_exact_selected_reference(self):
        payload = resolved()
        data = native(payload)
        book = ledger(payload)
        submission = book.begin(json.dumps(data).encode())
        observed = []
        product = PDFNativeProduct(payload, observed, threading.Lock())
        output = list(product.events(data, threading.Event(), time.monotonic() + 2,
                                     submission=submission))
        submission.finish()
        self.assertTrue(output)
        self.assertEqual(book.snapshot()[0]["status"], "sent")
        self.assertEqual(observed[0]["rendered_sha256"], digest(resolved_prompt_text(payload)))
        self.assertEqual(observed[0]["reference_hashes"], (payload["references"][0]["reference"]["text_sha256"],))
        self.assertEqual(observed[0]["available"], 1)
        self.assertNotIn("PDF exact", json.dumps(observed))

    def test_before_write_partial_and_post_send_failures_keep_honest_receipts(self):
        expected = {
            "SYNTHETIC PDF FAIL BEFORE WRITE": ("failed-before-send", ValueError),
            "SYNTHETIC PDF PARTIAL WRITE": ("uncertain", OSError),
            "SYNTHETIC PDF POST-SEND FAILURE": ("sent", ValueError),
        }
        for prompt, (status, error) in expected.items():
            with self.subTest(status=status):
                payload = resolved()
                payload["prompt"] = prompt
                data = native(payload)
                book = ledger(payload)
                submission = book.begin(json.dumps(data).encode())
                submission.bind(data)
                product = PDFNativeProduct(payload, [], threading.Lock())
                with self.assertRaises(error):
                    list(product.events(data, threading.Event(), time.monotonic() + 2,
                                        submission=submission))
                submission.finish()
                self.assertEqual(book.snapshot()[0]["status"], status)

    def test_wait_for_delete_is_a_real_question_event_after_native_submission(self):
        payload = resolved()
        payload["prompt"] = "SYNTHETIC PDF WAIT FOR DELETE"
        data = native(payload)
        book = ledger(payload)
        submission = book.begin(json.dumps(data).encode())
        product = PDFNativeProduct(payload, [], threading.Lock())
        result = b"".join(product.events(data, threading.Event(), time.monotonic() + 2,
                                         submission=submission))
        submission.finish()
        self.assertIn(b"response.function_call_arguments.done", result)
        self.assertEqual(book.snapshot()[0]["status"], "sent")


class OwnedApiClientMethodTests(unittest.TestCase):
    def test_delete_uses_the_single_owned_loopback_request_without_retry(self):
        import test_imp024_http

        client = test_imp024_http.client_module.Client("http://127.0.0.1:12345")
        connection = test_imp024_http.Connection(test_imp024_http.wire(status=204, data={}))
        with patch.object(
            test_imp024_http.client_module.http.client,
            "HTTPConnection",
            return_value=connection,
        ):
            result = client.delete("/api/projects/synthetic/attachments/id", headers={
                "Origin": client.base_url,
                "X-CSRF-Token": "synthetic-csrf",
            })
        self.assertEqual(result.status_code, 204)
        self.assertEqual(connection.sent[0], "DELETE")
        self.assertIsNone(connection.sent[2])
        self.assertTrue(connection.closed)
        client.close()


if __name__ == "__main__":
    unittest.main()
