"""Pure synthetic IMP-023 tests: NO server, namespace, socket or CLI scenarios.

HTTP/socket/process objects below are mocks; actual runtime proof is separately
review-gated, not silently exercised by test discovery.
"""

import base64
import io
import json
from pathlib import Path
import queue
import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import imp002_prototype as prototype
from imp002_relay import MAX_CALLS, ROUTE
import imp023_session as launcher
import imp023_worker as worker


def inference(action, prior=False):
    turns = []
    if prior:
        turns += [{"role": "user", "content": [{"type": "input_text", "text": worker.PROMPTS["seed"]}]},
                  {"role": "assistant", "content": [{"type": "output_text", "text": worker.TEXTS["seed"]}]}]
    turns += [{"role": "user", "content": [{"type": "input_text", "text": worker.PROMPTS[action]}]}]
    return {"model": "synthetic-deployment", "stream": True, "store": False, "input": turns}


def message(action, **updates):
    info = {"id": "msg_synthetic", "sessionID": "ses_synthetic", "role": "assistant",
            "parentID": "msg_user", "finish": "stop", "time": {"completed": 1}}
    info.update(updates)
    return {"info": info, "parts": [{"type": "text", "text": worker.TEXTS[action]}]}


class BoundaryTests(unittest.TestCase):
    def test_launcher_retains_mandatory_mounts_pins_and_changes_only_bootstrap(self):
        root = Path("/tmp/opencode/synthetic")
        previous = prototype.command(root, "synthetic", 1234)
        for mode in prototype.SESSION_MODES:
            args = prototype.command(root, mode, 1234)
            self.assertEqual(args[:args.index("--")], previous[:previous.index("--")])
            self.assertIn("import imp023_worker", args[args.index("-c") + 1])
            self.assertNotIn("serve", args)
            self.assertNotIn("--share-net", args)
            self.assertEqual(args[-2], mode)
        self.assertEqual(MAX_CALLS, 4)

    def test_capability_failure_never_launches_or_discloses(self):
        output = io.StringIO()
        with patch.object(launcher.sys, "argv", ["imp023_session.py", "startup"]), \
                patch.object(launcher, "run", side_effect=PermissionError("synthetic-private-detail")) as run, \
                patch.object(launcher.sys, "stdout", output):
            self.assertEqual(launcher.main(), 1)
        run.assert_called_once_with("imp023-startup")
        self.assertEqual(json.loads(output.getvalue()),
                         {"success": False, "session_capability_unavailable": True})
        self.assertNotIn("synthetic-private-detail", output.getvalue())

    def test_session_mode_cannot_select_host_live_transport(self):
        with patch.object(prototype, "check_runtime") as runtime:
            with self.assertRaises(prototype.CapabilityError):
                prototype.run("imp023-history", transport=object())
        runtime.assert_not_called()

    def test_private_fixed_server_command_and_denied_agent(self):
        command = worker.server_command(1234)
        self.assertEqual(command, ["/bin/opencode", "--log-level", "ERROR", "serve", "--hostname",
                                   "127.0.0.1", "--port", "1234", "--mdns=false"])
        config = worker.generated_config(5678)
        self.assertEqual(config["permission"], {"*": "deny"})
        self.assertEqual(config["agent"]["tech-lead"]["permission"], {"*": "deny"})
        self.assertFalse(config["provider"]["azure"]["models"]["synthetic-deployment"]["toolcall"])
        self.assertEqual(config["provider"]["azure"]["options"]["maxRetries"], 0)
        for name in ("plugin", "mcp"):
            self.assertFalse(config[name])

    def test_routes_deny_general_api_targets_and_injected_session_ids(self):
        self.assertEqual(worker.route("GET", "health"), "/global/health")
        self.assertEqual(worker.route("GET", "history", "ses_synthetic"), "/session/ses_synthetic/message?limit=16")
        for method, operation, session in [("POST", "shell", "ses_synthetic"), ("GET", "config", None),
                                           ("PUT", "auth", None), ("GET", "doc", None),
                                           ("POST", "prompt", "ses_synthetic?x=1"),
                                           ("POST", "prompt", "ses_synthetic/../../auth"),
                                           ("POST", "prompt", "http://host.invalid"),
                                           ("GET", "event", "ses_synthetic")]:
            with self.subTest(operation=operation), self.assertRaises(worker.Failed):
                worker.route(method, operation, session)

    def test_driver_generated_auth_no_prompt_tool_override_and_204_acceptance(self):
        connection, response = MagicMock(), MagicMock()
        connection.getresponse.return_value = response
        response.status, response.read.return_value = 204, b""
        driver = worker.Driver(1234, "generated-synthetic-password")
        with patch.object(worker.http.client, "HTTPConnection", return_value=connection) as client:
            driver.prompt("ses_synthetic", "seed")
        client.assert_called_once_with("127.0.0.1", 1234, timeout=2)
        method, path, body, headers = connection.request.call_args.args
        self.assertEqual((method, path), ("POST", "/session/ses_synthetic/prompt_async"))
        self.assertEqual(json.loads(body), {"model": worker.MODEL, "agent": "tech-lead",
                                          "parts": [{"type": "text", "text": worker.PROMPTS["seed"]}]})
        self.assertEqual(headers["Authorization"], "Basic " + base64.b64encode(
            b"synthetic:generated-synthetic-password").decode())
        self.assertEqual(headers["x-opencode-directory"], "/project")
        self.assertEqual(driver.prompts, 1)
        connection.close.assert_called_once()

    def test_driver_denial_redirect_and_body_bounds_close_connections(self):
        for status, raw, authenticated in [(401, b"denied", False), (302, b"", True),
                                            (200, b"x" * (worker.MAX_API_BODY + 1), True)]:
            connection, response = MagicMock(), MagicMock()
            connection.getresponse.return_value = response
            response.status, response.read.return_value = status, raw
            with patch.object(worker.http.client, "HTTPConnection", return_value=connection):
                driver = worker.Driver(1234, "synthetic")
                if authenticated:
                    with self.assertRaises(worker.Failed):
                        driver.request("GET", "health")
                else:
                    self.assertEqual(driver.request("GET", "health", authenticated=False), 401)
                    self.assertNotIn("Authorization", connection.request.call_args.args[3])
            connection.close.assert_called_once()

    def test_server_runtime_auth_health_and_bounded_shutdown_without_host_child(self):
        driver = MagicMock()
        driver.port = 1234
        driver.request.return_value = {"healthy": True, "version": "synthetic-updated-version"}
        process = MagicMock()
        process.poll.side_effect = [None, None, 0]
        process.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 2), 0]
        server = worker.Server(driver, "generated-synthetic")
        with patch.object(worker.os, "environ", {"HOME": "/home/worker"}), \
                patch.object(worker.subprocess, "Popen", return_value=process) as child, \
                patch.object(worker.os, "killpg") as kill, \
                patch.object(worker.socket, "socket") as peer:
            peer.return_value.__enter__.return_value.connect_ex.return_value = 111
            server.start()
            server.close()
        self.assertEqual(child.call_args.kwargs["env"], {"HOME": "/home/worker",
            "OPENCODE_SERVER_USERNAME": "synthetic", "OPENCODE_SERVER_PASSWORD": "generated-synthetic"})
        self.assertTrue(child.call_args.kwargs["start_new_session"])
        self.assertEqual(child.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual([call.args[1] for call in kill.call_args_list], [15, 9])
        self.assertIsNone(server.process)

    def test_health_accepts_updated_versions_but_rejects_unhealthy_or_incompatible_schema(self):
        for version in ("1.18.34", "1.19.0", "future-build"):
            driver = MagicMock(port=1234)
            driver.request.return_value = {"healthy": True, "version": version}
            with self.subTest(version=version), \
                    patch.object(worker.os, "environ", {"HOME": "/home/worker"}), \
                    patch.object(worker.subprocess, "Popen") as child:
                child.return_value.poll.return_value = None
                worker.Server(driver, "synthetic").start()
                driver.request.assert_called_once_with("GET", "health")
        for health in (None, {"healthy": False, "version": "1.19.0"},
                       {"healthy": 1, "version": "1.19.0"}, {"healthy": True},
                       {"healthy": True, "version": 119}, {"healthy": True, "version": ""},
                       {"healthy": True, "version": "x" * 65},
                       {"healthy": True, "version": "unsafe\nvalue"},
                       {"healthy": True, "version": "1.19.0", "extra": True}):
            driver = MagicMock(port=1234)
            driver.request.return_value = health
            with self.subTest(health=health), \
                    patch.object(worker.os, "environ", {"HOME": "/home/worker"}), \
                    patch.object(worker.subprocess, "Popen") as child:
                child.return_value.poll.return_value = None
                with self.assertRaises(worker.Failed):
                    worker.Server(driver, "synthetic").start()
                driver.request.assert_called_once_with("GET", "health")


class FixtureTests(unittest.TestCase):
    def test_history_oracle_accepts_exact_roles_and_rejects_fresh_leak_or_missing_history(self):
        for action in worker.PROMPTS:
            data = inference(action, prior=action == "recall")
            data["input"].insert(0, {"role": "system", "content": "synthetic system"})
            self.assertEqual(worker.fixture_text(data), (action, worker.TEXTS[action]))
        for data in (inference("recall"), inference("fresh", prior=True)):
            with self.assertRaises(worker.Failed):
                worker.fixture_text(data)
        data = inference("recall", prior=True)
        data["input"][1]["role"] = "user"
        with self.assertRaises(worker.Failed):
            worker.fixture_text(data)

    def handler(self, action, prior=False):
        # Construct without BaseHTTPRequestHandler.__init__ (which handles sockets).
        fixture = SimpleNamespace(calls=0, action=None, history_valid=False,
                                  **{name: threading.Event() for name in (
                                      "release", "delta_sent", "completed", "cancelled", "failed", "stop")})
        handler = worker.FixtureHandler.__new__(worker.FixtureHandler)
        body = json.dumps(inference(action, prior)).encode()
        handler.server = SimpleNamespace(fixture=fixture)
        handler.path = ROUTE
        handler.headers = MagicMock()
        handler.headers.get_all.return_value = [str(len(body))]
        handler.headers.get.return_value = None
        handler.rfile = io.BytesIO(body)
        handler.connection = MagicMock()
        return handler, fixture

    def test_delta_gate_prevents_completion_until_driver_release(self):
        handler, fixture = self.handler("seed")
        sent = []

        def release(_):
            self.assertTrue(fixture.delta_sent.is_set())
            self.assertFalse(fixture.completed.is_set())
            self.assertFalse(any(b"response.completed" in block for block in sent))
            fixture.release.set()
            return True

        handler.connection.sendall.side_effect = sent.append
        with patch.object(worker, "relay_check") as relay, patch.object(fixture.release, "wait", side_effect=release):
            handler.do_POST()
        relay.assert_called_once()
        self.assertTrue(fixture.completed.is_set())
        self.assertFalse(fixture.failed.is_set())
        self.assertTrue(any(b"response.completed" in block for block in sent))

    def test_abort_cancels_and_failure_has_no_success_terminal(self):
        for action in ("abort", "failure"):
            handler, fixture = self.handler(action)
            sent = []
            handler.connection.sendall.side_effect = sent.append
            with patch.object(worker, "relay_check"), \
                    patch.object(fixture.release, "wait", return_value=action == "failure"), \
                    patch.object(worker.select, "select", return_value=([handler.connection], [], [])):
                handler.do_POST()
            self.assertFalse(fixture.completed.is_set())
            self.assertFalse(any(b"response.completed" in block for block in sent))
            if action == "abort":
                self.assertTrue(fixture.cancelled.is_set())
                self.assertFalse(fixture.failed.is_set())
            else:
                self.assertTrue(fixture.failed.is_set())
                self.assertTrue(any(b"event: error" in block for block in sent))

    def test_gated_failure_frame_matches_pinned_error_schema_and_terminal_category(self):
        # Source-derived checks, NOT execution of the SDK: OpenAI 3.0.88
        # responses/openai-responses-api.ts requires a numeric sequence_number
        # and nested type/code/message strings. OpenCode v1.18.34 provider/error.ts
        # reads error.code and returns isRetryable=false for invalid_prompt.
        # Without the sequence the SDK's permissive unknown_chunk arm wins; a
        # top-level code alone defaults to retryable in OpenCode after output.
        handler, fixture = self.handler("failure")
        sent = []
        handler.connection.sendall.side_effect = sent.append

        def release(_):
            self.assertTrue(fixture.delta_sent.is_set())
            self.assertFalse(fixture.failed.is_set() or fixture.completed.is_set())
            self.assertFalse(any(b"event: error" in block for block in sent))
            fixture.release.set()
            return True

        with patch.object(worker, "relay_check") as relay, \
                patch.object(fixture.release, "wait", side_effect=release):
            handler.do_POST()

        # Decode the emitted HTTP chunks, not a disconnected test-only constant.
        frames = []
        for block in sent[1:-1]:
            length, payload = block.split(b"\r\n", 1)
            self.assertEqual(int(length, 16), len(payload) - 2)
            event, _ = worker.parse_event(io.BytesIO(payload[:-2]))
            frames.append(event)
        self.assertEqual([frame["sequence_number"] for frame in frames], list(range(5)))
        self.assertEqual(frames[-2]["type"], "response.output_text.delta")
        self.assertEqual(frames[-2]["delta"], worker.TEXTS["failure"])
        self.assertEqual(frames[-1], {"type": "error", "sequence_number": 4, "error": {
            "type": "invalid_request_error", "code": "invalid_prompt",
            "message": "synthetic terminal rejection", "param": None}})
        self.assertFalse(any(frame["type"] == "response.completed" for frame in frames))
        self.assertEqual(sent[-1], b"0\r\n\r\n")
        self.assertTrue(fixture.failed.is_set())
        self.assertFalse(fixture.completed.is_set())
        self.assertEqual(fixture.calls, 1)
        relay.assert_called_once()

    def test_tool_payload_and_fifth_call_never_reach_host_relay(self):
        for fifth in (False, True):
            handler, fixture = self.handler("seed")
            if fifth:
                fixture.calls = MAX_CALLS
            else:
                data = inference("seed")
                data["tools"] = [{"type": "function", "name": "synthetic"}]
                body = json.dumps(data).encode()
                handler.headers.get_all.return_value = [str(len(body))]
                handler.rfile = io.BytesIO(body)
            with patch.object(worker, "relay_check") as relay:
                handler.do_POST()
            relay.assert_not_called()
            self.assertTrue(fixture.failed.is_set())
            self.assertFalse(fixture.delta_sent.is_set())

    def test_relay_check_only_fixed_inference_no_server_auth(self):
        peer, response = MagicMock(), MagicMock()
        response.status = 200
        response.read.return_value = b"response.completed"
        peer.__enter__.return_value = peer
        with patch.object(worker.socket, "socket", return_value=peer), \
                patch.object(worker.http.client, "HTTPResponse", return_value=response):
            worker.relay_check(json.dumps(inference("seed")).encode())
        peer.connect.assert_called_once_with("/relay/inference.sock")
        request = peer.sendall.call_args.args[0]
        self.assertTrue(request.startswith(b"POST /openai/v1/responses HTTP/1.1\r\n"))
        self.assertNotIn(b"Authorization", request)
        self.assertNotIn(b"/session", request)


class ProtocolTests(unittest.TestCase):
    def test_sse_close_interrupts_detached_socket_before_thread_join(self):
        events = worker.Events.__new__(worker.Events)
        events.stopped = threading.Event()
        events.connection = MagicMock(sock=None)
        events.response = MagicMock()
        events.thread = MagicMock()
        events.thread.is_alive.return_value = False
        detached = events.connection._imp023_socket
        calls = []
        detached.shutdown.side_effect = lambda *_: calls.append("shutdown")
        events.thread.join.side_effect = lambda *_: calls.append("join")
        events.response.close.side_effect = lambda: calls.append("response-close")
        events.close()
        self.assertTrue(events.stopped.is_set())
        self.assertEqual(calls, ["shutdown", "join", "response-close"])

    def test_sse_parser_bound_and_native_delta_session_filter(self):
        payload = {"type": "message.part.delta", "properties": {"sessionID": "ses_synthetic",
                   "field": "text", "delta": worker.TEXTS["seed"]}}
        event, size = worker.parse_event(io.BytesIO(("event: message\r\ndata: " + json.dumps(payload) + "\r\n\r\n").encode()))
        self.assertEqual(event, payload)
        events = worker.Events.__new__(worker.Events)
        events.queue = queue.Queue()
        events.queue.put({"type": "session.error", "properties": {"sessionID": "ses_other"}})
        events.queue.put(payload)
        events.delta("ses_synthetic", worker.TEXTS["seed"])
        events.queue.put({"type": "session.error", "properties": {"sessionID": "ses_synthetic"}})
        with self.assertRaises(worker.Failed):
            events.delta("ses_synthetic", worker.TEXTS["seed"])
        for raw in (b"data: " + b"x" * 8193 + b"\n\n", b"data: []\n\n", b""):
            with self.assertRaises((worker.Failed, ValueError)):
                worker.parse_event(io.BytesIO(raw))

    def test_idle_and_partial_or_error_history_never_mean_success(self):
        self.assertTrue(worker.successful(message("seed"), "seed"))
        for updates in ({"error": {"name": "MessageAbortedError"}}, {"error": {"name": "APIError"}},
                        {"time": {}}, {"finish": "length"}, {"finish": None}):
            self.assertFalse(worker.successful(message("seed", **updates), "seed"))
        self.assertFalse(worker.successful(None, "seed"))
        self.assertFalse(worker.successful(message("fresh"), "seed"))
        user = {"info": {"id": "msg_user", "role": "user"}, "parts": [{"type": "text", "text": worker.PROMPTS["seed"]}]}
        self.assertEqual(worker.assistant([user, message("seed")], "seed"), message("seed"))
        with self.assertRaises(worker.Failed):
            worker.assistant([user, message("seed")], "recall")

    def test_history_rejects_other_session_and_tool_parts(self):
        driver = worker.Driver(1234, "synthetic")
        for history in ([message("seed", sessionID="ses_other")],
                        [{"info": {"sessionID": "ses_synthetic"}, "parts": [{"type": "tool"}]}]):
            with patch.object(driver, "request", return_value=history), self.assertRaises(worker.Failed):
                driver.history("ses_synthetic")


class ScenarioTests(unittest.TestCase):
    """Exercise scenario orchestration with ALL runtime/I/O seams mocked."""

    def run_scenario(self, mode, fail_delta=False):
        fixture = MagicMock()
        fixture.calls = 0
        fixture.server.server_address = ("127.0.0.1", 5678)
        fixture.completed = threading.Event()
        fixture.delta_sent = threading.Event()
        fixture.release = threading.Event()
        fixture.failed = threading.Event()
        fixture.cancelled = threading.Event()
        driver, server, events = MagicMock(), MagicMock(), MagicMock()
        driver.prompts = 0
        driver.create.side_effect = ["ses_first", "ses_second"]
        driver.request.side_effect = lambda method, op, *args, **kw: (
            401 if kw.get("authenticated") is False else {"id": "ses_first"} if op == "read" else True)
        saved = [message("seed", sessionID="ses_first")]

        def reset():
            for event in (fixture.completed, fixture.delta_sent, fixture.release,
                          fixture.failed, fixture.cancelled):
                event.clear()

        def prompt(session, action):
            fixture.calls += 1
            driver.prompts += 1
            fixture.action, fixture.history_valid = action, True
            fixture.delta_sent.set()

        def history(session):
            return [] if session == "ses_second" else saved

        def waited(*args, **kwargs):
            if kwargs.get("success") is False:
                if fixture.action == "abort":
                    fixture.cancelled.set()
                else:
                    fixture.failed.set()
                return [message(fixture.action, error={"name": "SyntheticError"})]
            self.assertTrue(fixture.release.is_set())
            fixture.completed.set()
            return saved

        fixture.reset.side_effect = reset
        driver.prompt.side_effect = prompt
        driver.history.side_effect = history
        driver.idle.side_effect = lambda *_: fixture.completed.is_set()
        if fail_delta:
            events.delta.side_effect = worker.Failed()
        checks = dict.fromkeys(worker.CHECKS[mode], False)
        with patch.object(worker, "Fixture", return_value=fixture), \
                patch.object(worker.socket, "socket") as reservation, \
                patch.object(worker, "Driver", return_value=driver), \
                patch.object(worker, "Server", return_value=server), \
                patch.object(worker, "Events", return_value=events), \
                patch.object(worker, "wait_history", side_effect=waited), \
                patch.object(worker, "assistant", side_effect=lambda *args: args[0][-1]), \
                patch.object(worker, "open", unittest.mock.mock_open()):
            reservation.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 1234)
            if fail_delta:
                with self.assertRaises(worker.Failed):
                    worker.scenario(mode, checks)
            else:
                worker.scenario(mode, checks)
        return checks, driver, server, events, fixture

    def test_reconnect_restart_reads_saved_state_and_submits_only_explicit_second_turn(self):
        checks, driver, server, events, fixture = self.run_scenario("imp023-reconnect")
        self.assertTrue(all(checks.values()))
        self.assertEqual(driver.prompt.call_args_list, [unittest.mock.call("ses_first", "seed"),
                                                       unittest.mock.call("ses_first", "recall")])
        self.assertEqual(server.start.call_count, 2)
        self.assertEqual(server.close.call_count, 2)
        self.assertEqual(fixture.calls, 2)

    def test_history_and_interruption_orchestration_keep_scenario_call_budgets(self):
        for mode, expected in (("imp023-history", 3), ("imp023-interrupt", 2)):
            with self.subTest(mode=mode):
                checks, driver, server, events, fixture = self.run_scenario(mode)
                self.assertTrue(all(checks.values()))
                self.assertEqual(driver.prompt.call_count, expected)
                fixture.close.assert_called_once()

    def test_protocol_failure_still_closes_owned_event_server_and_fixture(self):
        checks, driver, server, events, fixture = self.run_scenario("imp023-history", fail_delta=True)
        self.assertFalse(checks["successful_history"])
        self.assertTrue(checks["server_child_stopped"] and checks["private_listener_closed"]
                        and checks["fixture_stopped"])
        events.close.assert_called_once()
        server.close.assert_called_once()
        fixture.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
