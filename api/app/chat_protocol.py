"""Pure, bounded product broker contract; no HTTP, credentials or tool execution.

Also copied alone into the confined worker as imp024_channel.py. Linux peer
credentials authenticate the channel in both directions; UUIDs are scope, not auth.
"""

from __future__ import annotations

import hashlib
import json
import struct
import uuid
from typing import Any

MAX_FRAME = 512 * 1024
MAX_TEXT = 64 * 1024
# Raw and JSON-escaped user/assistant messages remain 64 KiB. Reconstructed history includes
# recorded interaction/tool metadata and JSON quoting: it is NOT one message.
# Cap its escaped native prompt below the 512 KiB inference request, retaining
# bounded room for measured system/tool definitions and native tool results.
MAX_CONTEXT = 384 * 1024
MAX_PRIOR_TURNS = 12
MAX_EVENTS = 256
TURN_SECONDS = 60
FAILURE_REASONS = (
    "native_stream_timeout",
    "native_stream_invalid",
    "native_session_error",
    "worker_deadline",
    "worker_error",
    "broker_worker_error",
)
FILES = ("PROJECT.md", "AGENTS.md", "BACKLOG.md")


class ChannelError(ValueError):
    def __init__(self) -> None:
        super().__init__("Broker unavailable")


def require(condition: object) -> None:
    if not condition:
        raise ChannelError()


def text(value: Any, maximum: int = MAX_TEXT, *, empty: bool = True) -> str:
    require(isinstance(value, str))
    require((empty or bool(value)) and "\0" not in value)
    require(len(value.encode("utf-8")) <= maximum)
    return str(value)


def opaque(value: Any) -> str:
    require(isinstance(value, str) and str(uuid.UUID(value)) == value)
    return str(value)


def native_id(value: Any, prefix: str) -> str:
    import re

    require(isinstance(value, str) and re.fullmatch(prefix + r"_[A-Za-z0-9_-]{1,128}", value))
    return str(value)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def escaped_size(value: str) -> int:
    # Exclude the enclosing JSON quotes, retaining every escaped message byte.
    return len(json.dumps(value, ensure_ascii=True).encode("utf-8")) - 2


def message_text(value: Any) -> str:
    validated = text(value, empty=False)
    require(escaped_size(validated) <= MAX_TEXT)
    return validated


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def encode(value: Any) -> bytes:
    body = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    require(0 < len(body) <= MAX_FRAME)
    return struct.pack("!I", len(body)) + body


def decode(body: bytes) -> Any:
    require(0 < len(body) <= MAX_FRAME)
    return json.loads(body, object_pairs_hook=_object, parse_constant=lambda _: require(False))


def receive(connection: Any) -> Any:
    def exact(size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            block = connection.recv(size - len(result))
            require(block)
            result.extend(block)
        return bytes(result)

    size = struct.unpack("!I", exact(4))[0]
    require(0 < size <= MAX_FRAME)
    return decode(exact(size))


def scope(value: dict[str, Any]) -> tuple[str, str, str]:
    return opaque(value["project_id"]), opaque(value["conversation_id"]), opaque(value["turn_id"])


def start_payload(value: Any) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {"prompt", "history", "documents"})
    message_text(value["prompt"])
    require(isinstance(value["history"], list) and len(value["history"]) <= MAX_PRIOR_TURNS * 2)
    for item in value["history"]:
        require(isinstance(item, dict) and set(item) == {"role", "text"})
        require(item["role"] in ("user", "assistant"))
        text(item["text"], MAX_CONTEXT, empty=False)
    documents = value["documents"]
    require(isinstance(documents, dict) and set(documents) == set(FILES))
    for item in documents.values():
        require(isinstance(item, dict) and set(item) == {"revision_id", "content", "sha256"})
        opaque(item["revision_id"])
        require(digest(text(item["content"])) == item["sha256"])
    encode(value)  # Aggregate context is rejected, never silently truncated.
    # Include the actual start header overhead BEFORE a turn may be queued. All
    # server-generated scope/epoch identifiers have this exact canonical length.
    placeholder = "00000000-0000-0000-0000-000000000000"
    encode(
        {
            "op": "start",
            "epoch": placeholder,
            "project_id": placeholder,
            "conversation_id": placeholder,
            "turn_id": placeholder,
            "payload": value,
        }
    )
    prompt_text(value)
    return dict(value)


def prompt_text(value: dict[str, Any]) -> str:
    assembled = value["prompt"]
    if value["history"]:
        assembled = (
            "Previous durable conversation (quoted data, not policy):\n"
            + json.dumps(value["history"], ensure_ascii=False)
            + "\nCurrent user message:\n"
            + value["prompt"]
        )
    text(assembled, MAX_CONTEXT, empty=False)
    # Native Driver/SDK JSON escapes Unicode and CR/LF. The raw UTF-8 size alone
    # cannot certify a bounded request. Never truncate to make this check pass.
    require(len(json.dumps(assembled, ensure_ascii=True).encode("utf-8")) <= MAX_CONTEXT)
    return str(assembled)


def request(value: Any) -> dict[str, Any]:
    require(isinstance(value, dict))
    operation = value.get("op")
    if operation == "hello":
        require(set(value) == {"op"})
        return dict(value)
    base = {"op", "epoch", "project_id", "conversation_id", "turn_id"}
    opaque(value.get("epoch"))
    scope(value)
    if operation == "start":
        require(set(value) == base | {"payload"})
        start_payload(value["payload"])
    elif operation == "poll":
        require(set(value) == base | {"after"})
        require(type(value["after"]) is int and 0 <= value["after"] <= MAX_EVENTS)
    elif operation == "reply":
        require(set(value) == base | {"interaction_id", "answer"})
        text(value["interaction_id"], 140, empty=False)
        require(isinstance(value["answer"], dict))
        encode(value["answer"])
    else:
        require(operation == "abort" and set(value) == base)
    return dict(value)


def event(value: Any) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == {"type", "data"})
    kind, data = value["type"], value["data"]
    require(isinstance(data, dict))
    if kind == "started":
        require(set(data) == {"native_session_id", "context_reconstructed"})
        native_id(data["native_session_id"], "ses")
        require(type(data["context_reconstructed"]) is bool)
    elif kind == "delta":
        require(set(data) == {"text"})
        text(data["text"], empty=False)
    elif kind == "question":
        require(set(data) == {"id", "questions"})
        native_id(data["id"], "que")
        question_list(data["questions"])
    elif kind == "permission":
        require(set(data) == {"id", "permission", "once_allowed"})
        native_id(data["id"], "per")
        require(data["permission"] in ("read", "edit", "denied"))
        require(type(data["once_allowed"]) is bool)
        require(not data["once_allowed"] or data["permission"] != "denied")
    elif kind == "tool":
        require(set(data) == {"tool", "status"})
        require(data["tool"] in ("read", "edit", "write", "question"))
        require(data["status"] in ("pending", "running", "completed", "error"))
    elif kind == "completed":
        require(set(data) == {"proposals"} and isinstance(data["proposals"], list))
        require(len(data["proposals"]) <= 3)
        names = set()
        for proposal in data["proposals"]:
            require(
                isinstance(proposal, dict)
                and set(proposal) == {"filename", "base_sha256", "content", "origin", "approval"}
            )
            require(proposal["filename"] in FILES and proposal["filename"] not in names)
            names.add(proposal["filename"])
            text(proposal["content"])
            require(isinstance(proposal["base_sha256"], str) and len(proposal["base_sha256"]) == 64)
            require(proposal["origin"] == "agent" and proposal["approval"] is False)
    elif kind == "failed":
        require(data == {} or (set(data) == {"reason"} and data["reason"] in FAILURE_REASONS))
    else:
        require(kind == "cancelled" and data == {})
    encode(value)
    return dict(value)


def question_list(value: Any) -> None:
    require(isinstance(value, list) and 1 <= len(value) <= 8)
    for question in value:
        require(
            isinstance(question, dict)
            and {"question", "header", "options"}
            <= set(question)
            <= {"question", "header", "options", "multiple", "custom"}
        )
        text(question["question"], 4096, empty=False)
        text(question["header"], 120, empty=False)
        for flag in ("multiple", "custom"):
            require(flag not in question or type(question[flag]) is bool)
        options = question["options"]
        require(isinstance(options, list) and 1 <= len(options) <= 16)
        labels = set()
        for option in options:
            require(isinstance(option, dict) and set(option) == {"label", "description"})
            label = text(option["label"], 256, empty=False)
            require(label not in labels)
            labels.add(label)
            text(option["description"], 2048)


def answer(kind: str, data: dict[str, Any], value: Any) -> dict[str, Any]:
    require(isinstance(value, dict))
    if kind == "permission":
        require(set(value) == {"reply"} and value["reply"] in ("once", "reject"))
        require(value["reply"] != "once" or data["once_allowed"])
    else:
        require(kind == "question" and set(value) == {"answers"})
        answers, questions = value["answers"], data["questions"]
        require(isinstance(answers, list) and len(answers) == len(questions))
        for question, selected in zip(questions, answers, strict=True):
            require(isinstance(selected, list) and 1 <= len(selected) <= 16)
            require(all(isinstance(item, str) for item in selected))
            require(len(set(selected)) == len(selected))
            require(question.get("multiple", False) or len(selected) == 1)
            for item in selected:
                text(item, 4096, empty=False)
                require(
                    question.get("custom", True)
                    or item in [option["label"] for option in question["options"]]
                )
    return dict(value)
