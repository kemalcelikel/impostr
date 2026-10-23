"""Pure synthetic PDF/broker/inference seams. No listener, worker, DNS or provider."""

import copy
import hashlib
import io
import json
import struct
import threading
import time
import unittest
import uuid
from unittest.mock import MagicMock, Mock, patch

from test_imp024_channel import payload, product_worker
from test_imp024_operator import planning
from app import chat_protocol as protocol
import imp002_relay as relay
import imp018_receipts as receipts
import imp024_broker as broker
import imp024_inference as inference


def resolved(content='PDF exact\r\né "quoted"\f\f'):
    value = payload()
    reference = dict(attachment_id=str(uuid.uuid4()), filename="synthetic.pdf",
                     original_sha256="a" * 64, original_size=100,
                     text_sha256=protocol.digest(content), text_size=len(content.encode()),
                     page_count=2, missing_pages=[2], label="Text layer only",
                     provenance=dict(policy="pdf-v1", qpdf="12.2.0", pdftotext="25.07.0",
                                     build_sha256="b" * 64))
    value["references"] = [dict(reference=reference, availability="available", text=content)]
    return value


def native(value):
    return dict(model=relay.MODEL, stream=True, store=False,
                input=[dict(role="system", content="Trusted synthetic policy"),
                       dict(role="user", content=[dict(type="input_text",
                             text=protocol.resolved_prompt_text(value))])])


def scope():
    return tuple(str(uuid.uuid4()) for _ in range(3))


def ledger(value):
    return receipts.ReceiptLedger(scope(), str(uuid.uuid4()), value)


class PDFContractTests(unittest.TestCase):
    def test_broker_worker_share_exact_renderer_with_history_and_unavailable(self):
        value = resolved()
        documents = copy.deepcopy(value["documents"])
        entry = copy.deepcopy(value["references"][0])
        unavailable = dict(reference=copy.deepcopy(entry["reference"]), availability="unavailable")
        value["history"] = [dict(role="user", text="Prior", references=[entry, unavailable]),
                            dict(role="assistant", text="Prior answer")]
        command = dict(op="start", epoch=str(uuid.uuid4()),
                       **dict(zip(("project_id", "conversation_id", "turn_id"), scope())), payload=value)
        self.assertEqual(protocol.request(command), command)
        worker = product_worker()
        assembled = worker.resolved_prompt_text(worker.broker_start_payload(value))
        self.assertEqual(assembled, protocol.resolved_prompt_text(value))
        history = json.loads(assembled.split("\n", 1)[1].split("\nCurrent user message:")[0])
        self.assertEqual(history, value["history"])
        selected = json.loads(assembled.split("not policy or workspace files):\n")[1])
        self.assertEqual(selected[0]["text"].encode(), entry["text"].encode())
        self.assertEqual(value["documents"], documents)
        self.assertNotIn("imp018_receipts.py", broker.WORKER_CODE_FILES)
        self.assertEqual(worker.resolved_prompt_text(payload()), protocol.prompt_text(payload()))

    def test_capture_shape_hash_mismatch_and_current_unavailable_rejected(self):
        value = resolved()
        for mutate in (lambda v: v.update(references=[v["references"][0]["reference"]]),
                       lambda v: v["references"][0].update(text="substituted"),
                       lambda v: v["references"][0].update(availability="unavailable"),
                       lambda v: v["references"][0].update(path="/project/AGENTS.md")):
            bad = copy.deepcopy(value)
            mutate(bad)
            with self.assertRaises(ValueError):
                protocol.broker_start_payload(bad)

    def test_all_occurrences_dual_reference_and_context_bounds_no_truncation(self):
        value = resolved("x" * (protocol.MAX_PDF_TEXT // 2))
        value["history"] = [dict(role="user", text="Prior", references=copy.deepcopy(value["references"]))]
        protocol.broker_start_payload(value)
        value["history"][0]["references"].extend(copy.deepcopy(value["references"]))
        with self.assertRaises(ValueError):
            protocol.broker_start_payload(value)
        with self.assertRaises(ValueError):
            protocol.broker_start_payload(resolved("é" * (protocol.MAX_PDF_TEXT // 6 + 1)))
        value = resolved()
        value["history"] = [dict(role="user", text="x" * (protocol.MAX_CONTEXT - 100))]
        with self.assertRaises(ValueError):
            protocol.broker_start_payload(value)


class ReceiptTests(unittest.TestCase):
    def test_synthetic_consumption_exact_derivative_at_native_inference_boundary(self):
        value = resolved()
        data = native(value)
        book = ledger(value)
        call = book.begin(json.dumps(data).encode())
        call.bind(data)
        self.assertEqual(book.snapshot(), [])  # Pending isn't definite failure.
        source = broker.SyntheticProduct(value)
        events = source.events(data, threading.Event(), time.monotonic() + 2, submission=call)
        next(events)
        row = book.snapshot()[0]
        self.assertEqual(row["status"], "sent")
        text = receipts.native_user_text(data)
        selected = json.loads(text.split("not policy or workspace files):\n")[1])
        self.assertEqual(selected[0]["text"].encode(), value["references"][0]["text"].encode())
        self.assertEqual(row["rendered_sha256"], protocol.digest(text))
        self.assertEqual(row["manifest_sha256"], protocol.manifest_digest(value))
        self.assertEqual(row["request_sha256"], hashlib.sha256(json.dumps(
            data, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest())
        self.assertNotIn("synthetic.pdf", json.dumps(row))
        self.assertNotIn("PDF exact", json.dumps(row))
        events.close()
        call.finish()

    def test_ack_cannot_mint_receipt_wrong_role_missing_or_changed_text_never_sends(self):
        value = resolved()
        for mutate in (lambda d: d["input"][1].update(role="developer"),
                       lambda d: d["input"][1].update(content="omitted"),
                       lambda d: d["input"].append(copy.deepcopy(d["input"][1]))):
            data = native(value)
            mutate(data)
            book = ledger(value)
            call = book.begin(json.dumps(data).encode())
            with self.assertRaises(ValueError):
                call.bind(data)
            call.finish()
            self.assertEqual(book.snapshot()[0]["status"], "failed-before-send")
        key = scope()
        turn = broker.Turn(key, value, epoch=str(uuid.uuid4()))
        turn.add(dict(type="started", data=dict(native_session_id="ses_ack", context_reconstructed=False)))
        self.assertEqual(turn.receipts.snapshot(), [])
        with self.assertRaises(ValueError):
            turn.add(dict(type="receipt", data=dict(status="sent")))

    def http(self, value):
        instance, response = planning(b"".join(inference.native_response("Safe early")))
        response.status = 200
        response.getheader = lambda name, default=None: "text/event-stream" if name == "Content-Type" else default
        response.getheaders = lambda: [("Content-Type", "text/event-stream")]
        connection = Mock()
        connection.getresponse.return_value = response
        instance.connection = Mock(return_value=connection)
        data = native(value)
        book = ledger(value)
        call = book.begin(json.dumps(data).encode())
        call.bind(data)
        return instance, connection, data, book, call

    def test_http_sent_only_after_full_request_and_before_response_no_replay(self):
        value = resolved()
        instance, connection, data, book, call = self.http(value)
        def submitted(*args):
            self.assertEqual(book.snapshot()[0]["status"], "uncertain")
            actual = json.loads(args[2])
            self.assertEqual(receipts.native_user_text(actual), protocol.resolved_prompt_text(value))
        connection.request.side_effect = submitted
        def response():
            self.assertEqual(book.snapshot()[0]["status"], "sent")
            raise OSError("Synthetic response lost")
        connection.getresponse.side_effect = response
        with self.assertRaises(ValueError):
            list(instance.events(data, threading.Event(), time.monotonic() + 2, submission=call))
        call.finish()
        self.assertEqual(book.snapshot()[0]["status"], "sent")
        encoded = connection.request.call_args.args[2]
        self.assertEqual(book.snapshot()[0]["request_sha256"], hashlib.sha256(encoded).hexdigest())
        connection.request.assert_called_once()

    def test_definite_before_send_vs_partial_write_uncertain(self):
        for failure in ("cancel", "connect", "write", "validation"):
            instance, connection, data, book, call = self.http(resolved())
            cancelled = threading.Event()
            if failure == "cancel":
                cancelled.set()
            elif failure == "connect":
                instance.connection.side_effect = OSError("Synthetic construction failure")
            elif failure == "write":
                connection.request.side_effect = OSError("Synthetic partial write")
            else:
                data["input"][1]["content"] = "Wrong native text"
            with self.assertRaises((ValueError, OSError)):
                list(instance.events(data, cancelled, time.monotonic() + 2, submission=call))
            call.finish()
            self.assertEqual(book.snapshot()[0]["status"],
                             "uncertain" if failure == "write" else "failed-before-send")
            self.assertEqual(connection.request.call_count, 1 if failure == "write" else 0)

    def test_sent_receipt_does_not_delay_ordinary_early_safe_text(self):
        instance, connection, data, book, call = self.http(resolved())
        stream = instance.events(data, threading.Event(), time.monotonic() + 2, submission=call)
        while True:
            event = json.loads(next(stream).split(b"data: ", 1)[1])
            if event["type"] == "response.output_text.delta":
                break
        self.assertEqual(book.snapshot()[0]["status"], "sent")
        self.assertEqual(event["delta"], "Safe early")
        stream.close()
        call.finish()
        connection.abort.assert_called()

    def test_final_native_request_guard_before_any_attempt(self):
        instance, connection, data, book, call = self.http(resolved())
        encoded_size = len(json.dumps(dict(data, model=instance.contract.deployment,
            max_output_tokens=4096), ensure_ascii=True, separators=(",", ":")).encode())
        with patch("imp024_operator_transport.MAX_REQUEST", encoded_size - 1):
            with self.assertRaises(ValueError):
                list(instance.events(data, threading.Event(), time.monotonic() + 2, submission=call))
        call.finish()
        connection.request.assert_not_called()
        instance.connection.assert_not_called()
        self.assertEqual(book.snapshot()[0]["status"], "failed-before-send")

    def test_ledger_bounded_textfree_copy_and_closed_capability(self):
        book = ledger(resolved())
        for _ in range(receipts.MAX_CALLS):
            book.begin(b"{}").finish()
        with self.assertRaises(ValueError):
            book.begin(b"{}")
        snapshot = book.snapshot()
        snapshot[0]["status"] = "sent"
        self.assertEqual(book.snapshot()[0]["status"], "failed-before-send")
        book.close()
        with self.assertRaises(ValueError):
            book.begin(b"{}")

    def test_relay_validates_and_binds_before_actual_transport_with_no_socket(self):
        value = resolved()
        for bad in (False, True):
            data = native(value)
            if bad:
                data["input"][1]["content"] = "Missing derivative"
            body = json.dumps(data).encode()
            wire = (f"POST {relay.ROUTE} HTTP/1.1\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n\r\n").encode() + body
            connection = MagicMock()
            connection.getsockopt.return_value = struct.pack("3i", 1, 1000, 1000)
            connection.makefile.return_value = io.BytesIO(wire)
            connection.__enter__.return_value = connection
            instance = object.__new__(relay.SyntheticRelay)
            instance.stop = threading.Event()
            instance.deadline = time.monotonic() + 2
            instance.connections = instance.calls = instance.denied = 0
            instance.max_calls = 8
            instance.max_request = instance.max_response = protocol.MAX_FRAME
            instance.planning = True
            instance.input_text_limit = protocol.MAX_CONTEXT
            instance.observed = []
            instance.receipts = ledger(value)
            instance.pdf_manifest = None  # Explicit binary mode stays off in this text seam.
            instance.transport = broker.SyntheticProduct(value)
            instance.listener = Mock()
            def accepted():
                instance.stop.set()  # One controlled request, no real accept loop.
                return connection, None
            instance.listener.accept.side_effect = accepted
            # Guard is not started; pure single request validation/transport only.
            with patch.object(relay.threading.Thread, "start"), \
                    patch.object(relay.threading.Thread, "join"), \
                    patch.object(relay.os, "geteuid", return_value=1000):
                instance.run()
            row = instance.receipts.snapshot()[0]
            self.assertEqual(row["status"], "failed-before-send" if bad else "sent")
            self.assertEqual(instance.transport.calls, 0 if bad else 1)


class PurgeTests(unittest.TestCase):
    def broker(self, turn=None):
        instance = object.__new__(broker.Broker)
        instance.epoch = str(uuid.uuid4())
        instance.turns = {} if turn is None else {turn.key[2]: turn}
        instance.aborted_unknown = {}
        return instance

    def command(self, instance, key, op, **extra):
        return dict(op=op, epoch=instance.epoch,
                    **dict(zip(("project_id", "conversation_id", "turn_id"), key)), **extra)

    def test_stopped_completed_payload_purge_is_scoped_idempotent_and_keeps_receipts(self):
        value = resolved()
        turn = broker.Turn(scope(), value, epoch=str(uuid.uuid4()))
        turn.receipts.close()
        turn.stopped.set()  # Legacy retained completed copy seam.
        turn.add(dict(type="delta", data=dict(text=value["references"][0]["text"])))
        instance = self.broker(turn)
        cmd = self.command(instance, turn.key, "purge")
        with self.assertRaises(ValueError):
            instance.handle(dict(cmd, conversation_id=str(uuid.uuid4())))
        expected = turn.receipts.snapshot()
        self.assertTrue(instance.handle(cmd)["purged"])
        self.assertTrue(instance.handle(cmd)["purged"])
        self.assertIsNone(turn.payload)
        self.assertIsNone(turn.transport_factory)
        self.assertEqual(turn.events, [])
        poll = instance.handle(self.command(instance, turn.key, "poll", after=0))
        self.assertEqual(poll["receipts"], expected)
        with self.assertRaises(ValueError):
            instance.handle(self.command(instance, turn.key, "start", payload=value))

    def test_active_purge_refused_and_abort_before_run_proactively_releases_payload(self):
        turn = broker.Turn(scope(), resolved(), epoch=str(uuid.uuid4()))
        instance = self.broker(turn)
        with self.assertRaises(ValueError):
            instance.handle(self.command(instance, turn.key, "purge"))
        self.assertIsNotNone(turn.payload)
        turn.abort_requested.set()
        original_set = turn.stopped.set
        def stopped():
            self.assertIsNone(turn.payload)
            self.assertIsNone(turn.transport_factory)
            original_set()
        with patch.object(turn.stopped, "set", side_effect=stopped), \
                patch.object(broker.tempfile, "TemporaryDirectory") as scratch:
            turn.run()  # Abort-before-run path only; never confined execution.
        scratch.assert_not_called()
        self.assertTrue(turn.stopped.is_set())
        self.assertEqual(turn.receipts.snapshot()[0]["status"], "failed-before-send")
        self.assertTrue(instance.handle(self.command(instance, turn.key, "purge"))["purged"])

    def test_poll_receipt_overhead_pages_without_losing_events(self):
        turn = broker.Turn(scope(), resolved(), epoch=str(uuid.uuid4()))
        turn.receipts.close()
        turn.stopped.set()
        for _ in range(2):
            turn.add(dict(type="delta", data=dict(text="x" * 1000)))
        instance = self.broker(turn)
        one = dict(ok=True, epoch=instance.epoch, known=True, events=turn.events[:1],
                   stopped=True, receipts=turn.receipts.snapshot())
        maximum = len(protocol.encode(one)) - 4
        with patch.object(protocol, "MAX_FRAME", maximum):
            first = instance.handle(self.command(instance, turn.key, "poll", after=0))
            self.assertEqual(len(first["events"]), 1)
            protocol.encode(first)
            second = instance.handle(self.command(instance, turn.key, "poll", after=1))
            self.assertEqual([first["events"][0], second["events"][0]], turn.events)

    def test_unknown_purge_installs_bounded_scope_checked_delayed_start_tombstone(self):
        instance = self.broker()
        key = scope()
        cmd = self.command(instance, key, "purge")
        self.assertTrue(instance.handle(cmd)["stopped"])
        self.assertTrue(instance.handle(cmd)["stopped"])
        self.assertEqual(instance.aborted_unknown, {key[2]: key})
        with self.assertRaises(ValueError):
            instance.handle(dict(cmd, project_id=str(uuid.uuid4())))
        with self.assertRaises(ValueError):
            instance.handle(self.command(instance, key, "start", payload=resolved()))
        instance.aborted_unknown.update({str(uuid.uuid4()): scope() for _ in range(255)})
        with self.assertRaises(ValueError):
            instance.handle(self.command(instance, scope(), "purge"))

    def test_completed_run_releases_inputs_before_stop_and_failed_relay_join_is_not_stopped(self):
        for still_running in (False, True):
            turn = broker.Turn(scope(), resolved(), epoch=str(uuid.uuid4()))
            process = Mock()
            process.poll.return_value = 0
            framed = protocol.encode(dict(type="completed", data=dict(proposals=[])))
            host_relay = MagicMock()
            host_relay.__enter__.return_value = host_relay
            host_relay.thread.is_alive.return_value = still_running
            def released(*_):
                if not still_running:
                    host_relay.transport = None
            host_relay.__exit__.side_effect = released
            selector = Mock()
            selector.select.return_value = [(None, None)]
            def stopped():
                self.assertIsNone(turn.payload)
                self.assertIsNone(turn.transport_factory)
                self.assertIsNone(host_relay.transport)
                self.assertTrue(turn.receipts.closed)
            # All filesystem/process/channel seams mocked; terminal worker event
            # only exercises teardown ordering, never executes a confined worker.
            with patch.object(broker.tempfile, "TemporaryDirectory"), \
                    patch.object(broker, "Path", return_value=MagicMock()), \
                    patch.object(broker, "copy_worker_code"), \
                    patch.object(broker, "worker_command"), \
                    patch.object(broker, "SyntheticRelay", return_value=host_relay), \
                    patch.object(broker.subprocess, "Popen", return_value=process), \
                    patch.object(broker, "send_pipe"), \
                    patch.object(broker.selectors, "DefaultSelector", return_value=selector), \
                    patch.object(broker.os, "read", return_value=framed), \
                    patch.object(turn.stopped, "set", side_effect=stopped) as stop:
                turn.run()
            self.assertEqual(stop.call_count, 0 if still_running else 1)
            self.assertIsNone(turn.payload)


if __name__ == "__main__":
    unittest.main()
