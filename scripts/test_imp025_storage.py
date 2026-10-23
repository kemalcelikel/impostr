"""Pure native storage/admission contract; no parser, DB, worker or relay execution."""

import asyncio
import copy
import hashlib
import json
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from app import chat_protocol as protocol
from app.pdf_intake import IntakeError, original_body


def reference(size=100):
    return {
        "kind": protocol.NATIVE_PDF_REFERENCE,
        "attachment_id": str(uuid.uuid4()),
        "filename": "reference.pdf",
        "original_sha256": "a" * 64,
        "original_size": size,
    }


def payload(references):
    return {
        "prompt": "Use selected originals",
        "history": [],
        "references": references,
        "documents": {
            name: {
                "revision_id": str(uuid.uuid4()),
                "content": "# Draft\n",
                "sha256": protocol.digest("# Draft\n"),
            }
            for name in protocol.FILES
        },
    }


def entry(selected, availability="available"):
    return {"reference": selected, "availability": availability}


class NativeStorageContractTests(unittest.TestCase):
    def test_capture_is_versioned_and_binary_free_but_not_a_transport_payload(self):
        selected = reference()
        capture = payload([selected, selected])
        self.assertEqual(protocol.captured_payload(capture), capture)
        resolved = payload([entry(selected), entry(selected)])
        self.assertEqual(protocol.reference_context(resolved), resolved)
        for key, value in (("data", "JVBERi0="), ("text", "PDF text"), ("path", "/upload.pdf")):
            forged = copy.deepcopy(capture)
            forged["references"][0][key] = value
            with self.assertRaises(protocol.ChannelError):
                protocol.captured_payload(forged)
        with self.assertRaises(protocol.ChannelError):
            protocol.broker_start_payload(resolved)  # Storage must not masquerade as sent bytes.

    def test_strict_per_file_limit_and_actual_aggregate_history_occurrences(self):
        protocol.original_reference(reference(49_999_999))
        with self.assertRaises(protocol.ChannelError):
            protocol.original_reference(reference(50_000_000))
        selected = reference(24_999_999)
        value = payload([entry(selected)])
        value["history"] = [{"role": "user", "text": "Prior", "references": [entry(selected)]}]
        protocol.reference_context(value)  # Same ID still consumes two occurrences.
        selected["original_size"] = 25_000_000
        with self.assertRaises(protocol.ChannelError):
            protocol.reference_context(value)  # Exact aggregate limit rejects, not <=.

    def test_occurrence_count_covers_32_selections_in_each_of_13_turns(self):
        selected = reference()
        value = payload([entry(selected)] * 32)
        value["history"] = [
            {"role": "user", "text": "Prior", "references": [entry(selected)] * 32}
            for _ in range(12)
        ]
        protocol.reference_context(value)
        value["history"].append({"role": "user", "text": "Extra", "references": [entry(selected)]})
        with self.assertRaises(protocol.ChannelError):
            protocol.reference_context(value)

    def test_unavailable_history_stays_explicit_and_is_not_an_included_original(self):
        missing = entry(reference(49_999_999), "unavailable")
        value = payload([entry(reference(49_999_999))])
        value["history"] = [{"role": "user", "text": "Prior", "references": [missing]}]
        before = copy.deepcopy(value)
        self.assertEqual(protocol.reference_context(value), before)
        self.assertEqual(value, before)
        value["references"] = [missing]
        with self.assertRaises(protocol.ChannelError):
            protocol.reference_context(value)

    def test_small_text_control_bounds_are_not_expanded_for_native_metadata(self):
        with self.assertRaises(protocol.ChannelError):
            protocol.encode({"oversized": "x" * protocol.MAX_FRAME})
        value = payload([entry(reference())])
        value["prompt"] = "x" * (protocol.MAX_TEXT + 1)
        with self.assertRaises(protocol.ChannelError):
            protocol.reference_context(value)

    def test_legacy_capture_keeps_derivative_semantics_and_inclusive_historical_size(self):
        from test_imp018_references import entry as legacy_entry

        legacy = legacy_entry()["reference"]
        legacy["original_size"] = 50_000_000
        capture = payload([legacy])
        before = json.dumps(capture, sort_keys=True)
        protocol.captured_payload(capture)
        self.assertEqual(json.dumps(capture, sort_keys=True), before)
        self.assertNotIn("kind", legacy)
        with self.assertRaises(protocol.ChannelError):
            protocol.original_reference(legacy)
        resumed = payload([])
        resumed["history"] = [
            {"role": "user", "text": "Prior", "references": [entry(legacy, "unavailable")]}
        ]
        protocol.reference_context(resumed)

    def test_actual_intake_boundary_and_envelope_without_local_parsing(self):
        async def chunks(size):
            yield b"%PDF-"
            remaining = size - 5
            while remaining:
                block = b"x" * min(65536, remaining)
                remaining -= len(block)
                yield block

        content, digest = asyncio.run(original_body(chunks(49_999_999)))
        self.assertEqual(len(content), 49_999_999)
        self.assertEqual(hashlib.sha256(content).hexdigest(), digest)
        del content
        with self.assertRaises(IntakeError) as failure:
            asyncio.run(original_body(chunks(50_000_000)))
        self.assertEqual(failure.exception.code, "limit")

        async def invalid():
            yield b"not a PDF"

        with self.assertRaises(IntakeError) as failure:
            asyncio.run(original_body(invalid()))
        self.assertEqual(failure.exception.code, "invalid")


if __name__ == "__main__":
    unittest.main()
