"""Test-only generated-ID scope. NEVER imported by normal app/config/startup.

No environment switch can grant synthetic mode to ordinary application accounts.
Reviewed disposable test entrypoints inject this exact in-process scope after
creating random test users on owned storage. Authorization remains mandatory.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import Project, User


def generated_scope(
    engine: Engine, user_ids: frozenset[uuid.UUID]
) -> Callable[[uuid.UUID, uuid.UUID], bool]:
    assert user_ids and len(user_ids) <= 4
    with Session(engine) as db:
        rows = list(db.scalars(select(User)))
        assert {row.id for row in rows} == user_ids
        assert all(
            row.role == "user" and row.username.startswith(("model-check-", "joined-"))
            for row in rows
        )
    return captured_scope(engine, user_ids)


def captured_scope(
    engine: Engine, user_ids: frozenset[uuid.UUID]
) -> Callable[[uuid.UUID, uuid.UUID], bool]:
    """Joined driver already generated IDs before launch; DB outage can boot API.

    Every actual scope check revalidates the actor/owner rows on authoritative DB;
    unknown IDs or unavailable storage cannot authorize dispatch.
    """
    assert user_ids and len(user_ids) <= 4

    def allows(project_id: uuid.UUID, actor_id: uuid.UUID) -> bool:
        if actor_id not in user_ids:
            return False
        with Session(engine) as db:
            project = db.get(Project, project_id)
            if project is None or project.owner_user_id not in user_ids:
                return False
            users = [db.get(User, uid) for uid in {actor_id, project.owner_user_id}]
            return all(
                user is not None
                and user.role == "user"
                and user.username.startswith(("model-check-", "joined-"))
                for user in users
            )

    return allows
