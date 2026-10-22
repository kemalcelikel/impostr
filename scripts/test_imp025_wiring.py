"""B3 pure wiring/teardown seams. All sockets, subprocesses and native startup mocked."""

import copy
import io
import json
import struct
import threading
import time
import unittest
import uuid
from unittest.mock import MagicMock, Mock, mock_open, patch
from email.message import Message
from types import SimpleNamespace

from test_imp025_inline import context, echo, responses, protocol
from test_imp024_channel import BytesPeer, product_worker, payload
from test_imp025_authorization import book
from app import chat_broker as api_broker
import imp024_broker as broker
import imp002_relay as relay
import imp023_worker as previous
import imp002_worker as shim_module


def command(key, epoch, operation, **extra):
    return dict(op=operation, epoch=epoch,
                **dict(zip(("project_id", "conversation_id", "turn_id"), key)), **extra)


class WiringTests(unittest.TestCase):
    def test_only_native_start_and_worker_input_get_binary_framing(self):
        value = context(b"%PDF-" + b"x" * 400_000, history=True)
        key = tuple(str(uuid.uuid4()) for _ in range(3))
        start = command(key, str(uuid.uuid4()), "start", payload=value, deadline=time.time() + 55)
        frame = protocol.encode_request(start)
        self.assertGreater(len(frame), protocol.MAX_FRAME)
        sizes = []
        self.assertEqual(protocol.receive_request(BytesPeer(frame), on_size=sizes.append), start)
        self.assertEqual(sizes, [len(frame) - 4])
        self.assertEqual(protocol.receive_dispatch(BytesPeer(protocol.encode_native_context(value))), value)
        self.assertEqual(protocol.receive_dispatch(BytesPeer(protocol.encode(payload())))["history"], [])
        with self.assertRaises(ValueError):
            protocol.encode_request(dict(start, payload=value["context"]))  # No available-history dropping.
        for op in ("poll", "reply", "purge"):
            with self.assertRaises(ValueError):
                protocol.request(dict(start, op=op))
        with self.assertRaises(ValueError):
            protocol.receive_request(BytesPeer(struct.pack("!I", len(frame) - 4 + protocol.MAX_FRAME)
                                              + frame[4:] + b" " * protocol.MAX_FRAME))
        with self.assertRaises(ValueError):
            protocol.receive(BytesPeer(frame))  # Ordinary responses still have a 512 KiB cap.

    def test_unavailable_native_and_legacy_history_is_retained_on_text_route(self):
        from test_imp018_references import entry as legacy_entry

        value = context()["context"]
        selected = value.pop("references")[0]
        selected["availability"] = "unavailable"
        value["history"] = [dict(role="user", text="Old quotes", references=[selected,
            dict(reference=legacy_entry()["reference"], availability="unavailable")])]
        protocol.broker_start_payload(value)
        rendered = protocol.resolved_prompt_text(value)
        self.assertIn('"unavailable"', rendered)
        self.assertIn('"native-original-v1"', rendered)
        self.assertIn('"text_sha256"', rendered)  # Legacy identity is not relabeled.
        self.assertNotIn("base64", rendered)
        value["history"][0]["references"][0]["availability"] = "available"
        with self.assertRaises(ValueError):
            protocol.broker_start_payload(value)

    def test_unix_client_uses_native_start_bound_and_small_response_without_real_socket(self):
        value = context(b"%PDF-" + b"x" * 400_000)
        key = tuple(str(uuid.uuid4()) for _ in range(3))
        start = command(key, str(uuid.uuid4()), "start", payload=value, deadline=time.time() + 55)
        peer = MagicMock()
        peer.__enter__.return_value = peer
        peer.getsockopt.return_value = struct.pack("3i", 1, 1000, 1000)
        received = BytesPeer(protocol.encode(dict(ok=True)))
        peer.recv.side_effect = received.recv
        with patch.object(api_broker.os, "geteuid", return_value=10001), \
                patch.object(api_broker.os, "lstat", return_value=Mock(st_mode=0o140600, st_uid=1000)), \
                patch.object(api_broker.socket, "socket", return_value=peer), \
                patch.object(api_broker.threading, "Timer") as timer:
            self.assertEqual(api_broker.UnixBroker().call(start), {"ok": True})
            peer.settimeout.assert_called_with(protocol.PDF_TRANSFER_SECONDS)
            timer.assert_called_once()
            self.assertEqual(peer.sendall.call_args.args[0], protocol.encode_request(start))

    def test_shim_forwards_only_valid_selected_native_body_on_fixed_unix_route(self):
        value = context(b"%PDF-" + b"x" * 400_000)
        manifest = [item["manifest"] for item in value["files"]]
        for forged in (False, True):
            data = responses(value)
            if forged:
                data["input"][0]["content"][1]["filename"] = "foreign.pdf"
            raw = json.dumps(data).encode()
            handler = object.__new__(shim_module.Shim)
            handler.server = SimpleNamespace(pdf_manifest=manifest, max_request=protocol.MAX_PDF_FRAME,
                                             max_response=protocol.MAX_FRAME)
            handler.path, handler.connection, handler.rfile = relay.ROUTE, Mock(), io.BytesIO(raw)
            handler.headers = Message()
            handler.headers["Content-Length"] = str(len(raw))
            upstream = MagicMock()
            upstream.__enter__.return_value = upstream
            response = Mock(status=503)  # Fixed relay rejection, no receiver/HTTP/native execution.
            with patch.object(shim_module.socket, "socket", return_value=upstream), \
                    patch.object(shim_module.http.client, "HTTPResponse", return_value=response), \
                    patch.object(shim_module.threading, "Timer"), \
                    patch.object(shim_module.threading.Thread, "start"), \
                    patch.object(shim_module.threading.Thread, "join"):
                handler.do_POST()
            if forged:
                upstream.connect.assert_not_called()
                upstream.sendall.assert_not_called()
            else:
                upstream.connect.assert_called_once_with("/relay/inference.sock")
                forwarded = upstream.sendall.call_args.args[0]
                headers, body = forwarded.split(b"\r\n\r\n", 1)
                self.assertEqual(body, raw)
                self.assertNotIn(b"Authorization", headers)
                self.assertNotIn(b"api-key", headers)
            self.assertTrue(handler.close_connection)

    def test_host_relay_requires_ledger_native_mode_and_refuses_ungated_output(self):
        value = context()
        ledger = book(value)
        transport = Mock()
        with patch.object(relay.socket, "socket"):
            host = relay.SyntheticRelay(Mock(), planning=True,
                                       input_text_limit=protocol.MAX_CONTEXT, receipts=ledger, transport=transport)
            self.assertEqual(host.pdf_manifest, [item["manifest"] for item in value["files"]])
            self.assertEqual(host.max_request, protocol.MAX_PDF_FRAME)
            self.assertEqual(host.max_response, protocol.MAX_FRAME)
        transport.events.return_value = iter(previous.response_events("Synthetic ungated answer"))
        connection = MagicMock()
        call = ledger.begin(None)
        with patch.object(relay.threading.Thread, "start"), patch.object(relay.threading.Thread, "join"):
            host.stream(connection, responses(value), threading.Event(), time.monotonic() + 1, submission=call)
        emitted = b"".join(item.args[0] for item in connection.sendall.call_args_list)
        self.assertTrue(emitted.startswith(b"HTTP/1.1 503"))
        self.assertNotIn(b"Synthetic ungated answer", emitted)
        call.finish()
        self.assertEqual(call.row["status"], "failed-before-send")

    def test_product_driver_posts_exact_parts_once_and_projects_native_history(self):
        worker = product_worker()
        value = context(history=True)
        driver = worker.ProductDriver(1, "synthetic", native_context=value)
        driver.sessions.add("ses_synthetic")
        driver.idle = Mock(return_value=True)
        prior = MagicMock(status=200)
        prior.getheader.return_value = "application/json"
        prior.read.return_value = b"[]"
        ack = MagicMock(status=204)
        ack.read.return_value = b""
        connection = Mock()
        # Calls still traverse Driver._open validation; only HTTP I/O is mocked.
        with patch.object(previous.Driver, "open", side_effect=[(connection, prior), (connection, ack)]) as send, \
                patch.object(worker, "read_surface", return_value={name: "# Draft\n" for name in protocol.FILES}):
            driver.prompt_native("ses_synthetic")
            self.assertEqual(send.call_args.args[3], worker.native_prompt_body(value))
            self.assertIsNone(driver.native_context)
            with self.assertRaises(ValueError):
                driver.prompt_native("ses_synthetic")
            self.assertEqual(send.call_count, 2)  # Empty history + ONE prompt, not a retry.
        history = [dict(info=dict(sessionID="ses_synthetic", role="user", id="msg_synthetic"),
                        parts=[dict(type="text", text=driver.turn_text), echo(value, 0), echo(value, 1)])]
        prior.read.return_value = json.dumps(history).encode()
        with patch.object(previous.Driver, "open", return_value=(connection, prior)):
            projected = driver.history("ses_synthetic")
            self.assertEqual(len(projected[0]["parts"]), 1)
            self.assertNotIn("base64", json.dumps(projected))
            history[0]["parts"].pop()
            prior.read.return_value = json.dumps(history).encode()
            self.assertEqual(driver.history("ses_synthetic"), [])  # Still materializing, not complete.
            prior.read.return_value = b"[]"  # Genuine async pre-message gap is not completion.
            self.assertEqual(driver.history("ses_synthetic"), [])
        self.assertEqual(driver.request_limit("prompt"), protocol.MAX_PDF_FRAME)
        self.assertEqual(driver.request_limit("question-reply"), protocol.MAX_FRAME)
        self.assertEqual(driver.response_limit("status"), protocol.MAX_FRAME)
        driver.release()
        self.assertIsNone(driver.native_manifest)

    def test_native_history_waits_for_text_and_each_ordered_file_without_resubmission(self):
        worker = product_worker()
        value = context(history=True)
        driver = worker.ProductDriver(1, "synthetic", native_context=value)
        driver.sessions.add("ses_synthetic")
        driver.idle = Mock(return_value=True)
        response = MagicMock(status=200)
        response.getheader.return_value = "application/json"
        connection = Mock()
        user = dict(info=dict(sessionID="ses_synthetic", role="user", id="msg_synthetic"),
                    parts=[dict(type="text", text=worker.native_prompt_text(value["context"]))])
        assistant = dict(info=dict(sessionID="ses_synthetic", role="assistant",
                                  time=dict(completed=1)), parts=[dict(type="text", text="Answer")])
        snapshots = [[], [user], [dict(user, parts=user["parts"] + [echo(value, 0)]), assistant],
                     [dict(user, parts=user["parts"] + [echo(value, 0), echo(value, 1)]), assistant]]
        response.read.side_effect = [b"[]"] + [json.dumps(item).encode() for item in snapshots]
        ack = MagicMock(status=204)
        ack.read.return_value = b""
        with patch.object(previous.Driver, "open", side_effect=[(connection, response), (connection, ack)]
                          + [(connection, response)] * len(snapshots)) as send, \
                patch.object(worker, "read_surface", return_value={name: "# Draft\n" for name in protocol.FILES}):
            driver.prompt_native("ses_synthetic")
            deadline = driver.deadline
            for _ in snapshots[:-1]:
                self.assertTrue(driver.idle("ses_synthetic"))
                self.assertEqual(driver.history("ses_synthetic"), [])  # Even a completed assistant is no proof.
            projected = driver.history("ses_synthetic")
            self.assertEqual(projected, [user, assistant])
            self.assertNotIn("base64", json.dumps(projected))
            self.assertEqual(driver.deadline, deadline)
            self.assertEqual(driver.prompts, 1)
            self.assertEqual(sum(call.args[1] == "prompt" for call in send.call_args_list), 1)
            self.assertEqual(response.close.call_count, 1 + len(snapshots))

    def test_incomplete_native_history_rejects_wrong_bytes_foreign_order_and_session_immediately(self):
        worker = product_worker()
        value = context(history=True)
        driver = worker.ProductDriver(1, "synthetic", native_context=value)
        driver.sessions.add("ses_synthetic")
        driver.native_prompted = True
        history = [dict(info=dict(sessionID="ses_synthetic", role="user"), parts=[echo(value, 0)])]
        for mutate in (lambda h: h[0]["parts"][0].update(url=context(b"%PDF-synthetic-originaL")["files"][0]["url"]),
                       lambda h: h[0]["parts"][0].update(filename="foreign.pdf"),
                       lambda h: h[0]["parts"].__setitem__(0, echo(value, 1)),
                       lambda h: h[0]["parts"][0].update(sessionID="ses_foreign")):
            with self.subTest(mutate=mutate):
                forged = copy.deepcopy(history)
                mutate(forged)
                response = MagicMock(status=200)
                response.getheader.return_value = "application/json"
                response.read.return_value = json.dumps(forged).encode()
                connection = Mock()
                with patch.object(previous.Driver, "open", return_value=(connection, response)) as send:
                    with self.assertRaises(ValueError):
                        driver.history("ses_synthetic")
                    send.assert_called_once()
                    response.close.assert_called_once()
                    connection.close.assert_called_once()

    def test_incomplete_native_history_cannot_renew_deadline_or_read_after_timeout(self):
        worker = product_worker()
        value = context(history=True)
        driver = worker.ProductDriver(1, "synthetic", native_context=value)
        driver.sessions.add("ses_synthetic")
        driver.native_prompted = True
        driver.deadline = 10
        response = MagicMock(status=200)
        response.getheader.return_value = "application/json"
        response.read.return_value = json.dumps([dict(info=dict(sessionID="ses_synthetic", role="user"),
                                                     parts=[echo(value, 0)])]).encode()
        with patch.object(previous.Driver, "open", return_value=(Mock(), response)) as send, \
                patch.object(worker.time, "monotonic", return_value=9):
            self.assertEqual(driver.history("ses_synthetic"), [])
            self.assertEqual(driver.request_timeout("history"), 1)
            with patch.object(worker.time, "monotonic", return_value=10):
                with self.assertRaises(ValueError):
                    driver.history("ses_synthetic")
            send.assert_called_once()
        self.assertEqual(driver.deadline, 10)

    def test_idle_partial_native_prompt_expires_in_existing_main_loop_without_completion_or_retry(self):
        worker = product_worker()
        value = context(history=True)
        driver = worker.ProductDriver(1, "synthetic", native_context=value)
        driver.sessions.add("ses_synthetic")
        driver.create = Mock(return_value="ses_synthetic")
        driver.idle = Mock(return_value=True)
        driver.deadline = 2
        response = MagicMock(status=200)
        response.getheader.return_value = "application/json"
        partial = [dict(info=dict(sessionID="ses_synthetic", role="user"),
                        parts=[dict(type="text", text=worker.native_prompt_text(value["context"])), echo(value, 0)]),
                   dict(info=dict(sessionID="ses_synthetic", role="assistant", time=dict(completed=1)), parts=[])]
        response.read.side_effect = lambda size: json.dumps(partial if driver.native_prompted else []).encode()
        ack = MagicMock(status=204)
        ack.read.return_value = b""
        clock = [0]
        events = Mock()

        def quiet_queue(**kwargs):
            clock[0] += 0.25  # No real sleep, threads, listeners or native process.
            raise worker.queue.Empty

        events.queue.get.side_effect = quiet_queue
        shim = MagicMock(server_address=("127.0.0.1", 1))
        with patch.object(worker, "receive_dispatch", return_value=value), \
                patch.object(worker, "validate_surface"), \
                patch.object(worker, "HTTPServer", return_value=shim), \
                patch.object(worker.socket, "socket") as socket, \
                patch.object(worker.threading, "Thread"), \
                patch.object(worker, "open", mock_open(), create=True), \
                patch.object(worker.previous, "Server"), \
                patch.object(worker, "ProductDriver", return_value=driver), \
                patch.object(worker, "ProductEvents", return_value=events), \
                patch.object(worker.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(worker, "read_surface", return_value={name: "# Draft\n" for name in protocol.FILES}), \
                patch.object(previous.Driver, "open", side_effect=lambda method, operation, *args:
                             (Mock(), ack if operation == "prompt" else response)) as send, \
                patch.object(driver, "finish") as finish, patch.object(worker, "emit") as emit:
            socket.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 1)
            self.assertEqual(worker.main(), 1)
            finish.assert_not_called()
            self.assertEqual(emit.call_args_list[-1].args, ("failed", {"reason": "worker_deadline"}))
            self.assertFalse(any(call.args[0] == "completed" for call in emit.call_args_list))
            self.assertEqual(sum(call.args[1] == "prompt" for call in send.call_args_list), 1)
            self.assertGreater(response.read.call_count, 2)  # Actual main-loop read polling.
            self.assertEqual(driver.deadline, 2)
            self.assertEqual(driver.prompts, 1)
        self.assertIsNone(driver.native_manifest)

    def test_product_event_queue_contains_no_binary_echo(self):
        import queue

        worker = product_worker()
        value = context(b"%PDF-" + b"x" * 400_000)
        driver = worker.ProductDriver(1, "synthetic", native_context=value)
        reader = object.__new__(worker.ProductEvents)
        reader.driver, reader.stopped, reader.queue, reader.bytes = driver, threading.Event(), queue.Queue(), 0
        update = dict(type="message.part.updated", properties=dict(part=echo(value)))
        status = dict(type="session.status", properties=dict(sessionID="ses_synthetic", status=dict(type="idle")))
        reader.response = io.BytesIO(b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in (update, status)))
        real_parse = previous.parse_event

        def arrived(stream, **kwargs):
            driver.sessions.add("ses_synthetic")  # Session created DURING the first blocking read.
            return real_parse(stream, **kwargs)

        with patch.object(previous, "parse_event", side_effect=arrived):
            reader.read()
        self.assertEqual(reader.queue.get_nowait(), status)
        self.assertEqual(reader.queue.get_nowait()["type"], "driver.stream.failed")  # Controlled EOF.
        self.assertTrue(reader.queue.empty())

    def test_broker_native_start_never_uses_synthetic_ack_or_restarts_retained_turn(self):
        value = context()
        ledger = book(value)
        instance = object.__new__(broker.Broker)
        instance.epoch, instance.turns, instance.aborted_unknown = ledger.epoch, {}, {}
        instance.scratch_parent = "/tmp/opencode"
        start = command(ledger.key, ledger.epoch, "start", payload=value, deadline=time.time() + 55)
        instance.transport_factory = broker.SyntheticProduct
        with self.assertRaises(ValueError):
            instance.handle(start)
        instance.transport_factory = Mock()  # Trusted construction, no runtime/native thread started.
        with patch.object(broker.threading.Thread, "start") as launch:
            instance.handle(start)
            launch.assert_called_once()
            with self.assertRaises(ValueError):
                instance.handle(start)
            launch.assert_called_once()
        turn = instance.turns[ledger.key[2]]
        self.assertLessEqual(turn.deadline - time.monotonic(), 55)
        self.assertTrue(turn.confirm_stop())
        instance.handle(command(ledger.key, ledger.epoch, "purge"))
        self.assertIsNone(turn.payload)
        with self.assertRaises(ValueError):
            instance.handle(start)
        source = broker.SyntheticProduct(value["context"])
        call = book(value).begin(None)
        with self.assertRaises(ValueError):
            next(source.events(responses(value), threading.Event(), time.monotonic() + 1, submission=call))
        with self.assertRaises(ValueError):
            call.consumed(responses(value))  # Shared legacy receipt helper also cannot relabel an ACK.
        call.finish()
        self.assertEqual(call.row["status"], "failed-before-send")


class StopTests(unittest.TestCase):
    def test_confirmed_stop_closes_and_joins_a_held_native_body_gate(self):
        value = context()
        ledger = book(value)
        turn = broker.Turn(ledger.key, value, epoch=ledger.epoch)
        turn.receipts = ledger
        call = ledger.begin(None)
        errors = []

        def held():
            try:
                call.bind(responses(value), cancelled=threading.Event(), deadline=time.monotonic() + 2)
            except ValueError:
                errors.append("cancelled-before-write")
            finally:
                call.finish()

        thread = threading.Thread(target=held)
        thread.start()
        self.addCleanup(thread.join, 2)
        limit = time.monotonic() + 1
        while ledger.pending_authorization() is None and time.monotonic() < limit:
            time.sleep(0.002)
        self.assertIsNotNone(ledger.pending_authorization())
        upstream = Mock()
        upstream.thread = thread

        def joined(*args):
            self.assertFalse(turn.stopped.is_set())
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertIsNone(ledger.active)

        upstream.__exit__ = Mock(side_effect=joined)
        turn.relay = upstream
        self.assertTrue(turn.confirm_stop())
        self.assertEqual(errors, ["cancelled-before-write"])
        self.assertIsNone(ledger.pending_authorization())
        self.assertEqual(ledger.snapshot()[0]["status"], "failed-before-send")

    def test_turn_run_passes_inline_pipe_but_factory_gets_metadata_and_tears_down_before_stop(self):
        value = context()
        ledger = book(value)
        factory = Mock(return_value=Mock())
        turn = broker.Turn(ledger.key, value, epoch=ledger.epoch, transport_factory=factory)
        process, upstream, scratch, root = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        process.poll.return_value = None
        upstream.thread.is_alive.return_value = False
        upstream.deadline = time.monotonic() + 60

        def delivered(child, inline, **kwargs):
            self.assertIs(child, process)
            self.assertEqual(inline, value)
            self.assertTrue(kwargs["native"])
            turn.abort_requested.set()  # The mock delivers no native events/requests.

        def reaped(*args, **kwargs):
            self.assertFalse(turn.stopped.is_set())
            process.poll.return_value = 0

        def removed():
            self.assertIsNone(turn.process)
            self.assertIsNone(turn.relay)
            self.assertFalse(turn.stopped.is_set())

        process.wait.side_effect = reaped
        scratch.cleanup.side_effect = removed
        with patch.object(broker.tempfile, "TemporaryDirectory", return_value=scratch), \
                patch.object(broker, "Path", return_value=root), \
                patch.object(broker, "copy_worker_code"), patch.object(broker, "worker_command", return_value=[]), \
                patch.object(broker, "SyntheticRelay", return_value=upstream), \
                patch.object(broker.subprocess, "Popen", return_value=process), \
                patch.object(broker, "send_pipe", side_effect=delivered), \
                patch.object(broker.selectors, "DefaultSelector"), patch.object(broker.os, "killpg"):
            turn.run()
        factory.assert_called_once_with(value["context"])
        self.assertIsNone(turn.payload)
        self.assertTrue(turn.stopped.is_set())
        self.assertEqual(turn.receipts.snapshot()[0]["status"], "failed-before-send")

    def test_stop_requires_reap_relay_join_scratch_purge_and_retries_cleanup_only(self):
        for failure in (None, "worker", "relay", "scratch"):
            value = context()
            ledger = book(value)
            turn = broker.Turn(ledger.key, value, epoch=ledger.epoch)
            process, upstream, scratch = Mock(), Mock(), Mock()
            process.poll.return_value = None
            process.pid = 12345
            upstream.thread.is_alive.return_value = False
            turn.process, turn.relay, turn.scratch = process, upstream, scratch
            order = []

            def phase(name):
                def check(*args, **kwargs):
                    self.assertFalse(turn.stopped.is_set())
                    order.append(name)
                    if name == failure:
                        raise OSError("synthetic teardown failure")
                return check

            process.wait.side_effect = phase("worker")
            upstream.__exit__ = Mock(side_effect=phase("relay"))
            scratch.cleanup.side_effect = phase("scratch")
            with patch.object(broker.os, "killpg") as kill:
                success = turn.confirm_stop()
                self.assertEqual(success, failure is None)
                self.assertIsNone(turn.payload)
                self.assertIsNone(turn.receipts.pending_authorization())
                if failure is not None:
                    with self.assertRaises(ValueError):
                        turn.purge()
                    process.wait.side_effect = phase("reaped")
                    upstream.__exit__.side_effect = phase("joined")
                    scratch.cleanup.side_effect = phase("removed")
                    self.assertTrue(turn.confirm_stop())  # No prompt/reply dispatch on retry.
                self.assertTrue(turn.stopped.is_set())
                self.assertIsNone(turn.process)
                self.assertIsNone(turn.relay)
                self.assertIsNone(turn.scratch)
                kill.assert_called()
            if failure is None:
                self.assertEqual(order, ["worker", "relay", "scratch"])
            turn.purge()
            self.assertTrue(turn.purged)
            self.assertEqual(turn.events, [])
            self.assertEqual(turn.receipts.snapshot()[0]["status"], "failed-before-send")


if __name__ == "__main__":
    unittest.main()
