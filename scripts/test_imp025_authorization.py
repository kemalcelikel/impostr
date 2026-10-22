"""B2 pure host gate/receipt/transport seams; no sockets, workers, DNS or provider."""

import copy
import hashlib
import json
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch

from test_imp025_inline import context, responses, protocol
from test_imp024_operator import planning
import imp018_receipts as receipts
import imp024_broker as broker
import imp024_inference as inference


def book(value):
    return receipts.ReceiptLedger(tuple(str(uuid.uuid4()) for _ in range(3)), str(uuid.uuid4()), value)


class AuthorizationTests(unittest.TestCase):
    def hold(self, ledger, operation):
        errors = []

        def run():
            try:
                operation()
            except Exception as exc:
                errors.append(type(exc))  # No request/exception data in diagnostics.

        thread = threading.Thread(target=run)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(ledger.close)
        limit = time.monotonic() + 1
        while time.monotonic() < limit:
            pending = ledger.pending_authorization()
            if pending is not None:
                return thread, errors, pending
            if not thread.is_alive():
                break
            time.sleep(0.002)
        self.fail("Native call did not reach metadata gate")

    def grant(self, pending):
        return dict(pending, authorization_id=str(uuid.uuid4()))

    def test_final_model_bytes_wait_for_scoped_single_use_gate_and_error_keeps_sent(self):
        value = context(history=True)
        data = responses(value)
        ledger = book(value)
        call = ledger.begin(b"worker serialization is not the final request")
        transport, response = planning(b"".join(inference.native_response("Synthetic safe response")))
        connection = Mock()
        transport.connection = Mock(return_value=connection)

        def reject_response():
            self.assertEqual(ledger.snapshot()[0]["status"], "sent")
            raise OSError("synthetic provider rejection")

        connection.getresponse.side_effect = reject_response

        def submit(*args):
            self.assertEqual(ledger.snapshot()[0]["status"], "uncertain")

        connection.request.side_effect = submit
        thread, errors, pending = self.hold(ledger, lambda: list(transport.events(
            data, threading.Event(), time.monotonic() + 2, submission=call)))
        transport.connection.assert_not_called()
        self.assertEqual(ledger.snapshot(), [])
        expected = dict(data, model=transport.contract.deployment, stream=True, store=False,
                        max_output_tokens=4096)
        encoded = json.dumps(expected, ensure_ascii=True, separators=(",", ":")).encode()
        self.assertEqual(pending["request_sha256"], hashlib.sha256(encoded).hexdigest())
        self.assertEqual(pending["request_size"], len(encoded))
        self.assertEqual(pending["original_manifest"], [item["manifest"] for item in value["files"]])
        self.assertNotIn("file_data", json.dumps(pending))
        grant = self.grant(pending)
        ledger.grant(grant)
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        call.finish()
        connection.request.assert_called_once()
        self.assertEqual(connection.request.call_args.args[2], encoded)
        self.assertEqual(ledger.snapshot()[0]["authorization_id"], grant["authorization_id"])
        self.assertEqual(ledger.snapshot()[0]["reference_kind"], "native-original-v1")
        with self.assertRaises(ValueError):
            ledger.grant(grant)

    def test_wrong_missing_foreign_changed_or_reordered_original_cannot_bind(self):
        value = context(history=True)
        for mutation in (lambda d: d["input"][0]["content"].pop(),
                         lambda d: d["input"][0]["content"].reverse(),
                         lambda d: d["input"][0]["content"][1].update(filename="foreign.pdf"),
                         lambda d: d["input"][0]["content"][1].update(file_data="data:application/pdf;base64,JVBERi15")):
            data = responses(value)
            mutation(data)
            ledger = book(value)
            call = ledger.begin(b"wrong")
            with self.assertRaises(ValueError):
                call.bind(data, cancelled=threading.Event(), deadline=time.monotonic() + 1)
            call.finish()
            self.assertIsNone(ledger.pending_authorization())
            self.assertEqual(ledger.snapshot()[0]["status"], "failed-before-send")

    def test_changed_serialization_never_hashes_an_unrelated_object(self):
        value = context()
        call = book(value).begin(None)
        with self.assertRaises(ValueError):
            call.bind(responses(value), b"{}", cancelled=threading.Event(), deadline=time.monotonic() + 1)
        call.finish()
        self.assertIsNone(call.row["request_sha256"])

    def test_native_connection_failure_is_definite_but_possible_partial_write_is_uncertain(self):
        for failure in ("connect", "write"):
            value = context()
            ledger = book(value)
            call = ledger.begin(None)
            transport, _ = planning(b"".join(inference.native_response("Synthetic result")))
            connection = Mock()
            transport.connection = Mock(return_value=connection)
            if failure == "connect":
                transport.connection.side_effect = OSError("Synthetic connection construction failure")
            else:
                connection.request.side_effect = OSError("Synthetic partial write")
            thread, errors, pending = self.hold(ledger, lambda: list(transport.events(
                responses(value), threading.Event(), time.monotonic() + 2, submission=call)))
            ledger.grant(self.grant(pending))
            thread.join(1)
            self.assertEqual(len(errors), 1)
            call.finish()
            self.assertEqual(ledger.snapshot()[0]["status"],
                             "uncertain" if failure == "write" else "failed-before-send")
            self.assertEqual(connection.request.call_count, 1 if failure == "write" else 0)

    def test_scope_hash_size_call_and_order_mismatch_cannot_consume_pending_gate(self):
        value = context(history=True)
        ledger = book(value)
        call = ledger.begin(None)
        thread, errors, pending = self.hold(ledger, lambda: call.bind(
            responses(value), cancelled=threading.Event(), deadline=time.monotonic() + 2))
        for field, wrong in (("epoch", str(uuid.uuid4())), ("project_id", str(uuid.uuid4())),
                             ("request_sha256", "f" * 64), ("request_size", pending["request_size"] + 1),
                             ("call", 2)):
            with self.assertRaises(ValueError):
                ledger.grant(dict(self.grant(pending), **{field: wrong}))
        changed = self.grant(copy.deepcopy(pending))
        changed["original_manifest"].reverse()
        with self.assertRaises(ValueError):
            ledger.grant(changed)
        ledger.grant(self.grant(pending))
        thread.join(1)
        self.assertEqual(errors, [])
        call.attempting()
        with self.assertRaises(ValueError):
            call.attempting()
        call.finish()
        self.assertEqual(ledger.snapshot()[0]["status"], "uncertain")

    def test_trusted_transport_followup_reconstructed_history_requires_a_fresh_gate_each_call(self):
        value = context(history=True)
        data = responses(value)
        ledger = book(value)
        transport, _ = planning(b"".join(inference.native_response("Synthetic safe response")))
        connection = Mock()
        # A mocked receiver failure occurs AFTER the complete request was sent.
        # This tests the transport seam, not a native runtime success claim.
        connection.getresponse.side_effect = OSError("synthetic receiver rejection")
        transport.connection = Mock(return_value=connection)
        for index in (1, 2):
            call = ledger.begin(None)
            thread, errors, pending = self.hold(ledger, lambda: list(transport.events(
                data, threading.Event(), time.monotonic() + 2, submission=call)))
            self.assertEqual(pending["call"], index)
            self.assertEqual(len(pending["original_manifest"]), 2)
            ledger.grant(self.grant(pending))
            thread.join(1)
            self.assertEqual(len(errors), 1)
            call.finish()
            if index == 1:
                from imp024_protocol import fixture_definitions
                data["tools"] = fixture_definitions()
                data["input"].extend([
                    dict(type="function_call", call_id="call_followup", name="read",
                         arguments=json.dumps({"filePath": "/project/PROJECT.md"})),
                    dict(type="function_call_output", call_id="call_followup", output="Synthetic tool result")])
        rows = ledger.snapshot()
        self.assertEqual([row["status"] for row in rows], ["sent", "sent"])
        self.assertNotEqual(rows[0]["request_sha256"], rows[1]["request_sha256"])
        self.assertEqual(rows[0]["original_manifest_sha256"], rows[1]["original_manifest_sha256"])
        self.assertEqual(connection.request.call_count, 2)
        self.assertEqual(connection.request.call_args.args[2], json.dumps(
            dict(data, model=transport.contract.deployment, stream=True, store=False, max_output_tokens=4096),
            ensure_ascii=True, separators=(",", ":")).encode())

    def test_cancel_outage_and_expiry_before_or_after_grant_fail_before_write(self):
        for failure in ("outage", "cancel", "expired-after-grant"):
            cancelled = threading.Event()
            value = context()
            ledger = book(value)
            call = ledger.begin(None)
            thread, errors, pending = self.hold(ledger, lambda: call.bind(
                responses(value), cancelled=cancelled, deadline=time.monotonic() + 2))
            if failure == "outage":
                ledger.close()
            elif failure == "cancel":
                cancelled.set()
            else:
                ledger.grant(self.grant(pending))
            thread.join(1)
            if failure == "expired-after-grant":
                self.assertEqual(errors, [])
                call.gate_deadline = time.monotonic() - 1
                with self.assertRaises(ValueError):
                    call.attempting()
            else:
                self.assertEqual(len(errors), 1)
                with self.assertRaises(ValueError):
                    ledger.grant(self.grant(pending))
            call.finish()
            self.assertIsNone(ledger.pending_authorization())
            self.assertEqual(ledger.snapshot()[0]["status"], "failed-before-send")

    def test_unanswered_gate_expires_without_send_and_stop_preserves_only_metadata(self):
        value = context()
        ledger = book(value)
        call = ledger.begin(None)
        with patch.object(receipts, "SEND_GATE_SECONDS", 0.05):
            thread, errors, pending = self.hold(ledger, lambda: call.bind(
                responses(value), cancelled=threading.Event(), deadline=time.monotonic() + 1))
            thread.join(1)
        self.assertEqual(len(errors), 1)
        with self.assertRaises(ValueError):
            ledger.grant(self.grant(pending))
        call.finish()
        ledger.close()
        self.assertIsNone(ledger.pending_authorization())
        self.assertIsNone(ledger.active)
        self.assertNotIn("file_data", json.dumps(ledger.snapshot()))
        self.assertNotIn("url", json.dumps(ledger.__dict__, default=str))

    def test_poll_exposes_metadata_and_grant_cannot_reopen_a_stopped_turn(self):
        value = context()
        ledger = book(value)
        call = ledger.begin(None)
        thread, errors, pending = self.hold(ledger, lambda: call.bind(
            responses(value), cancelled=threading.Event(), deadline=time.monotonic() + 2))
        instance = object.__new__(broker.Broker)
        instance.epoch = ledger.epoch
        turn = Mock(key=ledger.key, receipts=ledger, lock=threading.Lock(), events=[])
        turn.stopped = threading.Event()
        turn.abort_requested = threading.Event()
        instance.turns = {ledger.key[2]: turn}
        instance.aborted_unknown = {}
        base = dict(epoch=ledger.epoch, **dict(zip(("project_id", "conversation_id", "turn_id"), ledger.key)))
        result = instance.handle(dict(base, op="poll", after=0))
        self.assertEqual(result["send_authorization"], pending)
        protocol.encode(result)
        command = dict(base, op="authorize-send", authorization=self.grant(pending))
        turn.stopped.set()
        with self.assertRaises(ValueError):
            instance.handle(command)
        turn.stopped.clear()
        instance.handle(command)
        thread.join(1)
        self.assertEqual(errors, [])
        call.attempting()
        call.sent()
        call.finish()
        self.assertNotIn("send_authorization", instance.handle(dict(base, op="poll", after=0)))


if __name__ == "__main__":
    unittest.main()
