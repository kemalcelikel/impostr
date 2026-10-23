"""Coordinator-owned generated-Member API with both PDF and chat workers enabled.

This is only mounted by the reviewed IMP-018 verifier. It retains the ordinary
session/project checks and scopes synthetic dispatch to the generated Member; it
does not introduce an application setting or public synthetic-auth path.
"""

from __future__ import annotations

import os
import time

import uvicorn
from imp005_synthetic_scope import generated_scope
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.chat_broker import UnixBroker
from app.chat_dispatch import Dispatcher
from app.chat_protocol import ChannelError
from app.database import get_database_engine
from app.models import User


def serve() -> None:
    assert os.geteuid() == 10001
    assert all(
        os.environ.get(name) == "1"
        for name in (
            "IMPOSTR_TEST_POSTGRES",
            "IMPOSTR_TEST_CHAT_CHANNEL",
            "IMPOSTR_TEST_CHAT_JOINED",
            "IMPOSTR_TEST_PDF_LIFECYCLE",
            "IMPOSTR_CHAT_ENABLED",
            "IMPOSTR_PDF_ENABLED",
        )
    )
    engine = get_database_engine()
    with Session(engine) as db:
        user_ids = frozenset(db.scalars(select(User.id)))
    scope = generated_scope(engine, user_ids)

    class LostStartAckBroker(UnixBroker):
        """Drop one fixed fixture ACK only after the real broker accepted start."""

        def call(self, value):
            result = super().call(value)
            if (
                value.get("op") == "start"
                and value.get("payload", {}).get("prompt") == "SYNTHETIC PDF LOST START ACK"
            ):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    poll = {
                        key: value[key]
                        for key in ("epoch", "project_id", "conversation_id", "turn_id")
                    }
                    poll.update(op="poll", after=0)
                    observed = super().call(poll)
                    if observed.get("receipts"):
                        break
                    time.sleep(0.05)
                else:
                    raise ChannelError()
                raise ChannelError()
            return result

    class ScopedDispatcher(Dispatcher):
        def __init__(self, engine, broker):
            super().__init__(engine, broker, test_scope=scope)

    main.UnixBroker = LostStartAckBroker
    main.Dispatcher = ScopedDispatcher
    uvicorn.run(
        main.create_app(), host="0.0.0.0", port=8000, log_level="critical", access_log=False
    )


if __name__ == "__main__":
    try:
        serve()
    except Exception:
        raise SystemExit(1) from None
