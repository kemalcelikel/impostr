"""Pure phase-two contract checks. No broker, socket, worker or private input."""

import copy
import ast
import importlib.util
import io
import json
import os
import stat
import queue
import struct
import sys
import threading
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from app import chat_protocol as protocol
import imp024_broker as broker
import imp002_relay as relay
import imp024_worker as planning_worker
import imp023_worker as previous
import imp024_inference as inference
import imp024_protocol as planning_protocol


def payload():
    return {"prompt": "Plan the synthetic project", "history": [], "documents": {
        name: {"revision_id": str(uuid.uuid4()), "content": "# Synthetic\n",
               "sha256": protocol.digest("# Synthetic\n")} for name in protocol.FILES}}


def product_worker():
    path = Path(__file__).with_name("imp024_product_worker.py")
    spec = importlib.util.spec_from_file_location("product_worker_test", path)
    worker = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"imp024_channel": protocol}):
        spec.loader.exec_module(worker)
    return worker


class BytesPeer:
    def __init__(self, value):
        self.value = value

    def recv(self, size):
        chunk, self.value = self.value[:min(size, 7)], self.value[min(size, 7):]
        return chunk


class ContractTests(unittest.TestCase):
    def test_product_stream_wait_is_bound_to_original_deadline_not_idle_gap(self):
        from unittest.mock import Mock

        worker = product_worker()
        driver = worker.ProductDriver(1, "synthetic")
        driver.sessions.add("ses_synthetic")
        driver.deadline = 145
        connection, response = Mock(), Mock()
        response.status = 200
        response.getheader.return_value = "text/event-stream"
        driver.open = Mock(return_value=(connection, response))
        connected = b'data: {"type":"server.connected"}\n\n'
        # No wall-clock wait/server/worker: the stream emits a permission only
        # after simulated silence longer than the crashed API's 20-second lease.
        permission = {"type": "permission.asked", "properties": {
            "sessionID": "ses_synthetic", "id": "per_synthetic", "permission": "edit",
            "patterns": ["project/PROJECT.md"]}}
        now = [100]
        lines = iter(io.BytesIO(connected + b"data: " + json.dumps(permission).encode() + b"\n\n"))
        def readline(_):
            now[0] = 121
            return next(lines, b"")
        response.readline.side_effect = readline
        with patch.object(worker.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(previous.threading.Thread, "start"):
            reader = worker.ProductEvents(driver)
            connection._imp023_socket.settimeout.assert_called_once_with(45)
            reader.read()
            projected = reader.queue.get_nowait()
            self.assertEqual(projected["type"], "permission.asked")
            self.assertEqual(reader.queue.get_nowait(), {
                "type": "driver.stream.failed", "reason": "native_stream_invalid"})
            # Events cannot renew the main loop's immutable deadline.
            self.assertEqual(driver.deadline, 145)
            self.assertEqual(reader.stream_timeout, 24)
            response.readline.side_effect = TimeoutError("private detail")
            reader.read()
            self.assertEqual(reader.queue.get_nowait(), {
                "type": "driver.stream.failed", "reason": "native_stream_timeout"})
            now[0] = 146
            with self.assertRaises(ValueError):
                _ = reader.stream_timeout
        self.assertEqual(previous.Events.stream_timeout, 8)  # Delivered phase-one default unchanged.

    def test_product_stream_failure_reasons_are_fixed_and_bounded(self):
        worker = product_worker()
        for error, expected in ((TimeoutError("private detail"), "native_stream_timeout"),
                                (ValueError("private detail"), "native_stream_invalid")):
            value = worker.ProductEvents.stream_failure(error)
            self.assertEqual(value, {"type": "driver.stream.failed", "reason": expected})
            protocol.event({"type": "failed", "data": {"reason": value["reason"]}})
        for data in ({"reason": "private detail"}, {"reason": "worker_error", "detail": "secret"}):
            with self.assertRaises(ValueError):
                protocol.event({"type": "failed", "data": data})

    def test_persistent_mount_directory_rejects_unsafe_or_stale_inputs(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        directory = Mock()
        safe = dict(st_mode=stat.S_IFDIR | 0o711, st_uid=1000, st_gid=1000)
        directory.lstat.return_value = SimpleNamespace(**safe)
        directory.iterdir.return_value = iter(())
        broker.validate_persistent_directory(directory)
        for changes in ({"st_mode": stat.S_IFLNK | 0o711}, {"st_mode": stat.S_IFDIR | 0o777},
                        {"st_uid": 10001}, {"st_gid": 10001}):
            directory.lstat.return_value = SimpleNamespace(**dict(safe, **changes))
            directory.iterdir.return_value = iter(())
            with self.assertRaises(ValueError):
                broker.validate_persistent_directory(directory)
        directory.lstat.return_value = SimpleNamespace(**safe)
        directory.iterdir.return_value = iter(("channel.sock",))
        with self.assertRaises(ValueError):
            broker.validate_persistent_directory(directory)

    def test_clean_restart_retains_only_explicit_fixture_mount_directory(self):
        from unittest.mock import Mock

        for persistent in (False, True):
            instance = broker.Broker.__new__(broker.Broker)
            instance.stop = threading.Event()
            instance.stop.set()
            instance.turns = {}
            instance.listener = Mock()
            instance.path = Mock()
            instance.directory = Mock()
            instance.persistent_directory = persistent
            instance.run()
            instance.listener.close.assert_called_once()
            instance.path.unlink.assert_called_once()
            self.assertEqual(instance.directory.rmdir.call_count, 0 if persistent else 1)

    def test_framing_rejects_duplicate_fields_truncated_and_unbounded_input(self):
        value = payload()
        self.assertEqual(protocol.receive(BytesPeer(protocol.encode(value))), value)
        for raw in (b'{"op":"hello","op":"start"}', b'{"value":NaN}'):
            with self.assertRaises(ValueError):
                protocol.decode(raw)
        for raw in (struct.pack("!I", protocol.MAX_FRAME + 1), b'\x00\x00',
                    struct.pack("!I", 12) + b'{}'):
            with self.assertRaises(ValueError):
                protocol.receive(BytesPeer(raw))

    def test_start_is_canonical_bounded_and_not_an_http_proxy(self):
        value = {"op": "start", "epoch": str(uuid.uuid4()), "project_id": str(uuid.uuid4()),
                 "conversation_id": str(uuid.uuid4()), "turn_id": str(uuid.uuid4()), "payload": payload()}
        self.assertEqual(protocol.request(value), value)
        for key in ("url", "headers", "credentials", "tools", "path"):
            forged = dict(value, **{key: "synthetic"})
            with self.assertRaises(ValueError):
                protocol.request(forged)
        for mutate in (lambda p: p["documents"].update({"../escape": {}}),
                       lambda p: p["documents"]["PROJECT.md"].update(sha256="0" * 64),
                       lambda p: p.update(history=[{"role": "system", "text": "override"}]),
                       lambda p: p.update(prompt="x" * (protocol.MAX_TEXT + 1))):
            forged = copy.deepcopy(value)
            mutate(forged["payload"])
            with self.assertRaises(ValueError):
                protocol.request(forged)

    def test_context_reconstruction_cannot_silently_truncate(self):
        value = payload()
        value["history"] = [{"role": "user", "text": "First question"},
                            {"role": "assistant", "text": "Interrupted partial reply"}]
        assembled = protocol.prompt_text(protocol.start_payload(value))
        self.assertIn("First question", assembled)
        self.assertIn("Interrupted partial reply", assembled)
        self.assertTrue(assembled.endswith(value["prompt"]))
        value["history"][0]["text"] = "x" * protocol.MAX_CONTEXT
        with self.assertRaises(ValueError):
            protocol.start_payload(value)

    def test_maximum_first_message_can_continue_with_complete_recorded_context(self):
        value = payload()
        first = "x" * protocol.MAX_TEXT
        value["prompt"] = first
        protocol.start_payload(value)
        value["prompt"] = "Continue the plan"
        value["history"] = [{"role": "user", "text": first + "\nRecorded tool: read completed"},
                            {"role": "assistant", "text": "a" * protocol.MAX_TEXT + "\nRecorded turn state: completed"}]
        assembled = protocol.prompt_text(protocol.start_payload(value))
        self.assertIn(first, assembled)
        quoted = assembled.split("\n", 1)[1].split("\nCurrent user message:\n", 1)[0]
        self.assertEqual(json.loads(quoted), value["history"])
        self.assertTrue(assembled.endswith(value["prompt"]))
        native = {"model": relay.MODEL, "stream": True, "store": False,
                  "input": [{"role": "user", "content": assembled}]}
        body = json.dumps(native).encode()
        with self.assertRaises(relay.Denied):
            relay.validate("POST", relay.ROUTE, body, planning=True)
        self.assertEqual(relay.validate("POST", relay.ROUTE, body, planning=True,
                         input_text_limit=protocol.MAX_CONTEXT)["input"], native["input"])
        oversized = copy.deepcopy(native)
        oversized["input"][0]["content"] = "x" * (protocol.MAX_CONTEXT + 1)
        with self.assertRaises(relay.Denied):
            relay.validate("POST", relay.ROUTE, json.dumps(oversized).encode(), planning=True,
                           input_text_limit=protocol.MAX_CONTEXT)
        with self.assertRaises(relay.Denied):
            relay.validate("POST", relay.ROUTE, body, planning=False,
                           input_text_limit=protocol.MAX_CONTEXT)
        value["prompt"] = "Continue"
        maximum_escaped = '"' * (protocol.MAX_TEXT // 2)
        self.assertEqual(protocol.escaped_size(protocol.message_text(maximum_escaped)), protocol.MAX_TEXT)
        value["history"] = [{"role": "user", "text": maximum_escaped},
                            {"role": "assistant", "text": maximum_escaped}]
        protocol.start_payload(value)
        with self.assertRaises(ValueError):
            protocol.message_text(maximum_escaped + '"')

    def test_twelve_prior_turns_preserved_and_thirteenth_rejected(self):
        value = payload()
        value["history"] = [{"role": role, "text": f"{role} turn {index}"}
                            for index in range(protocol.MAX_PRIOR_TURNS)
                            for role in ("user", "assistant")]
        assembled = protocol.prompt_text(protocol.start_payload(value))
        for item in value["history"]:
            self.assertIn(item["text"], assembled)
        value["history"] += [{"role": "user", "text": "thirteenth"},
                             {"role": "assistant", "text": "must not disappear"}]
        with self.assertRaises(ValueError):
            protocol.start_payload(value)

    def test_escaped_context_and_full_dispatch_frame_checked_before_acceptance(self):
        value = payload()
        # Raw UTF-8 fits the aggregate cap, but native JSON quoting does not.
        value["history"] = [{"role": "user", "text": "\n" * (protocol.MAX_CONTEXT // 3)}]
        with self.assertRaises(ValueError):
            protocol.start_payload(value)
        # The payload alone fits a smaller synthetic frame, the dispatch header
        # does not: acceptance must validate the same envelope the broker sends.
        value = payload()
        payload_bytes = len(protocol.encode(value)) - 4
        with patch.object(protocol, "MAX_FRAME", payload_bytes):
            protocol.encode(value)
            with self.assertRaises(ValueError):
                protocol.start_payload(value)

    def test_confined_code_inventory_contains_transitive_runtime_imports(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            broker.copy_worker_code(root)
            modules = {path.stem for path in root.glob("*.py")}
            self.assertIn("imp024_inference", modules)
            self.assertNotIn("imp002_transport", modules)
            for path in root.glob("*.py"):
                for node in ast.walk(ast.parse(path.read_bytes())):
                    if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("imp0"):
                        self.assertIn(node.module, modules)
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith("imp0"):
                                self.assertIn(alias.name, modules)

    def test_product_surface_preserves_crlf_and_rejects_byte_drift(self):
        from imp024_worker import read_surface
        worker = product_worker()
        value = payload()
        content = "# Synthetic café\r\nMixed endings\nFinal\r\n"
        for document in value["documents"].values():
            document.update(content=content, sha256=protocol.digest(content))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in protocol.FILES:
                (root / name).write_bytes(content.encode("utf-8"))
            actual_open = os.open
            def open_project(path, *args, **kwargs):
                return actual_open(str(root) if path == "/project" else path, *args, **kwargs)
            with patch("os.open", side_effect=open_project):
                self.assertEqual(read_surface()["PROJECT.md"], content)
                worker.validate_surface(value)
                (root / "PROJECT.md").write_bytes(content.replace("\r\n", "\n").encode("utf-8"))
                with self.assertRaises(ValueError):
                    worker.validate_surface(value)
        self.assertEqual(worker.ProductDriver.max_prompt, protocol.MAX_CONTEXT)
        self.assertEqual(worker.Driver.max_prompt, protocol.MAX_TEXT)

        native_driver = worker.ProductDriver(1, "synthetic")
        native_driver.sessions.add("ses_synthetic")
        with patch.object(native_driver, "idle", return_value=True), \
                patch.object(native_driver, "history", return_value=[]), \
                patch.object(planning_worker, "read_surface", return_value={name: content for name in protocol.FILES}), \
                patch.object(native_driver, "_request", return_value=None) as send:
            native_driver.prompt("ses_synthetic", "x" * (protocol.MAX_TEXT + 1))
            self.assertTrue(send.called)

    def test_large_native_prompt_echo_is_bounded_before_ignoring_text_update(self):
        worker = product_worker()
        value = payload()
        value["history"] = [{"role": "user", "text": "x" * protocol.MAX_TEXT},
                            {"role": "assistant", "text": "a" * protocol.MAX_TEXT}]
        prompt = protocol.prompt_text(protocol.start_payload(value))
        update = {"type": "message.part.updated", "properties": {"part": {
            "type": "text", "sessionID": "ses_synthetic", "text": prompt}}}
        raw = b"data: " + json.dumps(update).encode() + b"\n\n"
        self.assertLess(len(raw), protocol.MAX_FRAME)
        # Measured root cause: native echoed prompt fails before projection.
        with self.assertRaises(previous.Failed):
            previous.parse_event(io.BytesIO(raw))
        decoded, size = worker.ProductEvents.parse_event(io.BytesIO(raw))
        self.assertEqual(decoded, update)
        self.assertEqual(size, len(raw))
        self.assertIsNone(planning_worker.event_projection(decoded, {"ses_synthetic"}))
        # Exercise the real planning reader method on the product subclass, not
        # only its helper: it must consume the large echo and continue to status.
        status = {"type": "session.status", "properties": {
            "sessionID": "ses_synthetic", "status": {"type": "idle"}}}
        reader = worker.ProductEvents.__new__(worker.ProductEvents)
        reader.driver = worker.ProductDriver(1, "synthetic")
        reader.driver.sessions.add("ses_synthetic")
        reader.response = io.BytesIO(raw + b"data: " + json.dumps(status).encode() + b"\n\n")
        reader.queue = queue.Queue(maxsize=256)
        reader.stopped = threading.Event()
        reader.bytes = 0
        reader.read()
        self.assertEqual(reader.queue.get_nowait(), status)
        self.assertEqual(reader.queue.get_nowait(), {
            "type": "driver.stream.failed", "reason": "native_stream_invalid"})  # fixture EOF
        self.assertLess(reader.bytes, protocol.MAX_FRAME)
        # The product-specific parser still rejects oversized framing and EOF;
        # it does not enlarge projected assistant delta/tool argument bounds.
        with self.assertRaises(previous.Failed):
            worker.ProductEvents.parse_event(io.BytesIO(b"data: " + b"x" * protocol.MAX_FRAME))
        delta = {"type": "message.part.delta", "properties": {
            "sessionID": "ses_synthetic", "field": "text", "delta": "x" * (protocol.MAX_TEXT + 1),
            "messageID": "msg_synthetic", "partID": "part_synthetic"}}
        with self.assertRaises(planning_protocol.Invalid):
            planning_worker.event_projection(delta, {"ses_synthetic"})

    def test_crlf_fixture_inference_and_terminal_proposal_preserve_exact_bytes(self):
        value = payload()
        content = "# Synthetic project\r\nExact CRLF draft\r\n"
        for document in value["documents"].values():
            document.update(content=content, sha256=protocol.digest(content))
        fixture = broker.SyntheticProduct(value)
        data = {"model": relay.MODEL, "stream": True, "store": False,
                "tools": planning_protocol.fixture_definitions(),
                "max_output_tokens": planning_protocol.MAX_TOKENS,
                "input": [{"role": "user", "content": "Synthetic short prompt"}]}
        edited = None
        for expected in ("read", "question", "edit"):
            validated = relay.validate("POST", relay.ROUTE, json.dumps(data).encode(), planning=True)
            blocks = inference.normalized_events(fixture.events(validated, None, 0), validated)
            terminal = [json.loads(raw.split(b"data: ", 1)[1]) for raw in blocks][-1]
            call = terminal["response"]["output"][0]
            self.assertEqual(call["name"], expected)
            args = json.loads(call["arguments"])
            if expected == "edit":
                self.assertEqual(args["oldString"].encode(), content.encode())
                edited = args["newString"]
            data["input"].extend([{key: call[key] for key in ("type", "name", "call_id", "arguments")},
                                  {"type": "function_call_output", "call_id": call["call_id"], "output": "Synthetic result"}])
        driver = product_worker().ProductDriver(1, "synthetic")
        driver.sessions.add("ses_synthetic")
        driver.active_session = "ses_synthetic"
        driver.turn_text = "Synthetic short prompt"
        driver.captured = {name: content for name in protocol.FILES}
        history = [{"info": {"id": "msg_user", "role": "user"}, "parts": [
            {"type": "text", "text": driver.turn_text}]},
            {"info": {"role": "assistant", "parentID": "msg_user", "finish": "stop",
                      "time": {"completed": 1}}, "parts": [{"type": "tool", "state": {"status": "completed"}}]}]
        with patch.object(driver, "idle", return_value=True), patch.object(driver, "pending", return_value=[]), \
                patch.object(driver, "history", return_value=history), \
                patch.object(planning_worker, "read_surface", return_value=dict(driver.captured, **{"PROJECT.md": edited})):
            proposals = driver.finish("ses_synthetic")
        self.assertEqual(proposals, [{"filename": "PROJECT.md", "base_sha256": protocol.digest(content),
                                     "content": edited, "origin": "agent", "approval": False}])

    def test_question_and_permission_replies_cannot_enlarge_policy(self):
        question = {"id": "que_synthetic", "questions": [{"header": "Scope", "question": "Choose?",
                    "options": [{"label": "Local", "description": "Synthetic"}], "custom": False}]}
        protocol.event({"type": "question", "data": question})
        self.assertEqual(protocol.answer("question", question, {"answers": [["Local"]]}),
                         {"answers": [["Local"]]})
        for forged in ({"answers": [["Other"]]}, {"answers": []}, {"answers": [["Local", "Local"]]}):
            with self.assertRaises(ValueError):
                protocol.answer("question", question, forged)
        permission = {"id": "per_synthetic", "permission": "edit", "once_allowed": True}
        protocol.answer("permission", permission, {"reply": "once"})
        for forged in ({"reply": "always"}, {"reply": "once", "patterns": ["*"]}):
            with self.assertRaises(ValueError):
                protocol.answer("permission", permission, forged)
        with self.assertRaises(ValueError):
            protocol.answer("permission", dict(permission, once_allowed=False), {"reply": "once"})

    def test_terminal_proposals_are_not_approvals_or_arbitrary_files(self):
        proposal = {"filename": "PROJECT.md", "base_sha256": "0" * 64,
                    "content": "Synthetic proposed draft", "origin": "agent", "approval": False}
        protocol.event({"type": "completed", "data": {"proposals": [proposal]}})
        for replacement in ({"filename": "opencode.json"}, {"approval": True}, {"origin": "human"}):
            with self.assertRaises(ValueError):
                protocol.event({"type": "completed", "data": {"proposals": [dict(proposal, **replacement)]}})
        with self.assertRaises(ValueError):
            protocol.event({"type": "session.error", "data": {"raw": "provider details"}})


if __name__ == "__main__":
    unittest.main()
