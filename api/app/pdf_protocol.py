"""Standalone IMP-017 wire/data contract; no parser, DB, or provider dependencies.

One connection = one metadata frame, accepted frame, raw bytes through write EOF,
one result frame. No caller-supplied paths, names, options, IDs, or credentials.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import struct
import time
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any, Protocol

API_UID = 10001
EXTRACTOR_UID = 10002
SOCKET_PATH = "/run/impostr-pdf/channel.sock"
MAX_ORIGINAL = 50_000_000
MAX_TEXT = 128 * 1024
MAX_PAGES = 500
JOB_SECONDS = 30
MAX_CONTROL = 1024
MAX_REPLY = 800 * 1024  # Worst-case JSON escaping of the UTF-8 text + coverage.
POLICY = "imp017-text-v1"
LABEL = "Text layer only; images and diagrams were not read."
ERRORS = frozenset(
    {"busy", "invalid", "encrypted", "active_content", "no_text", "limit", "timeout", "unavailable"}
)
HEX = re.compile(r"[0-9a-f]{64}\Z")


class PDFError(Exception):
    """Fixed public reason only; never forward parser diagnostics or exceptions."""

    def __init__(self, code: str = "invalid") -> None:
        self.code = code if code in ERRORS else "invalid"
        super().__init__(self.code)


def require(condition: object, code: str = "invalid") -> None:
    if not condition:
        raise PDFError(code)


def sha256(value: object) -> bool:
    return isinstance(value, str) and HEX.fullmatch(value) is not None


def metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"v", "size", "sha256"}:
        raise PDFError()
    require(type(value["v"]) is int and value["v"] == 1)
    require(type(value["size"]) is int and 0 < value["size"] <= MAX_ORIGINAL, "limit")
    require(sha256(value["sha256"]))
    return value


def usable(text: str) -> bool:
    return any(unicodedata.category(char)[0] in "LN" for char in text)


def coverage(text: Any, pages: Any) -> list[int]:
    require(isinstance(text, str))
    try:
        require(len(text.encode("utf-8")) <= MAX_TEXT, "limit")
    except UnicodeError as exc:
        raise PDFError() from exc
    require(type(pages) is int and 0 < pages <= MAX_PAGES, "limit")
    require(text.endswith("\f") and text.count("\f") == pages)
    require(not any(unicodedata.category(c) == "Cc" and c not in "\n\t\f" for c in text))
    parts = text.split("\f")[:-1]
    missing = [number for number, part in enumerate(parts, 1) if not usable(part)]
    require(len(missing) < pages, "no_text")
    return missing


def result(value: Any, original: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PDFError()
    require(type(value.get("v")) is int and value["v"] == 1)
    if value.get("status") == "rejected":
        require(
            set(value) == {"v", "status", "code"}
            and isinstance(value["code"], str)
            and value["code"] in ERRORS
        )
        return value
    require(value.get("status") == "ready")
    require(
        set(value)
        == {
            "v", "status", "size", "sha256", "text", "text_sha256",
            "pages", "missing_pages", "label", "provenance",
        }
    )
    metadata({"v": 1, "size": value["size"], "sha256": value["sha256"]})
    require(value["missing_pages"] == coverage(value["text"], value["pages"]))
    require(
        isinstance(value["missing_pages"], list)
        and all(type(page) is int for page in value["missing_pages"])
    )
    require(value["text_sha256"] == hashlib.sha256(value["text"].encode()).hexdigest())
    require(value["label"] == LABEL)
    provenance = value["provenance"]
    require(
        isinstance(provenance, dict)
        and set(provenance) == {"policy", "qpdf", "pdftotext", "build_sha256"}
    )
    require(
        provenance["policy"] == POLICY
        and provenance["qpdf"] == "11.3.0"
        and provenance["pdftotext"] == "22.12.0"
        and sha256(provenance["build_sha256"])
    )
    if original is not None:
        require(value["size"] == original["size"] and value["sha256"] == original["sha256"])
    return value


def rejected(code: str) -> dict[str, Any]:
    require(code in ERRORS)
    return {"v": 1, "status": "rejected", "code": code}


def encode(value: dict[str, Any], limit: int = MAX_REPLY) -> bytes:
    data = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
    require(0 < len(data) <= limit, "limit")
    return struct.pack("!I", len(data)) + data


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    require(seconds > 0, "timeout")
    return seconds


class Connection(Protocol):
    def recv(self, size: int) -> bytes: ...

    def settimeout(self, seconds: float) -> None: ...


def exact(connection: Connection, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        connection.settimeout(remaining(deadline))
        block = connection.recv(min(65536, size - len(data)))
        require(block)
        data.extend(block)
    return bytes(data)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        require(key not in value)
        value[key] = item
    return value


def receive(connection: Connection, deadline: float, limit: int = MAX_REPLY) -> dict[str, Any]:
    (size,) = struct.unpack("!I", exact(connection, 4, deadline))
    require(0 < size <= limit, "limit")
    data = exact(connection, size, deadline)
    # Wire schemas have at most four levels. Bound nesting BEFORE json.loads.
    depth = 0
    quoted = escaped = False
    for char in data:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (123, 91):
            depth += 1
            require(depth <= 4, "limit")
        elif char in (125, 93):
            depth -= 1
            require(depth >= 0)
    try:

        def reject_constant(_: str) -> None:
            raise PDFError()

        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PDFError() from exc
    if not isinstance(value, dict):
        raise PDFError()
    return value


def peer(connection: socket.socket, uid: int) -> None:
    _, actual_uid, gid = struct.unpack(
        "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    )
    require(actual_uid == uid and gid == uid, "unavailable")


def counted(chunks: Iterable[bytes], sink: Callable[[bytes], object], expected: dict[str, Any]) -> None:
    """Count actual bytes independently of declared size; never clip or over-write."""
    metadata(expected)
    size = 0
    digest = hashlib.sha256()
    for block in chunks:
        require(isinstance(block, bytes))
        size += len(block)
        require(size <= MAX_ORIGINAL and size <= expected["size"], "limit")
        digest.update(block)
        sink(block)
    require(size == expected["size"] and digest.hexdigest() == expected["sha256"])
