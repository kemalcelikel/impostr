"""Dependency-free raw envelope checks, not PDF structural parsing."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import AsyncIterable

from app.chat_protocol import NATIVE_PDF_BYTE_LIMIT


class IntakeError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def filename_metadata(value: str) -> str:
    # A display label only, never used as a path or reflected in download headers.
    value = unicodedata.normalize("NFC", value)
    if (
        not 1 <= len(value) <= 180
        or len(value.encode("utf-8")) > 255
        or value != value.strip()
        or any(c in "/\\:" or unicodedata.category(c).startswith("C") for c in value)
        or not value.lower().endswith(".pdf")
    ):
        raise IntakeError("filename")
    return value


async def original_body(chunks: AsyncIterable[bytes]) -> tuple[bytes, str]:
    """Count actual bytes; neither trusts nor requires Content-Length. No disk spool."""
    data = bytearray()
    digest = hashlib.sha256()
    try:
        async for chunk in chunks:
            if len(data) + len(chunk) >= NATIVE_PDF_BYTE_LIMIT:
                raise IntakeError("limit")
            data.extend(chunk)
            digest.update(chunk)
        if not data or not data.startswith(b"%PDF-"):
            # Envelope only; provider validity/acceptance is not claimed locally.
            raise IntakeError("invalid")
        return bytes(data), digest.hexdigest()
    finally:
        # Also discard partial bytes on overcap, disconnect or cancellation.
        data.clear()
