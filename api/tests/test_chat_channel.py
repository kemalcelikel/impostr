"""New boundary scenario: coordinator runs ONLY after independent review.

Requires the synthetic Compose overlay and real API UID10001/host UID1000 broker.
No owner account, private config or live model is accessed.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from app.chat_broker import UnixBroker
from app.chat_protocol import MAX_TEXT, ChannelError, digest

pytestmark = pytest.mark.skipif(
    os.environ.get("IMPOSTR_TEST_CHAT_CHANNEL") != "1",
    reason="requires reviewed coordinator-owned UID channel fixture",
)


@pytest.mark.parametrize(
    ("content", "prompt", "history"),
    [
        ("# Synthetic project\n", "Prepare only a synthetic planning proposal", []),
        ("# Synthetic project\r\nExact CRLF draft\r\n", "Synthetic CRLF-only plan", []),
        (
            "# Synthetic project\n",
            "Continue the synthetic LF-only plan",
            [
                {"role": "user", "text": "x" * MAX_TEXT},
                {"role": "assistant", "text": "a" * MAX_TEXT + "\nRecorded turn state: completed"},
            ],
        ),
        (
            "# Synthetic project\r\nExact CRLF draft\r\n",
            "Continue only the synthetic plan",
            [
                {"role": "user", "text": "x" * MAX_TEXT},
                {"role": "assistant", "text": "a" * MAX_TEXT + "\nRecorded turn state: completed"},
            ],
        ),
    ],
)
def test_actual_uid_channel_native_question_permission_and_proposal(content, prompt, history):
    assert os.geteuid() == 10001
    broker = UnixBroker()
    hello = broker.call({"op": "hello"})
    assert hello["mode"] == "synthetic"
    command = {
        "epoch": hello["epoch"],
        "project_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "turn_id": str(uuid.uuid4()),
    }
    documents = {
        name: {
            "revision_id": str(uuid.uuid4()),
            "content": content,
            "sha256": digest(content),
        }
        for name in ("PROJECT.md", "AGENTS.md", "BACKLOG.md")
    }
    payload = {
        "prompt": prompt,
        "history": history,
        "documents": documents,
    }
    cursor = 0
    observed = []
    try:
        broker.call(dict(command, op="start", payload=payload))
        with pytest.raises(ChannelError):
            broker.call(dict(command, op="start", payload=payload))
        with pytest.raises(ChannelError):
            broker.call(dict(command, op="poll", after=0, epoch=str(uuid.uuid4())))
        with pytest.raises(ChannelError):
            broker.call(dict(command, op="poll", after=0, project_id=str(uuid.uuid4())))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            page = broker.call(dict(command, op="poll", after=cursor))
            assert page["known"] is True
            for envelope in page["events"]:
                assert envelope["sequence"] == cursor + 1
                cursor += 1
                value = envelope["event"]
                observed.append(value["type"])
                if value["type"] in ("question", "permission"):
                    data = value["data"]
                    answer = (
                        {"answers": [["Yes"]]} if value["type"] == "question" else {"reply": "once"}
                    )
                    broker.call(dict(command, op="reply", interaction_id=data["id"], answer=answer))
                elif value["type"] == "completed":
                    assert {"started", "question", "permission", "delta", "completed"} <= set(
                        observed
                    )
                    proposals = value["data"]["proposals"]
                    assert len(proposals) == 1 and proposals[0]["filename"] == "PROJECT.md"
                    assert proposals[0]["approval"] is False
                    assert proposals[0]["base_sha256"] == documents["PROJECT.md"]["sha256"]
                    return
                else:
                    assert value["type"] not in ("failed", "cancelled")
            time.sleep(0.05)
        pytest.fail("Synthetic native turn did not complete within its bound")
    finally:
        assert broker.call(dict(command, op="abort"))["stopped"] is True


def test_abort_unknown_blocks_a_late_first_dispatch():
    broker = UnixBroker()
    epoch = broker.call({"op": "hello"})["epoch"]
    command = {
        "epoch": epoch,
        "project_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "turn_id": str(uuid.uuid4()),
    }
    assert broker.call(dict(command, op="abort"))["stopped"] is True
    documents = {
        name: {
            "revision_id": str(uuid.uuid4()),
            "content": "# Synthetic\n",
            "sha256": digest("# Synthetic\n"),
        }
        for name in ("PROJECT.md", "AGENTS.md", "BACKLOG.md")
    }
    with pytest.raises(ChannelError):
        broker.call(
            dict(
                command,
                op="start",
                payload={"prompt": "Never dispatch", "history": [], "documents": documents},
            )
        )
