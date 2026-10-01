"""Pure unit seams ONLY. No new worker/socket/provider/Compose runtime scenarios."""

import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

import imp005_connection as connection
import imp024_broker as broker
import imp024_inference as native
from test_imp024_operator import KEY, call, data, planning


def decoded(raw):
    return json.loads(raw.split(b"data: ", 1)[1])


class Frames:
    def __init__(self, events):
        self.events = iter(events)
        self.terminal_read = False

    def read1(self, _):
        value = next(self.events, b"")
        if b"event: response.completed" in value:
            self.terminal_read = True
        return value


class ConnectionTests(unittest.TestCase):
    def test_verifier_generated_turn_relay_path_fits_linux_unix_socket_limit(self):
        import imp005_verify as verify
        import imp024_verify as base

        fixture = verify.NormalVerify()
        # Exact base Verify mkdtemp prefix + eight-character generated suffix.
        fixture.inputs = base.PARENT / (fixture.project + "-inputs-12345678")
        with patch.object(verify, "OwnedRuntime") as owned, \
                patch.object(verify, "Connection"), patch.object(verify, "report"):
            fixture.start_broker()
        root = owned.call_args.args[0]
        relay = root / "private" / "imp024-turn-12345678" / "relay.sock"
        self.assertLess(len(str(relay).encode()), 108)
        self.assertEqual(root.parent, fixture.inputs)
        production = connection.RUNTIME / "private" / "imp024-turn-12345678" / "relay.sock"
        self.assertLess(len(str(production).encode()), 108)

    def test_normal_verifier_exact_prepare_and_start_with_generated_inputs(self):
        import imp005_verify as verify
        import imp024_verify as base

        with tempfile.TemporaryDirectory() as name:
            parent = Path(name)
            parent.chmod(0o775)  # Same approved scratch-parent mode as base Verify.
            fixture = verify.NormalVerify()
            fixture.channel = parent / fixture.project
            # Base preparation creates actual generated paths/modes; only the
            # subreaper and broker execution are mocked. No Docker/worker/socket.
            with patch.object(base, "PARENT", parent), patch.object(base.ctypes, "CDLL") as libc, \
                    patch.object(broker, "check_runtime"), patch.object(broker.socket, "socket") as listener, \
                    patch.object(connection.threading, "Thread") as thread, \
                    patch.object(verify, "reap_children"), patch.object(base, "report"), \
                    patch.object(verify, "report"):
                libc.return_value.prctl.return_value = 0
                # Placeholder file for mocked bind; no listener is ever created.
                # Real chmod/unlink keep ownership and cleanup assertions intact.
                listener.return_value.bind.side_effect = lambda path: Path(path).touch()
                try:
                    fixture.prepare()
                    self.assertEqual(parent.stat().st_mode & 0o777, 0o775)
                    self.assertLess(len(str(fixture.channel / "channel.sock").encode()), 108)
                    relay = fixture.runtime.scratch / "imp024-turn-12345678" / "relay.sock"
                    self.assertLess(len(str(relay).encode()), 108)
                    fixture.start_broker()
                    thread.return_value.is_alive.return_value = False
                    # close() sets stop before join; run only its cleanup branch,
                    # never accept or dispatch, for the mocked unstarted thread.
                    thread.return_value.join.side_effect = lambda _: fixture.connection.broker.run()
                    self.assertEqual(fixture.runtime.root.parent.stat().st_mode & 0o777, 0o700)
                    self.assertEqual(fixture.connection.broker.directory, fixture.channel)
                finally:
                    self.assertTrue(fixture.cleanup())

    def test_verifier_failed_seam_reports_only_fixed_phase_and_category(self):
        import imp005_verify as verify

        for error, reason in ((ValueError("synthetic private input"), "contract_rejected"),
                              (OSError("synthetic private path"), "filesystem_operation"),
                              (verify.CapabilityError("synthetic private binary"), "runtime_capability")):
            fixture = verify.NormalVerify()
            def failed_start():
                fixture.stage("broker_construct")
                raise error
            with patch.object(fixture, "prepare"), patch.object(fixture, "start_broker", side_effect=failed_start), \
                    patch.object(fixture, "compose") as compose, patch.object(fixture, "cleanup", return_value=True) as cleanup, \
                    patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(fixture.run(), 1)
            self.assertEqual([json.loads(line) for line in output.getvalue().splitlines()], [
                {"check": "ordinary_connection_phase", "status": "started", "phase": "broker_construct"},
                {"check": "ordinary_stack_synthetic_connection_lifecycle", "status": "failed",
                 "phase": "broker_construct", "reason": reason},
            ])
            compose.assert_not_called()
            cleanup.assert_called_once()

    def test_static_diagnostics_scope_new_files_and_never_emit_raw_ruff_details(self):
        import imp005_verify as verify
        import imp024_verify as base

        filename = "tests/imp005_synthetic_scope.py"
        row = {"filename": "/app/" + filename, "code": "E501", "location": {"row": 19},
               "message": "private detail", "source": "private snippet", "fix": {"content": "private"}}
        parser = verify.RuffJsonOutput(check_files=verify.API_CHECK_FILES)
        parser.feed(json.dumps([row]).encode())
        parser.finish()
        fixture = verify.NormalVerify()
        fixture.phase = "api_lint"
        with patch.object(fixture, "compose", side_effect=base.Unavailable()), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            with self.assertRaises(base.Unavailable):
                fixture.static_check("ruff", "check", output=parser)
        self.assertEqual(json.loads(output.getvalue()), {
            "check": "ordinary_connection_static_diagnostic", "status": "failed", "phase": "api_lint",
            "reasons": ["lint_findings"], "findings": [{"file": filename, "code": "E501", "line": 19}],
        })
        self.assertEqual(parser.buffer, b"")
        denied = verify.RuffJsonOutput(check_files=verify.API_CHECK_FILES)
        denied.feed(json.dumps([dict(row, filename="/private/secret.py")]).encode())
        with self.assertRaises(base.Unavailable):
            denied.finish()
        self.assertEqual(denied.findings, [])
        formatter = verify.CheckOutput("ruff_format", check_files=verify.API_CHECK_FILES)
        formatter.feed(("Would reformat: " + filename + "\n").encode())
        self.assertEqual(formatter.findings, [{"file": filename, "code": "format_mismatch"}])

    def stream(self, instance, response):
        return instance.normalize_planning(response, data(), threading.Event(), time.monotonic() + 3)

    def test_actual_safe_delta_before_terminal_read_and_no_tools_until_completion(self):
        response = Frames(native.native_response("Safe early text", [call()]))
        instance, _ = planning(b"")
        stream = self.stream(instance, response)
        seen = []
        while True:
            value = decoded(next(stream))
            seen.append(value)
            if value["type"] == "response.output_text.delta":
                break
        self.assertFalse(response.terminal_read)
        self.assertFalse(any(value.get("item", {}).get("type") == "function_call" for value in seen))
        rest = list(stream)
        self.assertEqual(decoded(rest[-1])["type"], "response.completed")

    def test_split_key_longest_prefix_held_and_late_failure_preserves_only_safe_text(self):
        events = native.native_response("safe " + KEY)
        values = [decoded(raw) for raw in events]
        delta_index = next(i for i, value in enumerate(values) if value["type"] == "response.output_text.delta")
        value = values[delta_index]
        first = dict(value, delta="safe " + KEY[:-1])
        second = dict(value, delta=KEY[-1:])
        events[delta_index:delta_index + 1] = [native.frame(first.pop("type"), first, 0),
                                             native.frame(second.pop("type"), second, 0)]
        instance, _ = planning(b"")
        emitted = []
        with self.assertRaises(ValueError):
            for raw in self.stream(instance, Frames(events)):
                emitted.append(decoded(raw))
        self.assertEqual("".join(v["delta"] for v in emitted if v["type"] == "response.output_text.delta"), "safe ")
        self.assertFalse(any(v["type"] == "response.completed" for v in emitted))

    def test_per_turn_cross_call_tail_rejects_key_completed_in_next_response(self):
        instance, _ = planning(b"")
        list(self.stream(instance, Frames(native.native_response(KEY[:10]))))
        with self.assertRaises(ValueError):
            list(self.stream(instance, Frames(native.native_response(KEY[10:]))))
        fresh = instance.for_turn()
        self.assertEqual(fresh.emitted_tail, "")
        list(self.stream(fresh, Frames(native.native_response(KEY[10:]))))

    def test_late_invalid_or_error_never_releases_tools_or_completion(self):
        for terminal in (b"broken\n\n", native.frame("response.failed", {"message": "private error"}, 8)):
            events = native.native_response("Safe partial", [call()])[:-1] + [terminal]
            instance, _ = planning(b"")
            seen = []
            try:
                for raw in self.stream(instance, Frames(events)):
                    seen.append(decoded(raw))
            except ValueError:
                pass
            self.assertEqual("".join(v["delta"] for v in seen if v["type"] == "response.output_text.delta"), "Safe partial")
            self.assertFalse(any(v["type"] == "response.completed" or
                                 v.get("item", {}).get("type") == "function_call" for v in seen))

    def test_tiny_deltas_coalesce_within_existing_event_bounds(self):
        text = "a" * 1600
        events = native.native_response(text)
        index = next(i for i, raw in enumerate(events) if decoded(raw)["type"] == "response.output_text.delta")
        value = decoded(events[index])
        events[index:index + 1] = [native.frame("response.output_text.delta", dict(value, delta="a"), i) for i in range(len(text))]
        instance, _ = planning(b"")
        emitted = [decoded(raw) for raw in self.stream(instance, Frames(events))]
        deltas = [value["delta"] for value in emitted if value["type"] == "response.output_text.delta"]
        self.assertEqual("".join(deltas), text)
        self.assertLess(len(deltas), 12)

    def test_owned_runtime_exclusive_stale_and_inode_retention_without_socket_execution(self):
        with tempfile.TemporaryDirectory() as name:
            parent = Path(name)
            parent.chmod(0o700)
            root = parent / "owned"
            first = connection.OwnedRuntime(root)
            inode = first.channel.stat().st_ino
            with self.assertRaises(ValueError):
                connection.OwnedRuntime(root)
            first.close(clean=True)
            second = connection.OwnedRuntime(root)
            self.assertEqual(second.channel.stat().st_ino, inode)
            second.close()  # Simulated crash retains exclusive marker.
            with self.assertRaises(ValueError):
                connection.OwnedRuntime(root)

    def test_runtime_denies_symlink_wrong_mode_and_foreign_state(self):
        with tempfile.TemporaryDirectory() as name:
            parent = Path(name)
            parent.chmod(0o700)
            root = parent / "owned"
            root.symlink_to(parent, target_is_directory=True)
            with self.assertRaises((ValueError, OSError)):
                connection.OwnedRuntime(root)
            root.unlink()
            runtime = connection.OwnedRuntime(root)
            runtime.close(clean=True)
            runtime.scratch.chmod(0o777)
            with self.assertRaises(ValueError):
                connection.OwnedRuntime(root)

    def test_launcher_orders_all_checks_before_noecho_and_cleans_failed_key(self):
        runtime, inference, core = Mock(), Mock(), Mock()
        core.thread.is_alive.return_value = True
        core.failed.wait.side_effect = KeyboardInterrupt()
        actions = []
        def input_value(label, *, secret=False):
            actions.append("key" if secret else "input")
            return KEY if secret else "CONNECT"
        with patch.object(connection, "check_runtime", side_effect=lambda: actions.append("pins")), \
                patch.object(connection.ctypes, "CDLL") as libc, \
                patch.object(connection, "OwnedRuntime", side_effect=lambda: (actions.append("owned"), runtime)[1]), \
                patch.object(connection, "explicit_contract"), \
                patch.object(connection, "PlanningHTTPSInference", side_effect=lambda _: (actions.append("dns_ca"), inference)[1]), \
                patch.object(connection, "Connection", side_effect=lambda *a: (actions.append("socket"), core)[1]), \
                patch.object(connection, "terminal_input", side_effect=input_value), \
                patch.object(connection.sys, "stdin", Mock(isatty=lambda: True)), \
                patch.object(connection.sys, "stdout", Mock(isatty=lambda: True)), \
                patch.object(connection, "reap_children"), patch.object(connection.Path, "cwd", return_value=connection.ROOT):
            libc.return_value.prctl.return_value = 0
            self.assertEqual(connection.connect(), 0)
        self.assertLess(actions.index("pins"), actions.index("key"))
        self.assertLess(actions.index("owned"), actions.index("key"))
        self.assertLess(actions.index("dns_ca"), actions.index("key"))
        self.assertLess(actions.index("socket"), actions.index("key"))
        inference.clear.assert_called_once()
        core.close.assert_called_once()
        runtime.close.assert_called_once_with(clean=True)

    def test_explicit_broker_mode_not_inferred_from_injection(self):
        with patch.object(broker.os, "getuid", return_value=1000), \
                patch.object(broker.os, "geteuid", return_value=1000), \
                patch.object(broker.os, "getgid", return_value=1000), \
                patch.object(broker, "check_runtime"), patch.object(broker.socket, "socket"):
            directory = MagicMock()
            directory.parent = Path("/tmp/opencode")
            directory.exists.return_value = True
            directory.lstat.return_value = Mock(st_mode=0o40711, st_uid=1000, st_gid=1000)
            directory.iterdir.return_value = iter(())
            instance = broker.Broker(directory, persistent_directory=True, transport_factory=Mock(), mode="synthetic")
            self.assertEqual(instance.mode, "synthetic")

    def test_capacity_preserves_poll_and_abort_slots_and_does_not_stop_service(self):
        from app.chat_protocol import scope
        from test_imp024_channel import payload
        import uuid

        instance = object.__new__(broker.Broker)
        instance.epoch = str(uuid.uuid4())
        instance.mode = "planning"
        instance.stop = threading.Event()
        instance.turns = {}
        instance.aborted_unknown = {str(uuid.uuid4()): () for _ in range(247)}
        instance.transport_factory = Mock()
        instance.scratch_parent = Path("/generated-private")
        command = {"op": "start", "epoch": instance.epoch, "project_id": str(uuid.uuid4()),
                   "conversation_id": str(uuid.uuid4()), "turn_id": str(uuid.uuid4()), "payload": payload()}
        turn = Mock()
        turn.key = scope(command)
        turn.stopped = threading.Event()
        turn.stopped.set()
        turn.lock = threading.Lock()
        turn.events = []
        with patch.object(broker, "Turn", return_value=turn):
            self.assertTrue(instance.handle(command)["ok"])
        self.assertFalse(instance.handle({"op": "hello"})["admitting"])
        with self.assertRaises(ValueError):
            instance.handle(dict(command, turn_id=str(uuid.uuid4())))
        clean = {key: value for key, value in command.items() if key != "payload"}
        self.assertTrue(instance.handle(dict(clean, op="poll", after=0))["known"])
        unknown = dict(clean, op="abort", turn_id=str(uuid.uuid4()))
        self.assertTrue(instance.handle(unknown)["stopped"])
        self.assertEqual(len(instance.aborted_unknown), 248)
        for _ in range(7):
            instance.handle(dict(unknown, turn_id=str(uuid.uuid4())))
        self.assertTrue(instance.handle(unknown)["stopped"])
        self.assertFalse(instance.stop.is_set())

    def test_setup_cleanup_failure_preserves_lock_and_refuses_foreign_owner(self):
        with tempfile.TemporaryDirectory() as name:
            parent = Path(name)
            parent.chmod(0o700)
            runtime = connection.OwnedRuntime(parent / "owned")
            (runtime.channel / "stale").touch()
            with self.assertRaises(ValueError):
                runtime.close(clean=True)
            self.assertTrue((runtime.scratch / "connection.lock").exists())
            with self.assertRaises(ValueError):
                connection.OwnedRuntime(runtime.root)
        instance = object.__new__(connection.OwnedRuntime)
        instance.fds = {}
        with patch.object(connection.os, "open", return_value=10), \
                patch.object(connection.os, "fstat", return_value=Mock(st_mode=0o40711, st_uid=10001, st_gid=10001)):
            with self.assertRaises(ValueError):
                instance.pin(Path("/synthetic"), 0o711)

    def test_coordinator_normal_verifier_is_import_only_and_uses_pure_transport(self):
        import imp005_verify as verify
        from test_imp024_channel import payload

        fixture = verify.NormalVerify()
        self.assertIsNone(fixture.connection)
        self.assertIsNone(fixture.runtime)
        transport = verify.SyntheticTransport(payload())
        frames = list(transport.events(data(), threading.Event(), time.monotonic() + 2))
        self.assertEqual(decoded(frames[-1])["type"], "response.completed")
        self.assertNotIn(b"generated-synthetic-key-not-real", b"".join(frames))

    def test_key_acquisition_failure_never_starts_and_always_clears_owned_state(self):
        runtime, inference, core = Mock(), Mock(), Mock()
        inference.acquire.side_effect = ValueError("synthetic input rejected")
        with patch.object(connection, "check_runtime"), patch.object(connection.ctypes, "CDLL") as libc, \
                patch.object(connection, "OwnedRuntime", return_value=runtime), \
                patch.object(connection, "explicit_contract"), \
                patch.object(connection, "PlanningHTTPSInference", return_value=inference), \
                patch.object(connection, "Connection", return_value=core), \
                patch.object(connection, "terminal_input", return_value="CONNECT"), \
                patch.object(connection.sys, "stdin", Mock(isatty=lambda: True)), \
                patch.object(connection.sys, "stdout", Mock(isatty=lambda: True)), \
                patch.object(connection, "reap_children"), patch.object(connection.Path, "cwd", return_value=connection.ROOT):
            libc.return_value.prctl.return_value = 0
            with self.assertRaises(ValueError):
                connection.connect()
        core.start.assert_not_called()
        inference.clear.assert_called_once()
        core.close.assert_called_once()
        runtime.close.assert_called_once_with(clean=True)

    def test_normal_synthetic_verifier_preserves_mounted_inode_across_core_restart(self):
        import imp005_verify as verify

        with tempfile.TemporaryDirectory() as name:
            parent = Path(name)
            parent.chmod(0o700)
            fixture = verify.NormalVerify()
            fixture.inputs = parent
            fixture.runtime = connection.OwnedRuntime(parent / "chat")
            fixture.channel = fixture.runtime.channel
            inode = fixture.channel.stat().st_ino
            # Fake Connection, no socket/bwrap/Compose execution in unit checks.
            with patch.object(verify, "Connection", return_value=Mock()), patch.object(verify, "reap_children"), \
                    patch.object(verify, "report"):
                fixture.start_broker()
                fixture.stop_broker()
                fixture.start_broker()
                self.assertEqual(fixture.channel.stat().st_ino, inode)
                fixture.stop_broker()


if __name__ == "__main__":
    unittest.main()
