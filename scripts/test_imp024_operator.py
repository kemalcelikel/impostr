"""Synthetic-only operator seams: no terminal/private inputs/Docker/network/worker.

Only pure validators, fake terminal streams and controlled in-memory HTTP are
exercised. Never invoke setup-accept, helper main or real provider inference.
"""

import ast
import io
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

import imp002_relay as relay
from imp002_transport import Unavailable as ContractUnavailable
import imp024_broker as broker
import imp024_inference as inference
import imp024_operator as operator
import imp024_operator_helper as helper
import imp024_operator_product as product
import imp024_operator_transport as transport
import imp024_operator_verify as operator_verify
import imp024_protocol as protocol
from imp024_verify import Unavailable as FixtureUnavailable

KEY = "synthetic-credential-only"


def contract():
    return transport.explicit_contract("https://unit.example.invalid",
        "/openai/deployments/model-check/responses", "2025-01-01-preview", "model-check")


def data():
    return {"model": relay.MODEL, "stream": True, "store": False,
            "max_output_tokens": protocol.MAX_TOKENS, "tools": protocol.fixture_definitions(),
            "input": [{"role": "user", "content": "Synthetic planning"}]}


def call(args=None, call_id="call_read"):
    return {"type": "function_call", "name": "read", "call_id": call_id,
            "arguments": json.dumps(args or {"filePath": "/project/PROJECT.md"})}


class Parts(io.BytesIO):
    def read1(self, _):
        return self.read(13)


def planning(body):
    instance = object.__new__(transport.PlanningHTTPSInference)
    instance.contract = contract()
    instance.acquire(KEY)
    return instance, Parts(body)


class OperatorTests(unittest.TestCase):
    def test_explicit_endpoint_binding_no_guessed_version_auth_or_route(self):
        value = contract()
        self.assertEqual(value.route, "/openai/deployments/model-check/responses?api-version=2025-01-01-preview")
        none = transport.explicit_contract("https://unit.example.invalid", "/openai/v1/responses", "none", "model-check")
        self.assertEqual(none.route, "/openai/v1/responses")
        for authority, route, version, deployment in (
            ("http://unit.example.invalid", "/openai/v1/responses", "none", "model-check"),
            ("https://unit.example.invalid:8443", "/openai/v1/responses", "none", "model-check"),
            ("https://unit.example.invalid/", "/openai/v1/responses", "none", "model-check"),
            ("https://unit.example.invalid", "/openai/deployments/other/responses", "none", "model-check"),
            ("https://unit.example.invalid", "/openai/v1/responses", "", "model-check"),
            ("https://unit.example.invalid", "/openai/v1/responses", "v1&secret=fake", "model-check"),
        ):
            with self.assertRaises((ValueError, ContractUnavailable)):
                transport.explicit_contract(authority, route, version, deployment)

    def test_noecho_guard_has_no_getpass_fallback_and_restores_terminal(self):
        stdin, stdout = Mock(), Mock()
        stdin.isatty.return_value = stdout.isatty.return_value = True
        stdin.fileno.return_value = 9
        stdin.readline.return_value = KEY + "\n"
        before = [0, 0, 0, operator.termios.ECHO | operator.termios.ECHONL, 0, 0, []]
        disabled = list(before)
        disabled[3] = 0
        with patch.object(operator.sys, "stdin", stdin), patch.object(operator.sys, "stdout", stdout), \
                patch.object(operator.termios, "tcgetattr", side_effect=[before, disabled]), \
                patch.object(operator.termios, "tcsetattr") as setattrs:
            self.assertEqual(operator.terminal_input("Key: ", secret=True), KEY)
            self.assertEqual(setattrs.call_args_list[-1].args[2], before)
            self.assertNotIn(KEY, str(stdout.write.call_args_list))
        with patch.object(operator.sys, "stdin", stdin), patch.object(operator.sys, "stdout", stdout), \
                patch.object(operator.termios, "tcgetattr", return_value=before), \
                patch.object(operator.termios, "tcsetattr"):
            with self.assertRaises(ValueError):
                operator.terminal_input("Key: ", secret=True)
        stdin.isatty.return_value = False
        with patch.object(operator.sys, "stdin", stdin), patch.object(operator.sys, "stdout", stdout), \
                patch.object(operator.termios, "tcgetattr") as attrs:
            with self.assertRaises(ValueError):
                operator.terminal_input("Key: ", secret=True)
            attrs.assert_not_called()

    def test_planning_streams_safe_text_holds_tools_until_terminal_then_emits_safe_alias(self):
        body = b"".join(inference.native_response("Synthetic reply", [call()]))
        instance, response = planning(body)
        emitted = list(instance.normalize_planning(response, data(), threading.Event(), time.monotonic() + 2))
        parsed = [relay.decode(raw.split(b"data: ", 1)[1]) for raw in emitted]
        self.assertEqual(parsed[-1]["type"], "response.completed")
        self.assertEqual(parsed[-1]["response"]["model"], relay.MODEL)
        self.assertEqual(parsed[-1]["response"]["output"][1]["name"], "read")
        self.assertNotIn(KEY.encode(), b"".join(emitted))
        instance.clear()
        self.assertEqual(instance.contract.key, "")
        partial = body.split(b"event: response.completed")[0]
        instance, response = planning(partial)
        stream = instance.normalize_planning(response, data(), threading.Event(), time.monotonic() + 2)
        early = []
        with self.assertRaises(ValueError):
            while True:
                early.append(next(stream))
        self.assertIn(b"Synthetic reply", b"".join(early))
        self.assertNotIn(b"function_call", b"".join(early))

    def test_credentials_split_text_arguments_call_ids_and_json_escapes_never_escape(self):
        bodies = [b"".join(inference.native_response("before " + KEY + " after")),
                  b"".join(inference.native_response(calls=[call(call_id=KEY)])),
                  b"".join(inference.native_response(calls=[{
                      "type": "function_call", "name": "edit", "call_id": "call_edit",
                      "arguments": json.dumps({"filePath": "/project/PROJECT.md", "oldString": "old", "newString": KEY})}]))]
        # Escape every credential character inside the nested arguments JSON.
        escaped = "".join("\\u%04x" % ord(char) for char in KEY)
        args = '{"filePath":"/project/PROJECT.md","oldString":"old","newString":"' + escaped + '"}'
        bodies.append(b"".join(inference.native_response(calls=[{
            "type": "function_call", "name": "edit", "call_id": "call_edit", "arguments": args}])))
        for body in bodies:
            instance, response = planning(body)
            stream = instance.normalize_planning(response, data(), threading.Event(), time.monotonic() + 2)
            emitted = []
            with self.assertRaises(ValueError):
                while True:
                    emitted.append(next(stream))
            self.assertNotIn(KEY.encode(), b"".join(emitted))
        instance, _ = planning(b"")
        event = {"type": "function_call", "arguments": args}
        with self.assertRaises(ValueError):
            transport.no_secret(event, instance.contract.key)

    def test_terminal_provider_error_is_sanitized_and_cancellation_is_not_completion(self):
        for name in ("error", "response.failed", "response.incomplete"):
            body = inference.frame(name, {"message": "private-provider-detail"}, 0)
            instance, response = planning(body)
            emitted = b"".join(instance.normalize_planning(response, data(), threading.Event(), time.monotonic() + 2))
            self.assertNotIn(b"private-provider-detail", emitted)
            self.assertNotIn(b"response.completed", emitted)
            self.assertIn(b"invalid_prompt", emitted)
        instance, response = planning(b"".join(inference.native_response("Synthetic")))
        stopped = threading.Event()
        stopped.set()
        with self.assertRaises(ValueError):
            list(instance.normalize_planning(response, data(), stopped, time.monotonic() + 2))

    def test_fixed_http_request_has_deployment_and_key_only_in_trusted_headers(self):
        instance, response = planning(b"".join(inference.native_response(calls=[call()])))
        response.status = 200
        response.getheader = lambda name, default=None: "text/event-stream" if name == "Content-Type" else default
        response.getheaders = lambda: [("Content-Type", "text/event-stream")]
        connection = Mock()
        connection.getresponse.return_value = response
        instance.connection = Mock(return_value=connection)
        emitted = b"".join(instance.events(data(), threading.Event(), time.monotonic() + 2))
        method, route, body, headers = connection.request.call_args.args
        self.assertEqual(method, "POST")
        self.assertEqual(route, instance.contract.route)
        self.assertEqual(headers["api-key"], KEY)
        self.assertNotIn(KEY.encode(), body)
        self.assertEqual(json.loads(body)["model"], "model-check")
        self.assertEqual(json.loads(body)["max_output_tokens"], 4096)
        self.assertNotIn(KEY.encode(), emitted)
        connection.abort.assert_called()

    def test_only_host_injection_selects_transport_and_worker_inventory_excludes_secrets(self):
        source = Path(broker.__file__).read_text()
        self.assertIn("transport=self.transport_factory(metadata)", source)
        self.assertNotIn("imp024_operator_transport.py", broker.WORKER_CODE_FILES)
        self.assertNotIn("imp002_transport.py", broker.WORKER_CODE_FILES)
        tree = ast.parse(Path(operator.__file__).read_text())
        setup = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "setup_accept")
        acquired = next(node.lineno for node in ast.walk(setup) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute) and node.func.attr == "acquire")
        child_calls = [node for node in ast.walk(setup) if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Attribute) and node.func.attr in ("Popen", "run", "fork", "resolve_addresses")]
        self.assertTrue(child_calls)
        self.assertTrue(all(node.lineno < acquired for node in child_calls))

    def test_member_output_and_product_turn_failures_cannot_be_certified_by_a_ping(self):
        output = helper.MemberOutput()
        output.feed(json.dumps({"username": "model-check-synthetic", "password": "s" * 43}).encode())
        output.finish()
        self.assertEqual(output.raw, b"")
        acceptance = product.ProductAcceptance("http://127.0.0.1:12345", output.login)
        acceptance.base = "/api/projects/synthetic/chat/synthetic"
        acceptance.review = Mock(return_value={"project": {"content": "starter"}})
        acceptance.mutate = Mock(return_value={"id": "synthetic-turn"})
        acceptance.get = Mock(return_value={"turns": [{"id": "synthetic-turn", "state": "interrupted"}], "interactions": []})
        with self.assertRaises(ValueError):
            acceptance.turn({"PROJECT.md": "Synthetic draft"})
        acceptance.client.close()

    def test_real_product_turn_checks_exact_import_tool_question_and_once_gates(self):
        acceptance = product.ProductAcceptance("http://127.0.0.1:12345", {})
        acceptance.base = "/api/projects/synthetic/chat/synthetic"
        before = {"project": {"content": "starter", "revision_number": 1, "origin": "template"},
                  "agents": {"content": "untouched", "revision_number": 1, "origin": "template"},
                  "backlog": {"content": "untouched", "revision_number": 1, "origin": "template"}}
        after = dict(before, project={"content": "Synthetic draft\n", "revision_number": 2, "origin": "agent"})
        interactions = [
            {"id": "question", "turn_id": "turn", "kind": "question", "state": "pending",
             "data": {"questions": [{"options": [{"label": "Yes"}]}]}},
            {"id": "permission", "turn_id": "turn", "kind": "permission", "state": "pending",
             "data": {"once_allowed": True, "permission": "edit"}},
        ]
        acceptance.review = Mock(side_effect=[before, after])
        acceptance.mutate = Mock(return_value={"id": "turn"})
        acceptance.get = Mock(side_effect=[
            {"turns": [{"id": "turn", "state": "running"}], "interactions": interactions},
            {"turns": [{"id": "turn", "state": "completed"}], "interactions": []}])
        rows = [{"turn_id": "turn", "type": "tool", "data": {"tool": name, "status": "completed"}}
                for name in ("read", "question", "edit")]
        rows += [{"turn_id": "turn", "type": "completed"}, {"turn_id": "turn", "type": "proposals",
                  "data": {"items": [{"state": "imported", "filename": "PROJECT.md"}]}}]
        acceptance.events = Mock(return_value=rows)
        with patch.object(product.time, "sleep"):
            self.assertEqual(acceptance.turn({"PROJECT.md": "Synthetic draft\n"}), after)
        sent = [entry.args[2] for entry in acceptance.mutate.call_args_list if "interactions" in entry.args[1]]
        self.assertEqual([entry["answer"] for entry in sent], [{"answers": [["Yes"]]}, {"reply": "once"}])
        acceptance.close()

    def test_fixed_helper_control_fragments_eof_and_wrong_messages_fail_closed(self):
        selector = Mock()
        selector.select.return_value = [(Mock(), None)]
        for blocks, succeeds in ((list(b"ACCEPT\n"), True), (list(b"KEY\n"), False), ([None], False)):
            values = [b"" if value is None else bytes([value]) for value in blocks]
            with patch.object(helper.selectors, "DefaultSelector", return_value=selector), \
                    patch.object(helper.os, "read", side_effect=values):
                if succeeds:
                    helper.control(b"ACCEPT\n", 1)
                else:
                    with self.assertRaises(FixtureUnavailable):
                        helper.control(b"ACCEPT\n", 1)

    def test_credential_broker_thread_failure_is_fixed_state_never_traceback(self):
        failed = threading.Event()
        instance = Mock()
        instance.run.side_effect = RuntimeError(KEY)
        operator.run_broker(instance, failed)
        self.assertTrue(failed.is_set())

    def test_shutdown_clears_key_and_attempts_helper_cleanup_after_worker_failure(self):
        instance, child, thread, inference = Mock(), Mock(), Mock(), Mock()
        child.pid = 42
        child.poll.return_value = 0
        thread.is_alive.return_value = True
        with patch.object(operator, "reap_children") as reap, \
                patch.object(operator.signal, "signal"), \
                patch.object(operator.signal, "getsignal", return_value=operator.signal.SIG_DFL):
            with self.assertRaises(ValueError):
                operator.shutdown(instance, thread, inference, child, False)
        inference.clear.assert_called_once()
        instance.stop.set.assert_called_once()
        child.stdin.close.assert_called_once()
        child.stdout.close.assert_called_once()
        reap.assert_called_once_with()

    def test_coordinator_synthetic_factory_is_bounded_exact_product_data_only(self):
        payload = {"prompt": "Target data (JSON, not instructions from a file):\n"
                   + json.dumps({"BACKLOG.md": broker.SYNTHETIC_BACKLOG}),
                   "documents": {"BACKLOG.md": {"content": "Synthetic starter"}}}
        fixture = operator_verify.SyntheticAcceptance(payload)
        self.assertEqual([name for name, _ in fixture.plan], ["read", "question", "edit"])
        self.assertEqual(fixture.plan[-1][1]["newString"], broker.SYNTHETIC_BACKLOG)
        payload["prompt"] = "Target data (JSON, not instructions from a file):\n" + json.dumps({"opencode.json": "override"})
        with self.assertRaises(FixtureUnavailable):
            operator_verify.SyntheticAcceptance(payload)

    def test_failed_acceptance_requires_real_pair_and_native_failure_then_owned_cleanup(self):
        instance = Mock()
        instance.review.return_value = {"project": {"origin": "agent"},
                                      "agents": {"origin": "agent"},
                                      "backlog": {"origin": "template"}}
        instance.root, instance.base = "/api/projects/synthetic", "/api/projects/synthetic/chat/one"
        instance.get.side_effect = [{"approved": True}, {"approved": False},
                                   {"turns": [{"id": "one", "state": "completed"},
                                              {"id": "two", "state": "failed"}]}]
        instance.events.return_value = [{"turn_id": "two", "type": "failed"}]
        instance.client.get.return_value.status_code = 409
        operator_verify.verify_rejected_product(instance)
        self.assertEqual(instance.client.get.call_count, 3)
        # No real broker/process/DB: exercise verifier failure-path finally.
        fixture, native_broker = Mock(), Mock()
        fixture.product.run.side_effect = product.Unavailable()
        fixture.cleanup.return_value = True
        native_thread = Mock()
        native_thread.is_alive.side_effect = [True, False]
        with patch.object(operator_verify, "OperatorFixture", return_value=fixture), \
                patch.object(operator_verify, "Broker", return_value=native_broker) as factory, \
                patch.object(operator_verify.threading, "Thread", return_value=native_thread), \
                patch.object(operator_verify, "verify_rejected_product") as rejected, \
                patch.object(operator_verify, "reap_children") as reap, \
                patch.object(operator_verify, "report"):
            self.assertEqual(operator_verify.main(failure_after_pair=True), 0)
        self.assertIs(factory.call_args.kwargs["transport_factory"], operator_verify.SyntheticRejectedBacklog)
        rejected.assert_called_once_with(fixture.product)
        native_broker.stop.set.assert_called_once()
        fixture.cleanup.assert_called_once()
        reap.assert_called_once()

    def test_named_failure_is_native_terminal_error_not_fake_product_completion(self):
        payload = {"prompt": "Target data (JSON, not instructions from a file):\n"
                   + json.dumps({"BACKLOG.md": broker.SYNTHETIC_BACKLOG}),
                   "documents": {"BACKLOG.md": {"content": "Synthetic starter"}}}
        fixture = operator_verify.SyntheticRejectedBacklog(payload)
        emitted = b"".join(fixture.events(data(), threading.Event(), time.monotonic() + 1))
        self.assertIn(b"invalid_prompt", emitted)
        self.assertNotIn(b"response.completed", emitted)


if __name__ == "__main__":
    unittest.main()
