"""Establish the initial Impostr Alembic revision without domain tables yet.

Revision ID: 20260925_0001
Revises:
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "20260925_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record the schema baseline; application tables arrive with later slices."""


def downgrade() -> None:
    """Return to the pre-baseline state."""
    pass
