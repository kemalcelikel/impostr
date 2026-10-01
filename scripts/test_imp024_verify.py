"""Pure orchestration tests; no Docker, listeners, workers or private inputs."""

import ast
import io
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import imp024_verify as verify


class VerifyTests(unittest.TestCase):
    def test_approved_group_writable_scratch_keeps_new_inputs_private_and_channel_traversable(self):
        with TemporaryDirectory(prefix="imp024-scratch-test-", dir="/tmp/opencode") as directory:
            parent = Path(directory)
            parent.chmod(
                0o775
            )  # Only this test's synthetic directory, not the actual scratch parent.
            with patch.object(verify, "PARENT", parent), patch.object(
                verify.ctypes, "CDLL"
            ) as library, patch("sys.stdout", new_callable=io.StringIO) as output:
                library.return_value.prctl.return_value = 0
                instance = verify.Verify()
                try:
                    instance.prepare()  # Provision only; no Docker, broker or live credentials.
                    self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o775)
                    self.assertEqual(stat.S_IMODE(instance.inputs.stat().st_mode), 0o700)
                    self.assertEqual(stat.S_IMODE(instance.channel.stat().st_mode), 0o711)
                    self.assertEqual(
                        stat.S_IMODE((instance.inputs / "fixture.env").stat().st_mode), 0o600
                    )
                    self.assertEqual(instance.inputs.stat().st_uid, os.getuid())
                    instance.check_directories()
                    self.assertNotIn("PASSWORD", output.getvalue())
                    self.assertNotIn("RATE_LIMIT_KEY", output.getvalue())
                finally:
                    with patch.object(instance, "stop_broker"):
                        self.assertTrue(instance.cleanup())
                self.assertEqual(list(parent.iterdir()), [])

    def test_replaced_owned_input_path_is_rejected_without_removing_replacement(self):
        with TemporaryDirectory(prefix="imp024-scratch-test-", dir="/tmp/opencode") as directory:
            parent = Path(directory)
            with patch.object(verify, "PARENT", parent), patch.object(
                verify.ctypes, "CDLL"
            ) as library, patch("sys.stdout", new_callable=io.StringIO):
                library.return_value.prctl.return_value = 0
                instance = verify.Verify()
                instance.prepare()
                moved = instance.inputs.with_name(instance.inputs.name + "-moved")
                instance.inputs.rename(moved)
                instance.inputs.mkdir(mode=0o700)
                with self.assertRaises(verify.Unavailable):
                    instance.check_directories()
                with patch.object(instance, "stop_broker"):
                    self.assertFalse(instance.cleanup())
                self.assertTrue(instance.inputs.is_dir() and moved.is_dir())

    def test_fragmented_no_newline_prompts_only_dispatch_in_exact_order(self):
        action = Mock()
        parser = verify.Output(action)
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            parser.feed(b"raw credential never forwarded\n")
            for prompt in verify.PROMPTS:
                for offset in range(0, len(prompt), 7):
                    parser.feed(prompt[offset : offset + 7])
                parser.feed(("PASS " + verify.LIFECYCLE_PASSES[0] + "\n").encode())
            self.assertNotIn("credential", output.getvalue())
            self.assertNotIn("ACTION", output.getvalue())
        self.assertEqual([call.args[0] for call in action.call_args_list], list(range(5)))
        self.assertEqual(parser.next_prompt, 5)
        for raw in (verify.PROMPTS[1], b"prefix" + verify.PROMPTS[0]):
            with self.assertRaises(verify.Unavailable):
                verify.Output(action).feed(raw)

    def test_raw_assertions_json_and_unknown_passes_are_not_transported(self):
        parser = verify.Output()
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            parser.feed(b'FAIL secret\n{"private":"value"}\nPASS fake success\n')
            parser.feed(("PASS " + verify.OWNED_CLEANUP + "\n").encode())
            self.assertNotIn("secret", output.getvalue())
            self.assertNotIn("private", output.getvalue())
            self.assertNotIn("fake", output.getvalue())
        self.assertEqual(parser.passed, {verify.OWNED_CLEANUP})
        with self.assertRaises(verify.Unavailable):
            parser.feed(b"x" * (64 * 1024 + 1))

    def test_prompts_and_pass_markers_match_the_actual_preserved_harness(self):
        path = Path(__file__).resolve().parents[1] / "api/tests/imp024_joined.py"
        tree = ast.parse(path.read_bytes())
        prompts = []
        printed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.args:
                if node.func.id == "input":
                    prompts.append(ast.literal_eval(node.args[0]).encode())
                if node.func.id == "print" and isinstance(node.args[0], ast.Constant):
                    printed.add(node.args[0].value)
        self.assertEqual(tuple(prompts), verify.PROMPTS)
        for message in verify.CHECK_PASSES + verify.LIFECYCLE_PASSES + (verify.OWNED_CLEANUP,):
            self.assertIn("PASS " + message, printed)

    def test_reaping_never_signals_active_joined_cli_or_other_host_processes(self):
        with patch.object(
            verify, "adopted_children", side_effect=([11, 22], [11, 22], [11], [11], [11])
        ), patch.object(verify.os, "pidfd_open", return_value=8) as opened, patch.object(
            verify.signal, "pidfd_send_signal"
        ) as sent, patch.object(
            verify.os, "close"
        ):
            verify.reap_children(exclude={11})
        opened.assert_called_once_with(22)
        sent.assert_called_once_with(8, verify.signal.SIGKILL)

    def test_diagnostics_copy_only_fixed_fields_and_counts_never_child_secrets(self):
        value = {
            "diagnostic": "joined_turn",
            "state": "failed",
            "private": "secret",
            "failure_reasons": ["native_stream_timeout"],
            "calls": {
                op: {stage: 1 for stage in ("before", "after")}
                for op in ("start", "reply", "poll", "abort")
            },
        }
        parser = verify.Output()
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            parser.feed(json.dumps(value).encode() + b"\n")
            self.assertIn("native_stream_timeout", output.getvalue())
            self.assertNotIn("private", output.getvalue())
            self.assertNotIn("secret", output.getvalue())
        value["failure_reasons"] = ["secret"]
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            parser.feed(json.dumps(value).encode() + b"\n")
            self.assertNotIn("secret", output.getvalue())
            self.assertIn("unavailable", output.getvalue())

    def test_failed_gate_still_cleans_up_and_returns_nonzero(self):
        instance = verify.Verify()
        with patch.object(instance, "prepare"), patch.object(
            instance, "start_broker", side_effect=verify.Unavailable
        ), patch.object(instance, "cleanup", return_value=True) as cleanup, patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            self.assertEqual(instance.run(), 1)
        cleanup.assert_called_once()

    def test_fixed_check_categories_never_forward_paths_or_error_text(self):
        cases = (
            ("pytest", b"1 failed, 18 passed in 1s\n", "tests_failed"),
            ("ruff_lint", b"private/path.py:1:1: F401 sensitive detail\n", "lint_findings"),
            ("ruff_format", b"Would reformat: private/path.py\n", "format_mismatch"),
            ("mypy", b"private/path.py:1: error: sensitive detail\n", "type_errors"),
        )
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            for check, raw, reason in cases:
                parser = verify.CheckOutput(check)
                parser.feed(raw)
                self.assertEqual(parser.reasons, {reason})
            self.assertEqual(output.getvalue(), "")

    def test_ruff_json_projects_only_allowlisted_file_rule_and_line(self):
        raw = json.dumps(
            [
                {
                    "filename": "/app/tests/imp024_joined.py",
                    "code": "F401",
                    "location": {"row": 29, "column": 1},
                    "message": "private detail",
                    "source": "private snippet",
                    "fix": {"content": "private replacement"},
                }
            ]
        ).encode()
        parser = verify.RuffJsonOutput()
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            for offset in range(0, len(raw), 11):
                parser.feed(raw[offset : offset + 11])
            parser.finish()
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            parser.findings, [{"file": "tests/imp024_joined.py", "code": "F401", "line": 29}]
        )
        self.assertEqual(parser.reasons, {"lint_findings"})
        self.assertEqual(parser.buffer, b"")
        self.assertIn("--output-format", dict(verify.FOCUSED_CHECKS)["ruff_lint"])

    def test_ruff_json_rejects_unknown_paths_rule_strings_and_invalid_bounds(self):
        row = {"filename": "tests/test_chat.py", "code": "I001", "location": {"row": 1}}
        invalid = (
            {**row, "filename": "/private/secret.py"},
            {**row, "filename": "/app/tests/../tests/test_chat.py"},
            {**row, "code": "F401 private detail"},
            {**row, "location": {"row": True}},
            {**row, "location": {"row": 10001}},
        )
        for value in invalid:
            parser = verify.RuffJsonOutput()
            parser.feed(json.dumps([row, value]).encode())
            with self.assertRaises(verify.Unavailable):
                parser.finish()
            self.assertEqual(parser.findings, [])
            self.assertEqual(parser.buffer, b"")
        with self.assertRaises(verify.Unavailable):
            verify.RuffJsonOutput().feed(b"x" * (512 * 1024 + 1))

    def test_format_findings_report_only_fixed_allowlisted_paths(self):
        parser = verify.CheckOutput("ruff_format")
        parser.feed(b"Would reformat: tests/test_chat.py\nWould reformat: /private/secret.py\n")
        self.assertEqual(
            parser.findings, [{"file": "tests/test_chat.py", "code": "format_mismatch"}]
        )

    def test_inventory_ignores_stderr_warning_but_rejects_nonempty_stdout(self):
        # All subprocess/selector/pipe operations mocked; no Docker or child starts.
        process = Mock()
        process.stdout, process.stderr = Mock(), Mock()
        process.wait.return_value = 0
        process.poll.return_value = 0
        stdout, stderr = Mock(fileobj=process.stdout), Mock(fileobj=process.stderr)
        for blocks, succeeds in (
            ((b"warning from Docker\n", b"", b""), True),
            ((b"warning from Docker\n", b"", b"owned-resource-id\n"), False),
        ):
            selector = Mock()
            selector.get_map.side_effect = [True, True, True, False]
            selector.select.side_effect = [[(stderr, None)], [(stderr, None)], [(stdout, None)]]
            instance = verify.Verify()
            with patch.object(verify.subprocess, "Popen", return_value=process), patch.object(
                verify.selectors, "DefaultSelector", return_value=selector
            ), patch.object(verify.os, "read", side_effect=blocks):
                if succeeds:
                    instance.command(["synthetic"], output=verify.EmptyOutput())
                else:
                    with self.assertRaises(verify.Unavailable):
                        instance.command(["synthetic"], output=verify.EmptyOutput())

    def test_cleanup_reports_failed_stage_and_continues_remaining_cleanup(self):
        instance = verify.Verify()
        instance.compose_used = True
        with patch.object(instance, "stop_broker"), patch.object(
            instance, "compose"
        ) as compose, patch.object(
            instance, "command", side_effect=(verify.Unavailable(), None, None, None)
        ), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as output:
            self.assertFalse(instance.cleanup())
        compose.assert_called_once_with(
            "--profile",
            "checks",
            "--profile",
            "integration",
            "down",
            "-v",
            "--remove-orphans",
            "--rmi",
            "local",
        )
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertIn({"check": "cleanup_container_inventory", "status": "failed"}, lines)
        self.assertIn({"check": "cleanup_generated_inputs", "status": "passed"}, lines)


if __name__ == "__main__":
    unittest.main()
