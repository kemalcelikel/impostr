"""Raw intake regressions only: no parser, DB, channel, runtime or private inputs."""

import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from app.pdf_intake import IntakeError, filename_metadata, original_body
from app.pdf_protocol import MAX_ORIGINAL


class IntakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_decimal_cap_and_actual_overcap_without_clipping(self):
        async def chunks(extra=False):
            yield b"%PDF-"
            remaining = MAX_ORIGINAL - 5
            block = b"x" * 65536
            while remaining:
                count = min(len(block), remaining)
                yield block[:count]
                remaining -= count
            if extra:
                yield b"!"
                self.fail("Must stop at the first overcap chunk")

        data, digest = await original_body(chunks())
        self.assertEqual(len(data), 50_000_000)
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        del data
        with self.assertRaises(IntakeError) as caught:
            await original_body(chunks(extra=True))
        self.assertEqual(caught.exception.code, "limit")

    async def test_fragmented_envelope_spoof_empty_and_interrupted_body(self):
        async def chunks(parts):
            for part in parts:
                yield part

        data, digest = await original_body(chunks([b"%P", b"D", b"F-test", b""]))
        self.assertEqual(data, b"%PDF-test")
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        for parts in ([], [b""], [b"<script>not PDF</script>"]):
            with self.assertRaises(IntakeError):
                await original_body(chunks(parts))

        async def interrupted():
            yield b"%PDF-partial"
            raise ConnectionError("synthetic disconnect")

        with self.assertRaises(ConnectionError):
            await original_body(interrupted())
        # A failed upload cannot poison the next request or share its partial bytes.
        self.assertEqual((await original_body(chunks([b"%PDF-next"])))[0], b"%PDF-next")

    def test_filename_is_bounded_display_metadata_not_a_path_or_header(self):
        self.assertEqual(filename_metadata('Café "reference".PDF'), 'Café "reference".PDF')
        for value in (
            "../secret.pdf",
            "/tmp/a.pdf",
            "C:\\a.pdf",
            "a\r\nb.pdf",
            "x\x00.pdf",
            "\u202eabc.pdf",
            " x.pdf",
            "x.pdf ",
            "x.html",
            "界" * 100 + ".pdf",
        ):
            with self.subTest(value=value), self.assertRaises(IntakeError):
                filename_metadata(value)


if __name__ == "__main__":
    unittest.main()
