"""Pure coordinator-harness parser tests; no Docker or private input access."""

import ast
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import imp017_intake_verify as intake
from imp024_verify import Unavailable


class IntakeHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = (Path(__file__).resolve().parents[1] / "web/nginx/default.conf").read_text()

    def test_upload_exception_is_exactly_scoped_and_keeps_general_api_limit(self):
        intake.validate_upload_route_config(self.config)

    def test_nginx_route_parser_rejects_upload_limit_leaking_to_other_routes(self):
        modified = self.config.replace(
            "client_max_body_size 1m;", "client_max_body_size 50000000;", 1
        )
        with self.assertRaises(Unavailable):
            intake.validate_upload_route_config(modified)

    def test_nginx_route_parser_rejects_missing_method_and_streaming_guards(self):
        for old, new in (
            ("limit_except POST { deny all; }", "limit_except GET { deny all; }"),
            ("proxy_request_buffering off;", "proxy_request_buffering on;"),
        ):
            with self.subTest(old=old):
                modified = self.config.replace(old, new, 1)
                with self.assertRaises(Unavailable):
                    intake.validate_upload_route_config(modified)

    def test_owner_credentials_are_placeholders_on_a_test_only_compose_service(self):
        overlay = intake.postgres_owner_overlay(Path("/synthetic/repository"))
        self.assertIn("api-integration-owner-check:", overlay)
        self.assertIn('file: "/synthetic/repository/compose.yaml"', overlay)
        self.assertIn("service: api-integration-check", overlay)
        self.assertIn(
            "DB_USER: ${POSTGRES_USER:?Set POSTGRES_USER in fixture}", overlay
        )
        self.assertIn(
            "DB_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in fixture}", overlay
        )
        self.assertNotIn("impostr_owner", overlay)
        self.assertNotIn("secret", overlay.lower())

    def test_prepare_writes_owned_overlay_and_inherited_cleanup_includes_its_image(self):
        class RecordingVerifier(intake.IntakeVerify):
            def __init__(self):
                super().__init__()
                self.commands = []

            def command(self, args, **kwargs):
                self.commands.append(args)
                output = kwargs.get("output")
                if output is not None and hasattr(output, "finish"):
                    output.finish()
                return output

        verifier = RecordingVerifier()
        with tempfile.TemporaryDirectory(prefix="imp017-overlay-test-") as name:
            inputs = Path(name)
            directory_fd = os.open(inputs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            verifier.inputs = inputs
            verifier.directories[inputs] = directory_fd
            verifier.write_postgres_owner_overlay()
            overlay = inputs / "postgres-owner.compose.yaml"
            self.assertEqual(verifier.postgres_owner_overlay, overlay)
            self.assertEqual(stat.S_IMODE(overlay.stat().st_mode), 0o600)
            self.assertIn("${POSTGRES_PASSWORD:", overlay.read_text())
            verifier.inputs = None
            verifier.base = ["docker", "compose", "-p", verifier.project, "-f", "compose.yaml"]
            verifier.compose_used = True
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertTrue(verifier.cleanup())

            down = next(command for command in verifier.commands if "down" in command)
            self.assertIn(str(overlay), down)
            self.assertIn("--rmi", down)
            self.assertIn("local", down)
            image_inventory = next(
                command
                for command in verifier.commands
                if command[:4] == ["docker", "--host", "unix:///var/run/docker.sock", "image"]
            )
            self.assertIn("reference=" + verifier.project + "-*", image_inventory)

    def test_only_fresh_postgres_check_uses_owner_overlay_and_rejects_other_stages(self):
        verifier = intake.IntakeVerify()
        verifier.base = [
            "docker",
            "compose",
            "--env-file",
            "/owned/fixture.env",
            "-f",
            "compose.yaml",
        ]
        verifier.postgres_owner_overlay = Path("/owned/postgres-owner.compose.yaml")
        pg_args = (
            intake.POSTGRES_OWNER_SERVICE,
            "python",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--capture=tee-sys",
            "--tb=no",
            "tests/test_attachments_postgres.py",
        )
        with (
            patch.object(verifier, "command") as command,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            verifier.check(
                "focused_tests", "api-check", "python", "-m", "pytest", output=Mock()
            )
            verifier.check_postgres_owner(
                "postgres_attachments", *pg_args, output=Mock()
            )
            with self.assertRaises(Unavailable):
                verifier.check_postgres_owner("focused_tests", *pg_args, output=Mock())
        calls = [call.args[0] for call in command.call_args_list]
        self.assertEqual(
            calls,
            [
                verifier.base + ["run", "--rm", "api-check", "python", "-m", "pytest"],
                verifier.base
                + [
                    "-f",
                    str(verifier.postgres_owner_overlay),
                    "run",
                    "--build",
                    "--rm",
                    *pg_args,
                ],
            ],
        )

    def test_nginx_dump_and_migration_head_parsers_do_not_forward_input(self):
        dumped = intake.NginxConfigOutput()
        dumped.feed(("# synthetic preamble\n" + self.config).encode())
        dumped.finish()
        self.assertEqual(dumped.buffer, bytearray())

        head = intake.HeadOutput()
        head.feed(b"irrelevant output\n20261002_0008 (head)\n")
        head.finish()
        for invalid in (b"20261001_0007 (head)\n", b"private revision detail\n"):
            parser = intake.HeadOutput()
            parser.feed(invalid)
            with self.assertRaises(Unavailable):
                parser.finish()

    def test_postgres_gate_requires_execution_instead_of_skip(self):
        for summary in (
            b"1 passed in 0.02s\n",
            b"==================== 1 passed in 0.02s ====================\n",
            b"================ 1 passed, 2 warnings in 0.02s ================\n",
        ):
            passed = intake.PostgresTestOutput()
            passed.feed(summary)
            passed.finish()
        for summary in (
            b"1 skipped in 0.02s\n",
            b"============= 1 skipped in 0.02s =============\n",
            b"============= 1 failed, 1 passed in 0.02s =============\n",
        ):
            skipped = intake.PostgresTestOutput()
            skipped.feed(summary)
            with self.assertRaises(Unavailable):
                skipped.finish()

    def test_postgres_failure_projection_is_fixed_and_does_not_satisfy_pass_gate(self):
        parser = intake.PostgresTestOutput()
        value = {
            "diagnostic": "imp017_intake_postgres",
            "stage": "preservation_constraint_ready",
            "category": "expected_exception_missing",
            "private": "synthetic secret SQL PDF detail",
        }
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            parser.feed(b"tests/test_attachments_postgres.py ")
            block = b"\n" + json.dumps(value).encode() + b"\n1 failed in 0.02s\n"
            for offset in range(0, len(block), 7):
                parser.feed(block[offset : offset + 7])
            # tee-sys can repeat captured stdout; duplicate findings stay bounded.
            parser.feed(json.dumps(value).encode() + b"\n")
            with self.assertRaises(Unavailable):
                parser.finish()
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(parser.reasons, {"tests_failed"})
        self.assertEqual(
            parser.findings,
            [{"stage": "preservation_constraint_ready", "category": "expected_exception_missing"}],
        )
        verifier = intake.IntakeVerify()
        with patch.object(verifier, "compose", side_effect=Unavailable), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            with self.assertRaises(Unavailable):
                verifier.check("postgres_attachments", output=parser)
        projected = json.loads(output.getvalue())
        self.assertEqual(projected["findings"], parser.findings)
        self.assertNotIn("secret", output.getvalue())

    def test_postgres_projection_rejects_unknown_stage_category_and_malformed_data(self):
        valid = {
            "diagnostic": "imp017_intake_postgres",
            "stage": "roundtrip_derivative_commit",
            "category": "integrity",
        }
        for value in (
            {**valid, "stage": "synthetic private path"},
            {**valid, "category": "synthetic private exception"},
            {**valid, "stage": []},
            {**valid, "diagnostic": "unknown"},
        ):
            parser = intake.PostgresTestOutput()
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                parser.feed(json.dumps(value).encode() + b"\n")
                parser.feed(b'{"diagnostic":invalid JSON\n')
            self.assertEqual(parser.findings, [])
            self.assertEqual(parser.reasons, {"postgres_diagnostic_unavailable"})
            self.assertEqual(output.getvalue(), "")

    def test_postgres_emitter_and_actual_checkpoints_match_harness_allowlist(self):
        tests = Path(__file__).resolve().parents[1] / "api/tests"
        tree = ast.parse((tests / "test_attachments_postgres.py").read_bytes())
        stages = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "POSTGRES_STAGES"
                    for target in node.targets)
        )
        self.assertEqual(set(stages), intake.POSTGRES_STAGES)
        for filename in ("test_attachments.py", "test_attachments_migration.py"):
            helper = ast.parse((tests / filename).read_bytes())
            for node in ast.walk(helper):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                        and node.func.id == "stage" and isinstance(node.args[0], ast.Constant):
                    self.assertIn(node.args[0].value, intake.POSTGRES_STAGES)
        # Execute only the dependency-free emitter, never import/run the PG test.
        emitter = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef) and node.name == "report_failure")

        class MissingExpected(BaseException):
            pass

        class DatabaseFailure(Exception):
            pass

        class IntegrityFailure(DatabaseFailure):
            pass

        namespace = {
            "json": json,
            "POSTGRES_STAGES": stages,
            "pytest": SimpleNamespace(fail=SimpleNamespace(Exception=MissingExpected)),
            "IntegrityError": IntegrityFailure,
            "SQLAlchemyError": DatabaseFailure,
        }
        exec(compile(ast.Module(body=[emitter], type_ignores=[]), "<fixed-emitter>", "exec"),
             namespace)
        for error, category in (
            (AssertionError("synthetic private assertion"), "assertion"),
            (MissingExpected("synthetic private expected exception"), "expected_exception_missing"),
            (IntegrityFailure("synthetic private SQL"), "integrity"),
            (DatabaseFailure("synthetic private URL"), "database"),
            (OSError("synthetic private path"), "filesystem"),
            (RuntimeError("synthetic private detail"), "unexpected"),
        ):
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                namespace["report_failure"]("preservation_upgrade", error)
            value = json.loads(output.getvalue())
            self.assertEqual(value["category"], category)
            self.assertNotIn("private", output.getvalue())
            parser = intake.PostgresTestOutput()
            parser.feed(output.getvalue().encode())
            self.assertEqual(parser.findings, [{"stage": "preservation_upgrade",
                                               "category": category}])

    def test_postgres_stage_wrapper_reraises_failure_and_still_cleans_owned_schema(self):
        path = Path(__file__).resolve().parents[1] / "api/tests/test_attachments_postgres.py"
        tree = ast.parse(path.read_bytes())
        function = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef)
            and node.name == "test_fresh_postgres_intake_migration_api_and_owned_cleanup"
        )
        control, engine = MagicMock(), Mock()
        connection = control.begin.return_value.__enter__.return_value = Mock()
        connection.scalar.return_value = 0
        failure = AssertionError("synthetic private failure")

        def failed_preservation(_, stage):
            stage("preservation_history")
            raise failure

        report = Mock()
        namespace = {
            "Path": Path,
            "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="a" * 32)),
            "database_url_from_environment": Mock(return_value="synthetic-unused"),
            "create_engine": Mock(side_effect=[control, engine]),
            "NullPool": object,
            "text": lambda value: value,
            "check_preservation": failed_preservation,
            "report_failure": report,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), "<fixed-pg-wrapper>", "exec"),
             namespace)
        with self.assertRaises(AssertionError) as raised:
            namespace[function.name](Path("synthetic-unused"))
        self.assertIs(raised.exception, failure)
        report.assert_called_once_with("preservation_history", failure)
        self.assertEqual(control.begin.call_count, 2)  # Create, then owned drop.
        self.assertIn("DROP SCHEMA", connection.execute.call_args.args[0])
        connection.scalar.assert_called_once()
        engine.dispose.assert_called_once()
        control.dispose.assert_called_once()

    def test_any_stage_failure_runs_owned_cleanup_and_reports_no_child_error(self):
        verifier = intake.IntakeVerify()
        with patch.object(verifier, "prepare", side_effect=RuntimeError("private details")), \
                patch.object(verifier, "cleanup", return_value=True) as cleanup, \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(verifier.run(), 1)
        cleanup.assert_called_once_with()
        self.assertIn('"phase": "prepare"', output.getvalue())
        self.assertNotIn("private details", output.getvalue())


if __name__ == "__main__":
    unittest.main()
