"""Disposable generated-Member synthetic API entrypoint, not normal application.

Requires explicit three fixture flags, exactly one previously generated Member on
owned storage, and captures its random ID BEFORE serving. Normal app has no switch
to activate this scope. No alternate auth, provider input or network ingress.
"""

import os

import uvicorn
from imp005_synthetic_scope import generated_scope
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.chat_dispatch import Dispatcher
from app.database import get_database_engine
from app.models import User


def main_scoped():
    assert os.geteuid() == 10001
    assert all(
        os.environ.get(name) == "1"
        for name in (
            "IMPOSTR_TEST_POSTGRES",
            "IMPOSTR_TEST_CHAT_CHANNEL",
            "IMPOSTR_TEST_CHAT_JOINED",
        )
    )
    engine = get_database_engine()
    with Session(engine) as db:
        users = frozenset(db.scalars(select(User.id)))
    assert len(users) == 1
    scope = generated_scope(engine, users)

    class ScopedDispatcher(Dispatcher):
        def __init__(self, engine, broker):
            super().__init__(engine, broker, test_scope=scope)

    main.Dispatcher = ScopedDispatcher
    uvicorn.run(
        main.create_app(), host="0.0.0.0", port=8000, log_level="critical", access_log=False
    )


if __name__ == "__main__":
    try:
        main_scoped()
    except Exception:
        raise SystemExit(1) from None
