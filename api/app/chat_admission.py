"""Normal broker-mode admission; synthetic exceptions are in-process test scope only."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from app.chat_protocol import opaque, require

TestScope = Callable[[uuid.UUID, uuid.UUID], bool]


def admission(
    hello: dict[str, Any],
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
    test_scope: TestScope | None = None,
    *,
    new: bool = True,
) -> uuid.UUID:
    epoch = uuid.UUID(opaque(hello.get("epoch")))
    require(
        hello.get("mode") == "planning"
        or (
            hello.get("mode") in ("synthetic", "operator")
            and test_scope is not None
            and test_scope(project_id, actor_id)
        )
    )
    if new:
        require(hello.get("admitting") is True)
    return epoch
