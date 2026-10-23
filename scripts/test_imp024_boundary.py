"""Pure synthetic checks only: runtime/server/socket/file operations are mocked."""

import io
import json
import fnmatch
import posixpath
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import imp002_prototype as prototype
import imp002_relay as relay
import imp023_worker as previous
import imp024_inference as inference
import imp024_protocol as protocol
import imp024_session as launcher
import imp024_worker as worker
import imp024_diagnostic as diagnostic


def request():
    return {"model": relay.MODEL, "stream": True, "store": False,
        "tools": protocol.fixture_definitions(), "max_output_tokens": protocol.MAX_TOKENS,
        "input": [{"role": "user", "content": "IMP024_PLANNING"}]}


def call(name="read", args=None, call_id="call_read"):
    return {"type": "function_call", "name": name, "call_id": call_id,
            "arguments": json.dumps(args or {"filePath": "/project/PROJECT.md"})}


def validate(data, planning=True):
    return relay.validate("POST", relay.ROUTE, json.dumps(data).encode(), planning=planning)


def frames(blocks):
    return [relay.decode(raw.split(b"data: ", 1)[1].strip()) for raw in blocks]


class InferenceTests(unittest.TestCase):
    def test_diagnostic_failure_never_outputs_raw_runtime_or_exception_and_restores_validator(self):
        original = relay.validate
        output = io.StringIO()
        def failure(_):
            print("synthetic-private-runtime")
            raise OSError("synthetic-private-detail")
        with patch.object(diagnostic.prototype, "run", side_effect=failure) as run, \
                patch.object(diagnostic.sys, "stdout", output):
            self.assertEqual(diagnostic.main(), 1)
        run.assert_called_once_with("imp024-planning")
        self.assertEqual(json.loads(output.getvalue()), {"diagnostic_completed": False, "requests": []})
        self.assertIs(relay.validate, original)

    def test_diagnostic_delegates_validation_unchanged_and_projects_fixed_shapes(self):
        records = []
        original = MagicMock(side_effect=relay.Denied("private synthetic detail"))
        data = request()
        data["input"] += [call(), {"type": "function_call_output", "call_id": "call_read",
            "output": [{"type": "input_text", "text": "synthetic-private-text"}]}]
        body = json.dumps(data).encode()
        with self.assertRaises(relay.Denied):
            diagnostic.observe(original, records)("POST", relay.ROUTE, body, planning=True)
        original.assert_called_once_with("POST", relay.ROUTE, body, planning=True)
        self.assertNotIn("result_categories", records[0])
        self.assertEqual(records, [{"definitions_valid": True,
            "input_types": ["message", "function_call", "function_call_output"],
            "result_shapes": ["text_parts"], "denial": "other"}])
        self.assertNotIn("synthetic-private", json.dumps(records))

    def test_measured_native_read_denial_does_not_retry_fixture_or_emit_tool_completion(self):
        data = request()
        # Measured request: native schemas accepted; read completed as a rule
        # denial string; synthetic oracle used to throw -> retryable HTTP 503.
        data["input"] += [call(), {"type": "function_call_output", "call_id": "call_read",
            "output": diagnostic.RULE_DENIAL + " Here are some of the relevant rules []"}]
        self.assertEqual(diagnostic.request_shape(json.dumps(data).encode())["result_categories"], ["native_rule_denial"])
        data = validate(data)
        synthetic = launcher.SyntheticPlanning("planning")
        synthetic.calls = 1
        instance = relay.SyntheticRelay.__new__(relay.SyntheticRelay)
        instance.transport = synthetic
        instance.pdf_manifest = None
        instance.planning = True
        instance.max_response = protocol.MAX_RESPONSE
        instance.denied = 0
        connection = MagicMock()
        with patch.object(relay.select, "select", return_value=([], [], [])):
            instance.stream(connection, data, threading.Event(), time.monotonic() + 2)
        emitted = b"".join(entry.args[0] for entry in connection.sendall.call_args_list)
        self.assertTrue(emitted.startswith(b"HTTP/1.1 200 OK"))
        self.assertIn(b'"sequence_number":0', emitted)
        self.assertIn(b'"code":"invalid_prompt"', emitted)
        self.assertNotIn(b"503 Service", emitted)
        self.assertNotIn(b"function_call", emitted)
        self.assertNotIn(b"response.completed", emitted)
        self.assertFalse(synthetic.validated)
        self.assertEqual(synthetic.calls, 2)

    def test_native_definition_call_result_roundtrip_and_text_ids(self):
        data = request()
        data["input"] += [call(), {"type": "function_call_output", "call_id": "call_read", "output": "Synthetic file"},
                            {"role": "assistant", "id": "msg_native", "content": [{"type": "output_text", "text": "hello"}]}]
        self.assertNotIn("id", validate(data)["input"][-1])
        with self.assertRaises(relay.Denied):
            validate(data, False)
        output = list(inference.normalized_events(iter(inference.native_response(calls=[call()])), request()))
        parsed = frames(output)
        self.assertEqual(parsed[-1]["type"], "response.completed")
        self.assertEqual(parsed[-1]["response"]["output"][0]["name"], "read")
        self.assertEqual([item["sequence_number"] for item in parsed], list(range(len(parsed))))

    def test_provider_tools_unknown_functions_remote_refs_and_schema_drift_denied(self):
        for replacement in ({"type": "web_search"}, {"type": "mcp", "server_url": "https://unit.invalid"},
                            dict(protocol.fixture_definitions()[0], name="shell"),
                            dict(protocol.fixture_definitions()[0], parameters={"$ref": "https://unit.invalid/schema"})):
            data = request()
            data["tools"] = [replacement]
            with self.subTest(replacement=replacement), self.assertRaises(relay.Denied):
                validate(data)
        data = request()
        data["tools"][0]["parameters"]["properties"]["filePath"] = {"type": "object"}
        with self.assertRaises(relay.Denied):
            validate(data)
        for name in ("shell", "task", "webfetch", "skill", "apply_patch", "unknown", "mcp_synthetic"):
            data = request()
            data["tools"][0]["name"] = name
            with self.subTest(tool=name), self.assertRaises(relay.Denied):
                validate(data)

    def test_bad_call_paths_pairing_and_result_media_denied(self):
        for items in ([call(args={"filePath": "/project/../tmp/generated.json"})],
                      [call(), call()],
                      [{"type": "function_call_output", "call_id": "call_read", "output": "orphan"}],
                      [call(), {"type": "function_call_output", "call_id": "call_read", "output": [{"type": "input_image"}]}],
                      [call(), {"role": "user", "content": "next"}]):
            data = request()
            data["input"] += items
            with self.subTest(items=items), self.assertRaises(relay.Denied):
                validate(data)

    def test_function_output_is_not_released_before_consistent_terminal(self):
        good = inference.native_response(calls=[call()])
        broken = frames(good)
        broken[-1]["response"]["output"][0]["arguments"] = '{"filePath":"/tmp/generated.json"}'
        for source in (good[:-1], [inference.frame(event.pop("type"), event, i) for i, event in enumerate(broken)],
                       inference.native_response(calls=[call("shell", {"command": "synthetic"})])):
            emitted = []
            with self.assertRaises((protocol.Invalid, relay.Denied)):
                for event in inference.normalized_events(iter(source), request()):
                    emitted.append(event)
            self.assertFalse(any(b"function_call" in event or b"response.completed" in event for event in emitted))

    def test_text_stream_and_function_complete_preserve_native_shapes(self):
        for source in (inference.native_response("hello"), inference.native_response("hello", [call()])):
            raw = b"".join(source)
            chunks = (raw[index:index + 17] for index in range(0, len(raw), 17))
            parsed = frames(list(inference.normalized_events(chunks, request())))
            self.assertEqual(parsed[-1]["type"], "response.completed")
            self.assertEqual(sum(event["type"] == "response.output_text.delta" for event in parsed), 1)
            self.assertEqual(parsed[-1]["response"]["output"][0]["content"][0]["text"], "hello")

    def test_actual_relay_terminal_error_after_delta_uses_measured_nonretryable_frame(self):
        def broken(*_):
            yield b"event: response.output_text.delta\ndata: {}\n\n"
            raise ValueError("synthetic-private-detail")
        instance = relay.SyntheticRelay.__new__(relay.SyntheticRelay)
        instance.transport = MagicMock()
        instance.pdf_manifest = None
        instance.transport.events.side_effect = broken
        instance.planning = False
        instance.max_response = relay.MAX_RESPONSE
        instance.denied = 0
        connection = MagicMock()
        with patch.object(relay.select, "select", return_value=([], [], [])):
            instance.stream(connection, {}, threading.Event(), time.monotonic() + 2)
        blocks = [entry.args[0] for entry in connection.sendall.call_args_list]
        error = blocks[-1].split(b"\r\n", 1)[1].split(b"\r\n0\r\n", 1)[0]
        event = frames([error])[0]
        self.assertEqual(event["error"]["code"], "invalid_prompt")
        self.assertIsInstance(event["sequence_number"], int)
        self.assertNotIn(b"synthetic-private-detail", b"".join(blocks))
        self.assertFalse(any(b"response.completed" in block for block in blocks))

    def test_planning_relay_rejects_malicious_output_and_closes_transport(self):
        closed = []
        def malicious(*_):
            try:
                yield from inference.native_response(calls=[call("shell", {"command": "synthetic"})])
            finally:
                closed.append(True)
        instance = relay.SyntheticRelay.__new__(relay.SyntheticRelay)
        instance.transport = MagicMock()
        instance.pdf_manifest = None
        instance.transport.events.side_effect = malicious
        instance.planning = True
        instance.max_response = protocol.MAX_RESPONSE
        instance.denied = 0
        connection = MagicMock()
        with patch.object(relay.select, "select", return_value=([], [], [])):
            instance.stream(connection, request(), threading.Event(), time.monotonic() + 2)
        emitted = b"".join(entry.args[0] for entry in connection.sendall.call_args_list)
        self.assertIn(b'"code":"invalid_prompt"', emitted)
        self.assertNotIn(b'"name":"shell"', emitted)
        self.assertNotIn(b"response.completed", emitted)
        self.assertEqual(instance.denied, 1)
        self.assertEqual(closed, [True])

    def test_large_planning_context_is_bounded_not_silently_truncated(self):
        data = request()
        data["input"] = [{"role": "user", "content": "x" * 60000} for _ in range(3)]
        self.assertEqual(len(validate(data)["input"]), 3)
        with self.assertRaises(relay.Denied):
            validate(data, False)
        data["input"] *= 3
        with self.assertRaises(relay.Denied):
            validate(data)


class DriverTests(unittest.TestCase):
    def test_abort_rejects_native_orphaned_question_then_stale_reply_cannot_continue(self):
        driver = self.driver()
        driver.active_session, driver.turn_text = "ses_A", "Synthetic cancel"
        prompts = [{"question": "Synthetic?", "header": "Scope", "options": [{"label": "Yes", "description": "Choice"}]}]
        questions = [{"id": "que_orphan", "sessionID": "ses_A", "questions": prompts},
                     {"id": "que_other", "sessionID": "ses_B", "questions": prompts}]
        history = [{"info": {"id": "msg_user", "role": "user", "sessionID": "ses_A"},
                    "parts": [{"type": "text", "text": "Synthetic cancel"}]},
                   {"info": {"role": "assistant", "sessionID": "ses_A", "parentID": "msg_user",
                    "error": {"name": "MessageAbortedError"}, "time": {"completed": 1}}, "parts": []}]
        calls = []
        def request(method, operation, target=None, body=None, **kwargs):
            calls.append((method, operation, target))
            if operation == "abort":
                # Native abort reports success and interrupted history, but DOES
                # NOT clear Question.Service's separately scoped pending entry.
                return True
            if operation == "status":
                return {}
            if operation == "history":
                return history
            if operation == "questions":
                return list(questions)
            if operation == "permissions":
                return []
            if operation == "question-reject":
                with self.assertRaises(protocol.Invalid):
                    driver.question_reply("ses_A", "que_orphan", [["Yes"]])
                questions[:] = [value for value in questions if value["id"] != target]
                return True
            self.fail("Unexpected native operation")
        with patch.object(driver, "_request", side_effect=request):
            self.assertTrue(driver.abort("ses_A"))
            self.assertEqual(driver.pending("ses_A", "questions"), [])
            self.assertEqual(driver.pending("ses_B", "questions")[0]["id"], "que_other")
            with self.assertRaises(protocol.Invalid):
                driver.question_reply("ses_A", "que_orphan", [["Yes"]])
        self.assertIn(("POST", "question-reject", "que_orphan"), calls)
        self.assertNotIn(("POST", "question-reply", "que_orphan"), calls)
        self.assertEqual(history[-1]["info"]["error"]["name"], "MessageAbortedError")
        self.assertEqual(driver.active_session, "ses_A")  # not a successful/resumable turn

    def test_abort_cleanup_failure_remains_interrupted_and_native_pending_is_not_hidden(self):
        driver = self.driver()
        driver.active_session, driver.turn_text = "ses_A", "Synthetic cancel"
        question = {"id": "que_orphan", "sessionID": "ses_A", "questions": [
            {"question": "Synthetic?", "header": "Scope", "options": [{"label": "Yes", "description": "Choice"}]}]}
        history = [{"info": {"id": "msg_user", "role": "user", "sessionID": "ses_A"}, "parts": [{"type": "text", "text": "Synthetic cancel"}]},
            {"info": {"role": "assistant", "sessionID": "ses_A", "parentID": "msg_user", "time": {"completed": 1},
                "error": {"name": "MessageAbortedError"}}, "parts": []}]
        def request(method, operation, *args, **kwargs):
            if operation == "question-reject":
                raise OSError("synthetic native cleanup unavailable")
            return {"abort": True, "status": {}, "history": history,
                    "questions": [question], "permissions": []}[operation]
        with patch.object(driver, "_request", side_effect=request), \
                patch.object(previous.http.client, "HTTPConnection") as connection:
            with self.assertRaises(OSError):
                driver.abort("ses_A")
            self.assertEqual(driver.pending("ses_A", "questions"), [question])
            with self.assertRaises(protocol.Invalid):
                driver.question_reply("ses_A", "que_orphan", [["Yes"]])
            with self.assertRaises(protocol.Invalid):
                driver.open("POST", "question-reply", "que_orphan", {"answers": [["Yes"]]})
            with self.assertRaises(protocol.Invalid):
                driver.finish("ses_A")
        connection.assert_not_called()
        self.assertIn("ses_A", driver.cancelled_sessions)

    def test_abort_rechecks_permission_list_after_native_session_wide_rejection(self):
        driver = self.driver()
        driver.active_session, driver.turn_text = "ses_A", "Synthetic cancel"
        history = [{"info": {"id": "msg_user", "role": "user", "sessionID": "ses_A"}, "parts": [{"type": "text", "text": "Synthetic cancel"}]},
            {"info": {"role": "assistant", "sessionID": "ses_A", "parentID": "msg_user", "time": {"completed": 1},
                "error": {"name": "MessageAbortedError"}}, "parts": []}]
        pending = [{"id": "per_one", "sessionID": "ses_A"}, {"id": "per_two", "sessionID": "ses_A"}]
        replies = []
        def request(method, operation, target=None, body=None, **kwargs):
            if operation == "permission-reply":
                self.assertEqual(body, {"reply": "reject"})
                replies.append(target)
                pending.clear()  # pinned Permission.reply reject clears same-session requests
                return True
            return {"abort": True, "status": {}, "history": history,
                    "questions": [], "permissions": list(pending)}[operation]
        with patch.object(driver, "_request", side_effect=request):
            self.assertTrue(driver.abort("ses_A"))
        self.assertEqual(replies, ["per_one"])

    def test_abort_cleanup_cannot_turn_native_success_into_aborted_status(self):
        driver = self.driver()
        driver.active_session, driver.turn_text = "ses_A", "Synthetic cancel"
        history = [{"info": {"id": "msg_user", "role": "user"}, "parts": [{"type": "text", "text": "Synthetic cancel"}]},
            {"info": {"role": "assistant", "parentID": "msg_user", "time": {"completed": 1}, "finish": "stop"}, "parts": []}]
        with patch.object(driver, "_request", return_value=True), \
                patch.object(worker, "wait_terminal", return_value=history), \
                patch.object(driver, "pending") as pending:
            with self.assertRaises(protocol.Invalid):
                driver.abort("ses_A")
        pending.assert_not_called()
        self.assertNotIn("error", history[-1]["info"])

    def test_abort_real_driver_requests_delete_orphan_and_verify_native_state(self):
        # Exercise actual fixed routes, reply guards and JSON framing; only HTTP
        # connections/responses are mocks. No server/socket/worker runs here.
        driver = self.driver()
        driver.active_session, driver.turn_text = "ses_A", "Synthetic cancel"
        question = {"id": "que_orphan", "sessionID": "ses_A", "questions": [
            {"question": "Synthetic?", "header": "Scope", "options": [{"label": "Yes", "description": "Choice"}]}]}
        history = [{"info": {"id": "msg_user", "role": "user", "sessionID": "ses_A"},
                    "parts": [{"type": "text", "text": "Synthetic cancel"}]},
            {"info": {"role": "assistant", "sessionID": "ses_A", "parentID": "msg_user",
                "time": {"completed": 1}, "error": {"name": "MessageAbortedError"}}, "parts": []}]
        for deletion_works in (False, True):
            driver.cancelled_sessions.clear()
            pending = [question]
            sent = []
            def connection(*args, **kwargs):
                peer, response = MagicMock(), MagicMock()
                response.status = 200
                response.getheader.return_value = "application/json"
                peer.getresponse.return_value = response
                def request(method, path, body, headers):
                    sent.append((method, path))
                    if path == "/session/ses_A/abort":
                        value = True
                    elif path == "/session/status":
                        value = {}
                    elif path == "/session/ses_A/message?limit=16":
                        value = history
                    elif path == "/question":
                        value = list(pending)
                    elif path == "/permission":
                        value = []
                    elif path == "/question/que_orphan/reject":
                        self.assertIsNone(body)
                        if deletion_works:
                            pending.clear()
                        value = True
                    else:
                        self.fail("Unexpected fixed route")
                    response.read.return_value = json.dumps(value).encode()
                peer.request.side_effect = request
                return peer
            with patch.object(previous.http.client, "HTTPConnection", side_effect=connection):
                if deletion_works:
                    self.assertTrue(driver.abort("ses_A"))
                else:
                    with self.assertRaises(protocol.Invalid):
                        driver.abort("ses_A")
                with self.assertRaises(protocol.Invalid):
                    driver.question_reply("ses_A", "que_orphan", [["Yes"]])
            self.assertEqual(sum(path.endswith("/reject") for _, path in sent), 1)
            self.assertTrue(any(path == "/question" for _, path in sent))
            self.assertEqual(bool(pending), not deletion_works)

    def test_non_vcs_native_worktree_patterns_allow_only_same_canonical_paths(self):
        # Public pinned Project.fromDirectory: worktree='/' without VCS. Public
        # read/edit: path.relative(worktree, filepath). Permission: last match.
        def evaluate(policy, permission, pattern):
            found = "ask"
            for name, value in policy.items():
                if not fnmatch.fnmatchcase(permission, name):
                    continue
                for candidate, action in ({"*": value} if isinstance(value, str) else value).items():
                    if fnmatch.fnmatchcase(pattern, candidate):
                        found = action
            return found
        policy = protocol.permission_policy()
        old = {"*": "deny", "read": {"*": "deny", **dict.fromkeys(protocol.FILES, "allow")}}
        for path in protocol.PATHS:
            pattern = posixpath.relpath(path, "/")
            self.assertEqual(evaluate(old, "read", pattern), "deny")  # reproduces reported root cause
            self.assertEqual(evaluate(policy, "read", pattern), "allow")
            self.assertEqual(evaluate(policy, "edit", pattern), "ask")
            self.assertEqual(protocol.permission_path(pattern), path)
            permission = {"permission": "edit", "patterns": [pattern], "metadata": {"filepath": path}}
            worker.Driver.validate_permission(permission, "once")
        for path in ("/project/opencode.json", "/tmp/generated.json", "/project/.opencode/config.json", "/sibling/PROJECT.md"):
            pattern = posixpath.relpath(path, "/")
            self.assertEqual(evaluate(policy, "read", pattern), "deny")
            self.assertEqual(evaluate(policy, "edit", pattern), "deny")
            with self.assertRaises(protocol.Invalid):
                worker.Driver.validate_permission({"permission": "edit", "patterns": [pattern], "metadata": {"filepath": path}}, "once")
        for tool in ("shell", "task", "webfetch", "mcp", "skill", "unknown"):
            self.assertEqual(evaluate(policy, tool, "*"), "deny")

    def driver(self):
        driver = worker.Driver(1234, "synthetic")
        driver.sessions = {"ses_A", "ses_B"}
        return driver

    def test_canonical_policy_and_mandatory_namespace_no_host_transport(self):
        config = worker.generated_config(1234)
        self.assertEqual(config["permission"], protocol.permission_policy())
        self.assertEqual(config["permission"]["*"], "deny")
        self.assertEqual(config["permission"]["edit"]["project/PROJECT.md"], "ask")
        old = prototype.command(Path("/tmp/opencode/synthetic"), "synthetic", 1234)
        new = prototype.command(Path("/tmp/opencode/synthetic"), "imp024-planning", 1234)
        self.assertEqual(old[:old.index("--")], new[:new.index("--")])
        self.assertIn("imp024_worker", new[new.index("-c") + 1])
        with patch.object(prototype, "check_runtime") as check, self.assertRaises(prototype.CapabilityError):
            prototype.run("imp024-planning", transport=object())
        check.assert_not_called()

    def test_prompt_never_accepts_tools_override_and_unknown_dispatch_not_retried(self):
        driver = self.driver()
        with patch.object(driver, "idle", return_value=True), patch.object(driver, "history", return_value=[]), \
                patch.object(worker, "read_surface", return_value={}), \
                patch.object(driver, "_request", side_effect=OSError("synthetic")) as request:
            with self.assertRaises(OSError):
                driver.prompt("ses_A", "synthetic text")
            with self.assertRaises(protocol.Invalid):
                driver.prompt("ses_B", "retry")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(set(request.call_args.args[3]), {"model", "agent", "parts", "tools"})
        self.assertEqual(request.call_args.args[3]["tools"], {"apply_patch": False})
        with self.assertRaises(protocol.Invalid):
            driver.request("POST", "prompt", "ses_A", {"tools": {"shell": True}})

    def test_reply_is_session_bound_pending_and_never_always_or_policy_expansion(self):
        driver = self.driver()
        value = {"id": "per_edit", "sessionID": "ses_A", "permission": "edit", "patterns": ["project/PROJECT.md"],
                 "metadata": {"filepath": "/project/PROJECT.md"}, "always": ["*"]}
        with patch.object(driver, "_request", side_effect=lambda method, operation, *args: [value] if method == "GET" else True) as request:
            self.assertTrue(driver.permission_reply("ses_A", "per_edit", "once"))
            for session, reply in (("ses_B", "once"), ("ses_A", "always")):
                with self.assertRaises(protocol.Invalid):
                    driver.permission_reply(session, "per_edit", reply)
            value["patterns"] = ["*"]
            with self.assertRaises(protocol.Invalid):
                driver.permission_reply("ses_A", "per_edit", "once")
            self.assertTrue(driver.permission_reply("ses_A", "per_edit", "reject"))
        self.assertEqual(sum(entry.args[0] == "POST" for entry in request.call_args_list), 2)

    def test_question_reply_rejects_wrong_count_and_foreign_session(self):
        driver = self.driver()
        prompts = [{"question": "Synthetic?", "header": "Scope", "options": [{"label": "Yes", "description": "Choice"}], "custom": False}]
        value = {"id": "que_one", "sessionID": "ses_A", "questions": prompts}
        with patch.object(driver, "_request", side_effect=lambda method, operation, *args: [value] if method == "GET" else True) as request:
            self.assertTrue(driver.question_reply("ses_A", "que_one", [["Yes"]]))
            for session, answers in (("ses_B", [["Yes"]]), ("ses_A", []), ("ses_A", [["Unknown"]])):
                with self.assertRaises(protocol.Invalid):
                    driver.question_reply(session, "que_one", answers)
        self.assertEqual(sum(entry.args[0] == "POST" for entry in request.call_args_list), 1)

    def test_proposals_keep_base_bytes_and_error_never_imports(self):
        before = dict.fromkeys(protocol.FILES, "synthetic old\n")
        after = dict(before, **{"PROJECT.md": "synthetic proposed\n"})
        proposed = worker.proposals(before, after)
        self.assertEqual(len(proposed), 1)
        self.assertFalse(proposed[0]["approval"])
        self.assertEqual(proposed[0]["origin"], "agent")
        driver = self.driver()
        driver.active_session, driver.captured = "ses_A", before
        with patch.object(driver, "idle", return_value=True), patch.object(driver, "pending", return_value=[]), \
                patch.object(driver, "history", return_value=[{"info": {"role": "assistant", "finish": "stop",
                    "time": {"completed": 1}, "error": {"name": "APIError"}}}]), \
                patch.object(worker, "read_surface") as surface:
            with self.assertRaises(protocol.Invalid):
                driver.finish("ses_A")
        surface.assert_not_called()

    def test_success_import_requires_this_turn_and_preserves_exact_proposal_bytes(self):
        driver = self.driver()
        before = dict.fromkeys(protocol.FILES, "synthetic old\n")
        after = dict(before, **{"PROJECT.md": "synthetic proposed\n"})
        driver.active_session, driver.captured, driver.turn_text = "ses_A", before, "Synthetic turn"
        history = [{"info": {"role": "user", "id": "msg_user"}, "parts": [{"type": "text", "text": "Synthetic turn"}]},
            {"info": {"role": "assistant", "parentID": "msg_user", "finish": "stop", "time": {"completed": 1}}, "parts": []}]
        with patch.object(driver, "idle", return_value=True), patch.object(driver, "pending", return_value=[]), \
                patch.object(driver, "history", return_value=history), patch.object(worker, "read_surface", return_value=after):
            history[-1]["info"]["parentID"] = "msg_old"
            with self.assertRaises(protocol.Invalid):
                driver.finish("ses_A")
            history[-1]["info"]["parentID"] = "msg_user"
            self.assertEqual(driver.finish("ses_A"), worker.proposals(before, after))
        self.assertIsNone(driver.active_session)

    def test_proposal_reader_denies_symlink_fifo_and_oversize_without_real_io(self):
        import stat
        from types import SimpleNamespace
        for mode, links, size in ((stat.S_IFIFO, 1, 0), (stat.S_IFREG, 2, 0), (stat.S_IFREG, 1, protocol.MAX_DOCUMENT + 1)):
            with patch.object(worker.os, "open", side_effect=[10, 11]) as opened, \
                    patch.object(worker.os, "fstat", return_value=SimpleNamespace(st_mode=mode, st_nlink=links, st_size=size)), \
                    patch.object(worker.os, "read") as read, patch.object(worker.os, "close"), \
                    self.assertRaises(protocol.Invalid):
                worker.read_surface()
            read.assert_not_called()
            self.assertTrue(opened.call_args_list[1].args[1] & worker.os.O_NOFOLLOW)
        with patch.object(worker.os, "open", side_effect=[10, OSError("synthetic symlink")]), \
                patch.object(worker.os, "close") as close, self.assertRaises(OSError):
            worker.read_surface()
        close.assert_called_once_with(10)

    def test_history_ceiling_and_abort_other_session_fail_closed(self):
        driver = self.driver()
        driver.active_session = "ses_A"
        with patch.object(driver, "_request", return_value=[{}] * 16) as request:
            with self.assertRaises(protocol.Invalid):
                driver.history("ses_A")
            with self.assertRaises(protocol.Invalid):
                driver.abort("ses_B")
        self.assertEqual(request.call_count, 1)

    def test_routes_only_fixed_and_injected_targets_denied(self):
        self.assertEqual(worker.route("POST", "question-reply", "que_one"), "/question/que_one/reply")
        for method, operation, target in (("POST", "shell", "ses_A"), ("PUT", "config", None),
            ("POST", "permission-reply", "per_one/../../auth"), ("GET", "questions", "ses_A")):
            with self.assertRaises((protocol.Invalid, previous.Failed)):
                worker.route(method, operation, target)

    def test_events_project_only_validated_session_and_safe_error_metadata(self):
        event = {"type": "session.error", "properties": {"sessionID": "ses_A", "error": {"message": "private-detail"}}}
        projected = worker.event_projection(event, {"ses_A"})
        self.assertEqual(projected["properties"]["error"], "inference_failed")
        with self.assertRaises(protocol.Invalid):
            worker.event_projection(event, {"ses_B"})
        pending = {"type": "message.part.updated", "properties": {"part": {"sessionID": "ses_A", "type": "tool",
            "tool": "read", "callID": "call_pending", "state": {"status": "pending", "input": {}, "raw": "partial"}}}}
        self.assertEqual(worker.event_projection(pending, {"ses_A"})["properties"]["status"], "pending")
        pending["properties"]["part"]["tool"] = "shell"
        with self.assertRaises(protocol.Invalid):
            worker.event_projection(pending, {"ses_A"})

    def test_direct_open_cannot_bypass_reply_guard_or_increase_prompt_policy(self):
        driver = self.driver()
        connection = MagicMock()
        with patch.object(previous.http.client, "HTTPConnection", return_value=connection):
            for operation, target, body in (("permission-reply", "per_unknown", {"reply": "always"}),
                ("prompt", "ses_A", {"model": previous.MODEL, "agent": "tech-lead", "tools": {"shell": True}, "parts": []}),
                ("create", None, {"title": "Synthetic", "permission": [{"permission": "*", "action": "allow"}]})):
                with self.assertRaises(protocol.Invalid):
                    driver.open("POST", operation, target, body)
        connection.request.assert_not_called()

    def test_full_native_synthetic_inference_conversation_without_runtime(self):
        synthetic = launcher.SyntheticPlanning("planning")
        data = request()
        for stage in range(4):
            data = validate(data)
            emitted = frames(list(inference.normalized_events(
                synthetic.events(data, threading.Event(), time.monotonic() + 2), data)))
            output = emitted[-1]["response"]["output"]
            if stage == 3:
                self.assertEqual(output[0]["content"][0]["text"], "IMP024_PLANNING_OK")
            else:
                native_call = {key: output[0][key] for key in ("type", "call_id", "name", "arguments")}
                data["input"] += [native_call, {"type": "function_call_output", "call_id": native_call["call_id"],
                    "output": ["Synthetic read", worker.ANSWER, "Edit applied successfully."][stage]}]
        self.assertTrue(synthetic.validated)


if __name__ == "__main__":
    unittest.main()
