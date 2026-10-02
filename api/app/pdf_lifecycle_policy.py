"""Bounded durable PDF scheduling policy; no parser, runtime or DB dependencies."""

from app.pdf_protocol import JOB_SECONDS

MAX_ATTEMPTS = 3
LEASE_SECONDS = JOB_SECONDS + 15
TRANSIENT = frozenset({"busy", "unavailable"})
# Actual phase-one verified build record, not a fabricated derivative fingerprint.
VERIFIED_BUILD_SHA256 = "b976249ca1a5aea47689ac9210b15611b6b9c88ab9c337f766e5e1569faa4192"


def retry_delay(code: str, attempt: int) -> int | None:
    if code in TRANSIENT and 0 < attempt < MAX_ATTEMPTS:
        return 5 if attempt == 1 else 15
    return None
