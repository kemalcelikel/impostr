"""Small helpers for recording credential and private-data access events."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record_audit(
    db: Session,
    *,
    action: str,
    actor_user_id: uuid.UUID | None,
    actor_kind: str = "user",
    target_user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            action=action,
            target_user_id=target_user_id,
            project_id=project_id,
            details=details,
        )
    )
