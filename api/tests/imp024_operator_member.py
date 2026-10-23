"""Pre-secret disposable helper only: offline generated Member seed, no auth bypass.

No provider input. Output consumed privately by the credential-free helper, never
forwarded to the terminal/agents. Owned disposable DB/stack cleanup removes it.
"""

import json
import os
import secrets

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import database_url_from_environment
from app.models import User
from app.passwords import hash_password


def main():
    assert os.geteuid() == 10001
    assert all(
        os.environ.get(name) == "1"
        for name in (
            "IMPOSTR_TEST_POSTGRES",
            "IMPOSTR_TEST_CHAT_CHANNEL",
            "IMPOSTR_TEST_CHAT_JOINED",
        )
    )
    engine = create_engine(database_url_from_environment(), hide_parameters=True)
    try:
        with Session(engine) as db, db.begin():
            assert db.scalar(select(User.id)) is None
            username = "model-check-" + secrets.token_hex(10)
            password = secrets.token_urlsafe(32)
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role="user",
                    is_active=True,
                )
            )
        print(json.dumps({"username": username, "password": password}), flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(1) from None
