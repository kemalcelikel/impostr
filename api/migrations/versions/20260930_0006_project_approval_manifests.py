"""Add immutable manifests for the approved three-document snapshot.

Revision ID: 20260930_0006
Revises: 20260929_0005
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0006"
down_revision: str | None = "20260929_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The composite reference binds the manifest's repeated pair revision IDs to
    # the exact pair approval row, not merely to any existing document revisions.
    with op.batch_alter_table("project_document_pair_approvals") as batch_op:
        batch_op.create_unique_constraint(
            "uq_project_pair_approval_snapshot",
            ["id", "project_id", "project_revision_id", "agents_revision_id"],
        )

    op.create_table(
        "project_approval_manifests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("pair_approval_id", sa.Uuid(), nullable=False),
        sa.Column("project_revision_id", sa.Uuid(), nullable=False),
        sa.Column("agents_revision_id", sa.Uuid(), nullable=False),
        sa.Column("backlog_revision_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pair_approval_id", "project_id", "project_revision_id", "agents_revision_id"],
            [
                "project_document_pair_approvals.id",
                "project_document_pair_approvals.project_id",
                "project_document_pair_approvals.project_revision_id",
                "project_document_pair_approvals.agents_revision_id",
            ],
            ondelete="CASCADE",
            name="fk_project_approval_manifests_pair_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["backlog_revision_id"],
            ["project_document_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "pair_approval_id",
            "backlog_revision_id",
            name="uq_project_approval_manifest_snapshot",
        ),
    )
    op.create_index(
        "ix_project_approval_manifests_project_created",
        "project_approval_manifests",
        ["project_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_approval_manifests_project_created",
        table_name="project_approval_manifests",
    )
    op.drop_table("project_approval_manifests")
    with op.batch_alter_table("project_document_pair_approvals") as batch_op:
        batch_op.drop_constraint("uq_project_pair_approval_snapshot", type_="unique")
