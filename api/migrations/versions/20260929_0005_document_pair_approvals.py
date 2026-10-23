"""Add immutable approvals for the current PROJECT.md/AGENTS.md revision pair.

Revision ID: 20260929_0005
Revises: 20260925_0004
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0005"
down_revision: str | None = "20260925_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing drafts are deliberately not backfilled: an approval is an explicit
    # human action, never an inference from historical document content.
    op.create_table(
        "project_document_pair_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("project_revision_id", sa.Uuid(), nullable=False),
        sa.Column("agents_revision_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["project_revision_id"],
            ["project_document_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agents_revision_id"],
            ["project_document_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "project_revision_id",
            "agents_revision_id",
            name="uq_project_pair_approval_revisions",
        ),
    )
    op.create_index(
        "ix_project_pair_approvals_project_created",
        "project_document_pair_approvals",
        ["project_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_pair_approvals_project_created",
        table_name="project_document_pair_approvals",
    )
    op.drop_table("project_document_pair_approvals")
