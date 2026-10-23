"""Metadata-only single-call native grants; preserve all historical text receipts.

Revision ID: 20261014_0012
Revises: 20261014_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0012"
down_revision: str | None = "20261014_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_send_authorizations",
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("call", sa.SmallInteger(), nullable=False),
        sa.Column("epoch", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("request_size", sa.Integer(), nullable=False),
        sa.Column("original_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("turn_id", "call"),
        sa.UniqueConstraint("authorization_id", name="uq_send_authorization_id"),
        sa.CheckConstraint("call BETWEEN 1 AND 8", name="ck_send_call"),
        sa.CheckConstraint("request_size BETWEEN 1 AND 71303168", name="ck_send_request_size"),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_send_request_hash"),
        sa.CheckConstraint("length(original_manifest_sha256) = 64", name="ck_send_manifest_hash"),
    )
    with op.batch_alter_table("chat_submission_receipts") as batch:
        batch.add_column(
            sa.Column(
                "reference_kind", sa.String(24), nullable=False, server_default="legacy-text-v1"
            )
        )
        batch.add_column(sa.Column("request_size", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("authorization_id", sa.Uuid(), nullable=True))
        batch.create_check_constraint(
            "ck_receipt_reference_kind",
            "reference_kind IN ('legacy-text-v1','native-original-v1')",
        )
        batch.create_check_constraint(
            "ck_receipt_request_size",
            "request_size IS NULL OR request_size BETWEEN 1 AND 71303168",
        )
        batch.create_check_constraint(
            "ck_receipt_native_authorized",
            "reference_kind <> 'native-original-v1' OR status = 'failed-before-send' OR "
            "(request_size IS NOT NULL AND authorization_id IS NOT NULL)",
        )


def downgrade() -> None:
    raise RuntimeError("Native send facts must not be relabeled; restore a pre-native backup")
