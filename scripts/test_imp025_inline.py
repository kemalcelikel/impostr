"""B1 pure inline contract/adapters. No worker, listener, provider or DB execution."""

import base64
import copy
import hashlib
import io
import json
import queue
import struct
import threading
import unittest
from unittest.mock import patch

from test_imp025_storage import entry, payload, protocol, reference
from test_imp024_channel import product_worker
import imp002_relay as relay
from imp002_worker import Shim
import imp024_worker as planning
import imp023_worker as previous


def context(body=b"%PDF-synthetic-original", *, history=False):
    selected = reference(len(body))
    selected["original_sha256"] = hashlib.sha256(body).hexdigest()
    metadata = payload([entry(selected)])
    if history:
        metadata["history"] = [
            {"role": "user", "text": "Prior", "references": [entry(selected)]},
            {"role": "assistant", "text": "Quoted prior discussion"},
        ]
    manifest = protocol.native_occurrence_manifest(metadata)
    url = protocol.PDF_DATA_PREFIX + base64.b64encode(body).decode("ascii")
    return dict(kind=protocol.NATIVE_INLINE_CONTEXT, context=metadata,
                files=[dict(manifest=item, url=url) for item in manifest])


def responses(value):
    parts = protocol.native_prompt_parts(value)
    return dict(model=relay.MODEL, stream=True, store=False,
                input=[dict(role="user", content=[dict(type="input_text", text=parts[0]["text"])] + [
                    dict(type="input_file", filename=part["filename"], file_data=part["url"])
                    for part in parts[1:]])])


def validate(data, manifest):
    return relay.validate("POST", relay.ROUTE, json.dumps(data).encode(), planning=True,
                          input_text_limit=protocol.MAX_CONTEXT, pdf_manifest=manifest)


def echo(value, index=0):
    part = protocol.native_prompt_parts(value)[index + 1]
    return dict(part, id="prt_synthetic", sessionID="ses_synthetic", messageID="msg_synthetic")


class InlineContractTests(unittest.TestCase):
    def test_ephemeral_context_requires_explicit_native_driver_and_is_never_durable(self):
        value = context(history=True)
        self.assertEqual(protocol.native_dispatch_context(value), value)
        frame = protocol.encode_native_context(value)
        self.assertEqual(struct.unpack("!I", frame[:4])[0], len(frame) - 4)
        self.assertEqual(protocol.decode_native_context(frame[4:]), value)
        for candidate in (value, value["context"]):
            with self.assertRaises(ValueError):
                protocol.broker_start_payload(candidate)
        with self.assertRaises(ValueError):
            protocol.captured_payload(value)
        data = responses(value)
        with self.assertRaises(relay.Denied):
            relay.validate("POST", relay.ROUTE, json.dumps(data).encode(), planning=True,
                           input_text_limit=protocol.MAX_CONTEXT)
        worker = product_worker()
        # Ordinary driver construction still denies files; only authorized turn
        # construction opts in. B3 specialized framing is tested separately.
        driver = worker.ProductDriver(1, "synthetic")
        driver.sessions.add("ses_synthetic")
        driver.active_session = "ses_synthetic"
        with patch.object(previous.Driver, "open") as network:
            with self.assertRaises(ValueError):
                driver._open("POST", "prompt", "ses_synthetic", worker.native_prompt_body(value))
            network.assert_not_called()

    def test_ordered_manifest_preserves_repeated_original_and_history_before_current(self):
        value = context(history=True)
        manifest = [item["manifest"] for item in value["files"]]
        self.assertEqual([item["message_index"] for item in manifest], [0, 2])
        self.assertEqual([item["occurrence"] for item in manifest], [0, 1])
        self.assertEqual(manifest[0]["attachment_id"], manifest[1]["attachment_id"])
        self.assertNotEqual(protocol.occurrence_filename(manifest[0]), protocol.occurrence_filename(manifest[1]))
        for mutate in (lambda v: v["files"].reverse(),
                       lambda v: v["files"].pop(),
                       lambda v: v["files"][0]["manifest"].update(occurrence=True),
                       lambda v: v["files"][0]["manifest"].update(selection_index=1)):
            forged = copy.deepcopy(value)
            mutate(forged)
            with self.assertRaises(ValueError):
                protocol.native_dispatch_context(forged)

    def test_each_aggregate_and_occurrence_limits_include_repeated_history(self):
        value = context(history=True)
        manifest = [item["manifest"] for item in value["files"]]
        for item in manifest:
            item["original_size"] = 24_999_999
        protocol.native_manifest(manifest)
        for item in manifest:
            item["original_size"] = 25_000_000
        with self.assertRaises(ValueError):
            protocol.native_manifest(manifest)
        with self.assertRaises(ValueError):
            protocol.native_manifest([dict(manifest[0], original_size=50_000_000)])
        selected = value["context"]["references"][0]
        metadata = payload([selected] * 32)
        metadata["history"] = [{"role": "user", "text": "Prior", "references": [selected] * 32}
                               for _ in range(12)]
        all_files = protocol.native_occurrence_manifest(metadata)
        self.assertEqual(len(all_files), 416)
        self.assertEqual(protocol.MAX_NATIVE_PDF_FILES, 32)  # Existing API selection bound.
        with self.assertRaises(ValueError):
            protocol.native_manifest(all_files + [dict(all_files[-1], occurrence=416)])

    def test_wrong_bytes_hash_size_and_noncanonical_base64_are_rejected(self):
        value = context(b"%PDF-x")  # Six bytes; separately exercise canonical padding below.
        for url in ("https://example.invalid/file.pdf", "file:///project/upload.pdf",
                    "data:image/png;base64," + base64.b64encode(b"%PDF-x").decode(),
                    value["files"][0]["url"] + "\n",
                    protocol.PDF_DATA_PREFIX + base64.b64encode(b"notPDF").decode(),
                    protocol.PDF_DATA_PREFIX + base64.b64encode(b"%PDF-y").decode()):
            forged = copy.deepcopy(value)
            forged["files"][0]["url"] = url
            with self.assertRaises(ValueError):
                protocol.native_dispatch_context(forged)
        padded = context(b"%PDF-xx")
        url = padded["files"][0]["url"]
        self.assertTrue(url.endswith("eA=="))
        # Same decoded bytes, different nonzero unused padding bits.
        padded["files"][0]["url"] = url[:-4] + "eB=="
        with self.assertRaises(ValueError):
            protocol.native_dispatch_context(padded)
        for change in ({"original_sha256": "0" * 64}, {"original_size": 5}):
            forged = copy.deepcopy(value)
            forged["context"]["references"][0]["reference"].update(change)
            forged["files"][0]["manifest"].update(change)
            with self.assertRaises(ValueError):
                protocol.native_dispatch_context(forged)

    def test_pdf_framing_does_not_enlarge_nonbinary_envelope_or_small_text_frames(self):
        value = context(b"%PDF-" + b"x" * 400_000)
        frame = protocol.encode_native_context(value)
        self.assertGreater(len(frame), protocol.MAX_FRAME)
        protocol.decode_native_context(frame[4:])
        with self.assertRaises(ValueError):
            protocol.decode_native_context(frame[4:] + b" " * protocol.MAX_FRAME)
        with self.assertRaises(ValueError):
            protocol.decode(frame[4:])
        with self.assertRaises(ValueError):
            protocol.pdf_envelope({"text": "x" * protocol.MAX_FRAME}, {"text": "x" * protocol.MAX_FRAME})
        forged = copy.deepcopy(value)
        forged["files"][0]["path"] = "/project/other.pdf"
        with self.assertRaises(ValueError):
            protocol.native_dispatch_context(forged)
        with self.assertRaises(ValueError):
            protocol.decode_native_context(b'{"kind":"native-inline-v1","kind":"native-inline-v1"}')
        maximum_base64 = 4 * ((protocol.NATIVE_PDF_BYTE_LIMIT - 1 + 2) // 3)
        self.assertLess(maximum_base64 + 2 * 416 + protocol.MAX_FRAME, protocol.MAX_PDF_FRAME)

    def test_native_model_declaration_and_prompt_parts_do_not_expand_planning_permissions(self):
        worker = product_worker()
        config = planning.generated_config(1, native_pdf=True)
        plain = planning.generated_config(1)
        self.assertEqual(config["permission"], plain["permission"])
        self.assertEqual(config["agent"], plain["agent"])
        self.assertEqual(config["provider"]["azure"]["models"]["synthetic-deployment"]["modalities"],
                         {"input": ["text", "pdf"], "output": ["text"]})
        value = context(history=True)
        body = worker.native_prompt_body(value)
        self.assertEqual(len(body["parts"]), 3)
        self.assertIn("Quoted prior discussion", body["parts"][0]["text"])
        self.assertIn("untrusted reference data", body["parts"][0]["text"])
        self.assertNotIn("base64", body["parts"][0]["text"])
        self.assertTrue(all(part["mime"] == "application/pdf" for part in body["parts"][1:]))
        self.assertNotEqual(body["parts"][1]["filename"], "reference.pdf")

    def test_all_416_occurrences_survive_prompt_and_responses_shape_validation(self):
        value = context()
        selected = value["context"]["references"][0]
        value["context"]["references"] = [selected] * 32
        for _ in range(12):
            value["context"]["history"].extend([
                {"role": "user", "text": "Prior", "references": [selected] * 32},
                {"role": "assistant", "text": "Prior answer"},
            ])
        manifest = protocol.native_occurrence_manifest(value["context"])
        url = value["files"][0]["url"]
        value["files"] = [dict(manifest=item, url=url) for item in manifest]
        body = product_worker().native_prompt_body(value)
        self.assertEqual(len(body["parts"]), 417)
        data = responses(value)
        self.assertEqual(validate(data, manifest), data)
        self.assertEqual(manifest[-1]["message_index"], 24)


class NativeRelayShapeTests(unittest.TestCase):
    def test_relay_and_shim_validate_exact_inline_pdf_shape_and_tool_followup(self):
        from imp024_protocol import fixture_definitions

        value = context(history=True)
        manifest = [item["manifest"] for item in value["files"]]
        data = responses(value)
        data["tools"] = fixture_definitions()
        data["input"].extend([
            dict(type="function_call", call_id="call_synthetic", name="read",
                 arguments=json.dumps({"filePath": "/project/PROJECT.md"})),
            dict(type="function_call_output", call_id="call_synthetic", output="# Draft\n"),
        ])
        self.assertEqual(validate(data, manifest), data)
        self.assertEqual(Shim.request_shape(json.dumps(data).encode(), manifest), data)
        data["input"][-2]["arguments"] = json.dumps({"filePath": "/project/upload.pdf"})
        with self.assertRaises(relay.Denied):
            validate(data, manifest)

    def test_remote_image_extra_fields_order_and_missing_files_are_denied(self):
        value = context(history=True)
        manifest = [item["manifest"] for item in value["files"]]
        for mutate in (lambda d: d["input"][0]["content"][1].update(file_id="provider-file"),
                       lambda d: d["input"][0]["content"][1].update(file_data="https://example.invalid/a.pdf"),
                       lambda d: d["input"][0]["content"][1].update(type="input_image"),
                       lambda d: d["input"][0]["content"][1].update(filename="/project/PROJECT.md"),
                       lambda d: d["input"][0].update(role="assistant"),
                       lambda d: d["input"][0]["content"].reverse(),
                       lambda d: d["input"][0]["content"].pop()):
            data = responses(value)
            mutate(data)
            with self.assertRaises(relay.Denied):
                validate(data, manifest)

    def test_large_pdf_body_only_enlarges_binary_slots_not_text_or_envelope(self):
        value = context(b"%PDF-" + b"x" * 400_000)
        manifest = [item["manifest"] for item in value["files"]]
        data = responses(value)
        validate(data, manifest)
        raw = json.dumps(data).encode()
        self.assertGreater(len(raw), protocol.MAX_FRAME)
        with self.assertRaises(relay.Denied):
            relay.validate("POST", relay.ROUTE, raw, planning=True, input_text_limit=protocol.MAX_CONTEXT)
        with self.assertRaises(relay.Denied):
            relay.validate("POST", relay.ROUTE, raw + b" " * protocol.MAX_FRAME, planning=True,
                           input_text_limit=protocol.MAX_CONTEXT, pdf_manifest=manifest)
        data["input"][0]["content"][0]["text"] = "x" * (protocol.MAX_CONTEXT + 1)
        with self.assertRaises(relay.Denied):
            validate(data, manifest)
        data = responses(value)
        data["input"][0]["content"] += [dict(type="input_text", text="x")] * 16
        with self.assertRaises(relay.Denied):
            validate(data, manifest)

    def test_eight_digit_content_length_is_pdf_only_and_still_bounded(self):
        for function in (relay.content_length, Shim.request_length):
            self.assertEqual(function("10000000", protocol.MAX_PDF_FRAME, pdf_mode=True), 10_000_000)
            self.assertEqual(function(str(protocol.MAX_PDF_FRAME), protocol.MAX_PDF_FRAME, pdf_mode=True),
                             protocol.MAX_PDF_FRAME)
            for length, maximum, mode in (("10000000", protocol.MAX_PDF_FRAME, False),
                                          (str(protocol.MAX_PDF_FRAME + 1), protocol.MAX_PDF_FRAME, True),
                                          ("000000001", protocol.MAX_PDF_FRAME, True),
                                          ("123", protocol.MAX_FRAME, True),
                                          ("+123", protocol.MAX_PDF_FRAME, True)):
                with self.assertRaises(ValueError):
                    function(length, maximum, pdf_mode=mode)
        body = b"{}"
        raw = b"POST " + relay.ROUTE.encode() + b" HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n" + body
        self.assertEqual(relay.read_request(io.BytesIO(raw)), ("POST", relay.ROUTE, body))


class NativeEchoTests(unittest.TestCase):
    def test_native_history_only_strips_exact_user_file_echoes(self):
        worker = product_worker()
        value = context(history=True)
        manifest = [item["manifest"] for item in value["files"]]
        history = [dict(info=dict(sessionID="ses_synthetic", role="user"), parts=[
            dict(type="text", text="Prior"), echo(value, 0), echo(value, 1)])]
        stripped = worker.strip_native_history(history, "ses_synthetic", manifest)
        self.assertEqual(stripped[0]["parts"], [dict(type="text", text="Prior")])
        self.assertEqual(len(history[0]["parts"]), 3)  # Never mutates the captured source.
        for mutate in (lambda h: h[0]["info"].update(role="assistant"),
                       lambda h: h[0]["parts"][1].update(source={"path": "/project/other.pdf"}),
                       lambda h: h[0]["parts"].append(dict(type="tool", state=dict(attachments=[echo(value)]))),
                       lambda h: h[0]["parts"].reverse(),
                       lambda h: h[0]["parts"].pop(),
                       lambda h: h[0]["parts"][0].update(text="x" * protocol.MAX_FRAME)):
            forged = copy.deepcopy(history)
            mutate(forged)
            with self.assertRaises(ValueError):
                worker.strip_native_history(forged, "ses_synthetic", manifest)

    def test_large_pdf_sse_echo_is_validated_discarded_and_stream_bounded(self):
        worker = product_worker()
        value = context(b"%PDF-" + b"x" * 400_000)
        manifest = [item["manifest"] for item in value["files"]]
        update = dict(id="evt_synthetic", type="message.part.updated", properties=dict(
            sessionID="ses_synthetic", part=echo(value), time=1761120000123))
        raw = b"data: " + json.dumps(update).encode() + b"\n\n"
        self.assertGreater(len(raw), protocol.MAX_FRAME)
        reader = worker.NativeEchoStream({"ses_synthetic"}, manifest)
        self.assertIsNone(reader.read(io.BytesIO(raw)))
        status = dict(type="session.status", properties=dict(sessionID="ses_synthetic", status=dict(type="idle")))
        self.assertEqual(reader.read(io.BytesIO(b"data: " + json.dumps(status).encode() + b"\n\n")), status)
        reader.bytes = protocol.MAX_PDF_FRAME
        with self.assertRaises(ValueError):
            reader.read(io.BytesIO(raw))
        padded_raw = raw[:-2] + b" " * protocol.MAX_FRAME + b"\n\n"
        with self.assertRaises(ValueError):
            worker.NativeEchoStream({"ses_synthetic"}, manifest).read(io.BytesIO(padded_raw))
        update["properties"]["part"]["url"] = "https://example.invalid/file.pdf"
        with self.assertRaises(ValueError):
            worker.native_event_projection(update, {"ses_synthetic"}, manifest)
        large_text = dict(type="message.part.updated", properties=dict(part=dict(
            type="text", sessionID="ses_synthetic", text="x" * protocol.MAX_FRAME)))
        with self.assertRaises(ValueError):
            worker.native_event_projection(large_text, {"ses_synthetic"}, manifest)

    def test_file_sse_rejects_unknown_metadata_and_mismatched_identity(self):
        worker = product_worker()
        value = context()
        manifest = [item["manifest"] for item in value["files"]]
        update = dict(id="evt_synthetic", type="message.part.updated", properties=dict(
            sessionID="ses_synthetic", part=echo(value), time=1761120000123.5))
        sessions = {"ses_synthetic", "ses_other"}
        self.assertIsNone(worker.native_event_projection(update, sessions, manifest))
        for mutate in (lambda e: e.update(extra="unknown"),
                       lambda e: e.update(id="x" * 129),
                       lambda e: e["properties"].update(extra="unknown"),
                       lambda e: e["properties"].update(sessionID="ses_other"),
                       lambda e: e["properties"]["part"].update(sessionID="ses_other"),
                       lambda e: e["properties"].update(sessionID="ses_foreign", part=dict(
                           e["properties"]["part"], sessionID="ses_foreign")),
                       lambda e: e["properties"]["part"].update(id="/project/other.pdf"),
                       lambda e: e["properties"]["part"].update(messageID=None),
                       lambda e: e["properties"]["part"].update(source={"path": "/project/other.pdf"}),
                       lambda e: e["properties"]["part"].update(
                           url=protocol.PDF_DATA_PREFIX + base64.b64encode(b"%PDF-tampered").decode())):
            forged = copy.deepcopy(update)
            mutate(forged)
            with self.subTest(event=forged), self.assertRaises(ValueError):
                worker.native_event_projection(forged, sessions, manifest)
        for invalid in (True, "1761120000123", {}, float("nan"), float("inf")):
            forged = copy.deepcopy(update)
            forged["properties"]["time"] = invalid
            with self.subTest(time=invalid), self.assertRaises(ValueError):
                worker.native_event_projection(forged, sessions, manifest)

    def test_product_reader_accepts_known_envelopes_without_queueing_binary(self):
        worker = product_worker()
        value = context()
        minimal = dict(type="message.part.updated", properties=dict(part=echo(value)))
        # Earlier file-part envelopes and current documented session/time metadata.
        updates = (minimal, dict(minimal, id="evt_earlier"),
                   dict(minimal, id="evt_current", properties=dict(
                       minimal["properties"], sessionID="ses_synthetic", time=1761120000123)))
        status = dict(type="session.status", properties=dict(
            sessionID="ses_synthetic", status=dict(type="idle")))
        for update in updates:
            with self.subTest(fields=set(update["properties"])):
                driver = worker.ProductDriver(1, "synthetic", native_context=value)
                driver.sessions.add("ses_synthetic")
                reader = object.__new__(worker.ProductEvents)
                reader.driver, reader.stopped, reader.queue, reader.bytes = (
                    driver, threading.Event(), queue.Queue(maxsize=16), 0)
                reader.response = io.BytesIO(b"".join(
                    b"data: " + json.dumps(event).encode() + b"\n\n" for event in (update, status)))
                reader.read()
                self.assertEqual(reader.queue.get_nowait(), status)
                self.assertEqual(reader.queue.get_nowait(), {
                    "type": "driver.stream.failed", "reason": "native_stream_invalid"})  # Controlled EOF.
                self.assertTrue(reader.queue.empty())


if __name__ == "__main__":
    unittest.main()
