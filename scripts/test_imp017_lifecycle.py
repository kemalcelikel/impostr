"""Pure lifecycle budget/provenance/config checks; no DB/runtime/private inputs."""

import sys
import unittest
from pathlib import Path
import io
import ast
import asyncio
from contextlib import asynccontextmanager
import hashlib
import os
import signal
import stat
import tarfile
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from app.config import AppSettings
from app.pdf_extractor import UnixPDFExtractor
from app.pdf_lifecycle_policy import LEASE_SECONDS, MAX_ATTEMPTS, VERIFIED_BUILD_SHA256, retry_delay
from app.pdf_protocol import JOB_SECONDS, PDFError
import imp017_lifecycle_verify as verifier
from imp024_verify import Unavailable


class PolicyTests(unittest.TestCase):
    def test_shutdown_fixture_mock_tracks_calls_without_bypassing_blocking_callback(self):
        tree = ast.parse((verifier.ROOT / "api/tests/test_pdf_lifecycle.py").read_text())
        test = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "test_shutdown_drains_inflight_job_and_leaves_next_pending")
        assignment = next(node for node in test.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "processor"
                                  for target in node.targets))
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        metadata, chunks, result = object(), object(), object()

        def extract(actual_metadata, actual_chunks):
            self.assertIs(actual_metadata, metadata)
            self.assertIs(actual_chunks, chunks)
            entered.set()
            self.assertTrue(release.wait(5))
            returned.set()
            return result

        # Evaluate only the fixture's stdlib Mock construction, not API/DB code.
        wrapper = ast.Expression(assignment.value.args[1])
        extractor = eval(compile(wrapper, "shutdown-fixture-mock", "eval"),
                         {"Mock": Mock, "extract": extract})
        results = []
        thread = threading.Thread(target=lambda: results.append(extractor.extract(metadata, chunks)))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertFalse(returned.is_set())
            self.assertEqual(extractor.extract.call_count, 1)
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [result])
        extractor.extract.assert_called_once_with(metadata, chunks)

    def test_changed_python_sources_compile_without_importing_runtime_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        paths = [root / "api" / path for path in verifier.FILES]
        paths += [root / "scripts" / "imp017_lifecycle_verify.py"]
        for path in paths:
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(), filename=path.name)
                compile(tree, path.name, "exec")

    def test_joined_fixture_uses_the_provisioned_httpx2_client(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "api"
            / "tests"
            / "imp017_lifecycle_joined.py"
        )
        tree = ast.parse(path.read_text(), filename=path.name)
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertIn("httpx2", imported_modules)
        self.assertNotIn("httpx", imported_modules)

    def test_only_transient_errors_retry_with_finite_backoff(self):
        for code in ("busy", "unavailable"):
            self.assertEqual([retry_delay(code, n) for n in (1, 2, 3)], [5, 15, None])
        for code in ("invalid", "encrypted", "active_content", "no_text", "limit", "timeout"):
            self.assertIsNone(retry_delay(code, 1))
        self.assertEqual(MAX_ATTEMPTS, 3)
        self.assertGreater(LEASE_SECONDS, JOB_SECONDS)

    def test_explicit_setting_and_real_recorded_build(self):
        settings = AppSettings("http://127.0.0.1:8080", b"synthetic-only" * 4)
        self.assertFalse(settings.pdf_enabled)
        with self.assertRaises(ValueError):
            AppSettings(settings.public_origin, settings.rate_limit_key, pdf_enabled="1")
        self.assertEqual(VERIFIED_BUILD_SHA256,
                         "b976249ca1a5aea47689ac9210b15611b6b9c88ab9c337f766e5e1569faa4192")

    def test_socket_deadline_is_terminal_timeout_not_unavailable(self):
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o711, st_uid=10002)
        channel = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=10002, st_gid=10001)
        connection = Mock()
        connection.connect.side_effect = TimeoutError("synthetic private diagnostic")
        socket_context = Mock()
        socket_context.__enter__ = Mock(return_value=connection)
        socket_context.__exit__ = Mock(return_value=False)
        with patch("app.pdf_extractor.os.geteuid", return_value=10001), \
                patch("app.pdf_extractor.os.getegid", return_value=10001), \
                patch("app.pdf_extractor.os.lstat", side_effect=[directory, channel]), \
                patch("app.pdf_extractor.socket.socket", return_value=socket_context):
            with self.assertRaises(PDFError) as caught:
                UnixPDFExtractor().extract({"v": 1, "size": 1, "sha256": "a" * 64}, [b"x"])
        self.assertEqual(caught.exception.code, "timeout")

    def test_joined_parser_projects_fixed_fields_and_requires_all_actual_passes(self):
        start = Mock()
        output = verifier.JoinedOutput(start)
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            output.feed(b"ACTION pdf-start\n")
            output.feed(b'{"diagnostic":"imp017_lifecycle","stage":"ready",'
                        b'"category":"operation","private":"never print me"}\n')
            for passed in verifier.PASSES:
                output.feed((passed + "\n").encode())
            output.finish()
            self.assertNotIn("never print me", stdout.getvalue())
        start.assert_called_once()
        with self.assertRaises(Unavailable):
            verifier.JoinedOutput(start).finish()
        with self.assertRaises(Unavailable):
            verifier.JoinedOutput(start).feed(b"arbitrary parser output\n")

    def test_image_inventory_requires_canonical_immutable_id_or_explicit_absence(self):
        output = verifier.ImageOutput()
        image = "sha256:" + "a" * 64
        output.feed((image + "\n").encode())
        output.finish()
        self.assertEqual(output.image, image)
        for content in (b"", b"impostr-pdf:phase1\n", (image + "\n" + image + "\n").encode()):
            output = verifier.ImageOutput()
            output.feed(content)
            with self.assertRaises(Unavailable):
                output.finish()
        output = verifier.ImageOutput(optional=True)
        output.finish()
        self.assertIsNone(output.image)


class JoinedShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Only the affected stdlib helper/class, never API/DB runtime imports.
        tree = ast.parse((verifier.ROOT / "api/tests/imp017_lifecycle_joined.py").read_text())
        nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                 and node.name in ("shutdown_lifespan", "PDFAPI")]
        namespace = {"asynccontextmanager": asynccontextmanager, "ApiProcess": object,
                     "os": SimpleNamespace(killpg=Mock()), "signal": signal}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "joined-shutdown", "exec"), namespace)
        cls.namespace = namespace

    def test_marker_written_after_successful_drain_but_never_after_failed_close(self):
        wrapper = self.namespace["shutdown_lifespan"]

        async def exercise(failed):
            events = []
            marker = Mock()
            marker.write_bytes.side_effect = lambda value: events.append("marker")
            directory = MagicMock()
            directory.__truediv__.return_value = marker

            @asynccontextmanager
            async def lifespan(application):
                events.append("open")
                yield
                events.append("drain")
                if failed:
                    raise RuntimeError("synthetic shutdown failure")
                events.append("closed")

            async def run():
                async with wrapper(lifespan, directory)(object()):
                    events.append("running")

            if failed:
                with self.assertRaises(RuntimeError):
                    await run()
                marker.write_bytes.assert_not_called()
                self.assertEqual(events, ["open", "running", "drain"])
            else:
                await run()
                marker.write_bytes.assert_called_once_with(b"complete\n")
                self.assertEqual(events, ["open", "running", "drain", "closed", "marker"])

        asyncio.run(exercise(False))
        asyncio.run(exercise(True))

    def test_graceful_stop_requires_fresh_marker_and_exact_signal_exit_without_retry(self):
        api = self.namespace["PDFAPI"]()
        marker = Mock()
        api.directory = MagicMock()
        api.directory.__truediv__.return_value = marker
        api.process = Mock(pid=12345, returncode=-signal.SIGTERM)
        api.process.poll.return_value = None
        api.process.wait.side_effect = lambda **_: marker.unlink.assert_called_once_with(missing_ok=True)
        marker.read_bytes.return_value = b"complete\n"
        kill = self.namespace["os"].killpg
        kill.reset_mock()
        api.graceful_stop()
        kill.assert_called_once_with(12345, signal.SIGTERM)
        api.process.wait.assert_called_once_with(timeout=55)
        for code, content in ((0, b"complete\n"), (-signal.SIGKILL, b"complete\n"),
                              (-signal.SIGTERM, b"incomplete\n")):
            marker.reset_mock()
            api.process.returncode = code
            marker.read_bytes.return_value = content
            with self.assertRaises(AssertionError):
                api.graceful_stop()
        marker.reset_mock()
        api.process.returncode = -signal.SIGTERM
        marker.read_bytes.side_effect = FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            api.graceful_stop()

    def test_fixed_shutdown_substage_is_projected_without_private_details(self):
        output = verifier.JoinedOutput(Mock())
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            output.feed(b'{"diagnostic":"imp017_lifecycle","stage":"shutdown",'
                        b'"category":"assertion","private":"secret"}\n')
        self.assertIn('"stage": "shutdown"', stdout.getvalue())
        self.assertNotIn("secret", stdout.getvalue())


class FocusedProjectionTests(unittest.TestCase):
    def test_summary_projects_allowlisted_names_and_fixed_assertion_category_only(self):
        output = verifier.FocusedTestOutput()
        filename = "tests/test_pdf_lifecycle.py"
        test = "test_transient_durable_backoff_recovery_and_exhaustion"
        text = (f"FAILED {filename}::{test}[private-param] - AssertionError: private-value\n"
                f"FAILED {filename}::{test}[other-param] - assert private-value == secret\n"
                "=================== 2 failed, 19 passed in 1.0s ===================\n").encode()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            # Real subprocess blocks can split a summary anywhere.
            for offset in range(0, len(text), 17):
                output.feed(text[offset:offset + 17])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(output.reasons, {"tests_failed"})
        self.assertEqual(output.findings, [{"file": filename, "test": test, "category": "assertion"}])

    def test_unknown_paths_tests_unbounded_or_unrecognized_details_never_escape(self):
        output = verifier.FocusedTestOutput()
        node = "tests/test_pdf_retry_migration.py::test_0008_pending_bytes_preserved_and_lossy_downgrade_denied"
        output.feed((
            "FAILED /private/test_secret.py::test_secret - AssertionError: secret\n"
            "FAILED tests/test_pdf_lifecycle.py::test_unapproved - assert secret\n"
            f"FAILED {node}[{'private' * 100}] - AssertionError: secret\n"
            "1 failed, 1 error in 0.1s\n").encode())
        self.assertEqual(output.findings, [{"file": "unknown", "test": "unknown", "category": "unknown"}])
        output.feed(f"ERROR {node} - sqlalchemy.exc.IntegrityError: private SQL/values\n".encode())
        self.assertEqual(output.findings, [{"file": node.split("::")[0],
                                           "test": node.split("::")[1], "category": "unknown"}])
        self.assertEqual(output.reasons, {"tests_failed", "test_errors"})

    def test_failure_check_emits_only_bounded_safe_projection_and_still_raises(self):
        runner = verifier.LifecycleVerify()
        output = verifier.FocusedTestOutput()
        def fail(*args, **kwargs):
            output.feed(b"FAILED tests/test_attachments.py::test_pending_commit_exact_download_escaped_ready_preview_and_delete - assert private-secret\n")
            raise Unavailable()
        with patch.object(runner, "compose", side_effect=fail), \
                patch("sys.stdout", new_callable=io.StringIO) as stdout:
            with self.assertRaises(Unavailable):
                runner.check("focused_lifecycle", "api-check", output=output)
        self.assertIn("test_pending_commit_exact_download_escaped_ready_preview_and_delete", stdout.getvalue())
        self.assertNotIn("private-secret", stdout.getvalue())
        self.assertIn('"category": "assertion"', stdout.getvalue())
        self.assertEqual(runner.phase, "focused_lifecycle")
        for filename, tests in verifier.FOCUSED_TESTS.items():
            for test in sorted(tests):
                output.feed(f"FAILED {filename}::{test} - AssertionError: private\n".encode())
        self.assertEqual(len(output.findings), 16)

    def test_allowlist_matches_current_focused_test_definitions(self):
        for filename, names in verifier.FOCUSED_TESTS.items():
            tree = ast.parse((verifier.ROOT / "api" / filename).read_text())
            actual = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name.startswith("test_")}
            self.assertEqual(names, actual)


def packed(values):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name, data in values.items():
            info = tarfile.TarInfo("./" + name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class ReconstructionTests(unittest.TestCase):
    def test_build_command_uses_inherited_minimal_environment_and_discards_raw_output(self):
        runner = verifier.LifecycleVerify()
        environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/synthetic-owned"}
        runner.environment = environment
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        process = Mock(pid=12345, stdout=os.fdopen(read_fd, "rb"), stderr=None)
        process.wait.return_value = 0
        args = verifier.DOCKER + ["compose", "--env-file", "/dev/null", "build", "pdf-extractor"]
        with patch.object(runner, "check_directories"), \
                patch("imp024_verify.subprocess.Popen", return_value=process) as popen, \
                patch("imp024_verify.stop_process"):
            runner.command(args, seconds=900)
        self.assertIs(popen.call_args.kwargs["env"], environment)
        self.assertEqual(popen.call_args.kwargs["cwd"], verifier.ROOT)
        self.assertEqual(popen.call_args.kwargs["stdin"], verifier.subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs["stdout"], verifier.subprocess.PIPE)
        self.assertEqual(popen.call_args.kwargs["stderr"], verifier.subprocess.STDOUT)

    def fixture(self, existing=None, *, bad_provenance=False, build_failure=False):
        runner = verifier.LifecycleVerify()
        runner.project = "synthetic-lifecycle-owned"
        runner.base = ["synthetic-compose"]
        runner.environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/synthetic-owned"}
        state = {verifier.SHARED_IMAGE: existing}
        calls, overlays = [], []
        built = "sha256:" + "b" * 64

        def overlay(filename, image):
            overlays.append((filename, image))
            return "/synthetic-owned/" + filename

        def command(args, **kwargs):
            calls.append((args, kwargs))
            output = kwargs.get("output")
            if "image" in args and "ls" in args:
                image = state.get(args[-1].removeprefix("reference="))
                if image:
                    output.feed((image + "\n").encode())
            elif "build" in args:
                self.assertEqual(kwargs["seconds"], 900)
                self.assertEqual(args[:3], verifier.DOCKER)
                self.assertEqual(args[3:6], ["compose", "--env-file", "/dev/null"])
                state[overlays[-1][1]] = built
                if build_failure:
                    raise Unavailable()
            elif "cp" in args:
                self.assertIsInstance(output, verifier.PackagedOutput)
                self.assertEqual(output.expected["build.json"], verifier.VERIFIED_BUILD_SHA256)
                if bad_provenance:
                    output.feed(packed({"build.json": b"synthetic wrong provenance"}))
                    output.finish()
                # Other exact packaged hashes are exercised independently below;
                # mock Docker only, never construct/run an actual converter.
                return output
            elif "image" in args and "rm" in args:
                state.pop(args[-1])
            if hasattr(output, "finish"):
                output.finish()
            return output

        runner.command = Mock(side_effect=command)
        runner.write_image_overlay = Mock(side_effect=overlay)
        return runner, state, calls, overlays, built

    def test_absence_reconstructs_only_owned_tag_and_pins_validated_id(self):
        runner, state, calls, overlays, built = self.fixture()
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            runner.ensure_extractor()
        self.assertIsNone(state[verifier.SHARED_IMAGE])
        self.assertEqual(runner.reconstructed_image, built)
        self.assertEqual(runner.extractor_image, built)
        self.assertEqual(overlays[-1], ("extractor-pinned.compose.yaml", built))
        self.assertEqual(runner.base[-2:], ["-f", "/synthetic-owned/extractor-pinned.compose.yaml"])
        create = next(args for args, _ in calls if "create" in args)
        self.assertEqual(create[-1], built)
        self.assertIn("none", create)
        self.assertFalse(any("start" in args for args, _ in calls))
        self.assertIn(verifier.VERIFIED_BUILD_SHA256, stdout.getvalue())
        self.assertEqual(runner.runs, [])
        with patch.object(verifier.IntakeVerify, "cleanup", return_value=True), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertTrue(runner.cleanup())
        removals = [args[-1] for args, _ in calls if "image" in args and "rm" in args]
        self.assertEqual(removals, ["impostr-pdf-reconstruct:synthetic-lifecycle-owned"])
        self.assertFalse(runner.reconstructed_tag.startswith(runner.project + "-"))

    def test_existing_image_validated_without_build_retag_or_image_removal(self):
        existing = "sha256:" + "c" * 64  # Not the historical Docker image ID.
        runner, state, calls, overlays, _ = self.fixture(existing)
        with patch("sys.stdout", new_callable=io.StringIO), \
                patch.object(verifier.IntakeVerify, "cleanup", return_value=True):
            runner.ensure_extractor()
            self.assertTrue(runner.cleanup())
        self.assertEqual(state[verifier.SHARED_IMAGE], existing)
        self.assertEqual(overlays, [("extractor-pinned.compose.yaml", existing)])
        self.assertFalse(any("build" in args or "tag" in args for args, _ in calls))
        self.assertFalse(any("image" in args and "rm" in args for args, _ in calls))
        self.assertEqual(runner.extractor_image, existing)

    def test_provenance_mismatch_stops_before_lifecycle_and_cleans_only_owned_image(self):
        for existing in (None, "sha256:" + "c" * 64):
            with self.subTest(existing=existing):
                runner, state, calls, overlays, _ = self.fixture(existing, bad_provenance=True)
                with patch("sys.stdout", new_callable=io.StringIO), \
                        patch.object(verifier.IntakeVerify, "cleanup", return_value=True):
                    with self.assertRaises(Unavailable):
                        runner.ensure_extractor()
                    self.assertTrue(runner.cleanup())
                self.assertIsNone(runner.extractor_image)
                self.assertFalse(any(name == "extractor-pinned.compose.yaml" for name, _ in overlays))
                self.assertEqual(state[verifier.SHARED_IMAGE], existing)
                removals = [args for args, _ in calls if "image" in args and "rm" in args]
                self.assertEqual(len(removals), 1 if existing is None else 0)

    def test_failed_build_cleans_reserved_tag_and_cleanup_failure_is_visible(self):
        runner, state, calls, _, _ = self.fixture(build_failure=True)
        with self.assertRaises(Unavailable):
            runner.ensure_extractor()
        with patch.object(verifier.IntakeVerify, "cleanup", return_value=True), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertTrue(runner.cleanup())
        self.assertNotIn(runner.reconstructed_tag, state)
        runner.reconstructed_image = "sha256:" + "b" * 64
        state[runner.reconstructed_tag] = "sha256:" + "d" * 64
        calls.clear()
        with patch.object(verifier.IntakeVerify, "cleanup", return_value=True), \
                patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertFalse(runner.cleanup())
        self.assertIn('"status": "failed"', stdout.getvalue())
        self.assertFalse(any("rm" in args for args, _ in calls))

    def test_source_drift_or_inventory_failure_is_not_treated_as_absence(self):
        runner, _, calls, _, _ = self.fixture()
        with patch.object(runner, "validate_sources", side_effect=Unavailable):
            with self.assertRaises(Unavailable):
                runner.ensure_extractor()
        self.assertEqual(calls, [])
        runner.command = Mock(side_effect=Unavailable)
        with patch.object(runner, "validate_sources"), self.assertRaises(Unavailable):
            runner.ensure_extractor()
        self.assertIn("image", runner.command.call_args.args[0])
        self.assertIsNone(runner.reconstructed_tag)

    def test_reconstruction_name_collision_is_not_adopted_or_removed(self):
        runner, state, calls, _, _ = self.fixture()
        collision = "impostr-pdf-reconstruct:" + runner.project
        state[collision] = "sha256:" + "e" * 64
        with self.assertRaises(Unavailable):
            runner.ensure_extractor()
        with patch.object(verifier.IntakeVerify, "cleanup", return_value=True):
            self.assertTrue(runner.cleanup())
        self.assertIsNone(runner.reconstructed_tag)
        self.assertIn(collision, state)
        self.assertFalse(any("build" in args or "rm" in args for args, _ in calls))

    def test_packaged_archive_hashes_actual_bytes_and_refuses_missing_or_extra_sources(self):
        values = {"build.json": b"synthetic build", "worker.py": b"synthetic worker"}
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in values.items()}
        output = verifier.PackagedOutput(hashes)
        output.feed(packed(values))
        output.finish()
        for changed in ({"build.json": values["build.json"]},
                        {**values, "worker.py": b"changed"},
                        {**values, "unexpected.py": b"extra"}):
            output = verifier.PackagedOutput(hashes)
            output.feed(packed(changed))
            with self.assertRaises(Unavailable):
                output.finish()
            self.assertFalse(output.buffer)

    def test_sources_guard_allows_only_exact_fixture_context_delta(self):
        runner = verifier.LifecycleVerify()
        runner.command = Mock()
        runner.validate_sources()
        runner.command.assert_called_once()
        args = runner.command.call_args.args[0]
        self.assertEqual(args[:5], ["git", "diff", "--no-ext-diff", "--no-textconv", "--exit-code"])
        self.assertIn("ca09dc3", args)
        self.assertIn("pdf-extractor", args)
        with patch.object(Path, "read_bytes", return_value=b"**\n" + verifier.FIXTURE_ALLOWANCE):
            with self.assertRaises(Unavailable):
                runner.validate_sources()
        root = Path(__file__).resolve().parents[1]
        self.assertIn("!scripts/imp017_fixtures.py", (root / ".dockerignore").read_text().splitlines())
        self.assertIn("COPY scripts/imp017_fixtures.py ", (root / "api/Dockerfile").read_text())
