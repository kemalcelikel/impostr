"""Ordered PDF request identity; deletion does not erase turn replay metadata.

Revision ID: 20261002_0010
Revises: 20261002_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0010"
down_revision: str | None = "20261002_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_turns") as batch:
        batch.add_column(
            sa.Column("submission_state", sa.String(24), nullable=False, server_default="queued")
        )
        batch.add_column(sa.Column("dispatch_rendered_sha256", sa.String(64)))
        batch.add_column(sa.Column("dispatch_manifest_sha256", sa.String(64)))
        batch.add_column(sa.Column("dispatch_manifest", sa.JSON()))
        batch.add_column(
            sa.Column("receipt_pending", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("stop_confirmed", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.create_check_constraint(
            "ck_turn_submission_state",
            "submission_state IN ('queued','sent','failed-before-send','uncertain')",
        )
    # Legacy turns have no trusted receipt proof. Never manufacture sent/never-sent.
    op.execute(
        sa.text(
            "UPDATE chat_turns SET submission_state = 'uncertain' WHERE broker_epoch IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE chat_turns SET submission_state = 'failed-before-send' "
            "WHERE broker_epoch IS NULL AND state != 'queued'"
        )
    )
    op.create_table(
        "chat_turn_pdf_selections",
        sa.Column("turn_id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("position", sa.SmallInteger(), nullable=False, primary_key=True),
        sa.Column("attachment_id", sa.Uuid(), nullable=False),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
        sa.CheckConstraint("position BETWEEN 0 AND 31", name="ck_turn_pdf_position"),
        sa.CheckConstraint("length(expected_sha256) = 64", name="ck_turn_pdf_hash"),
    )
    op.create_table(
        "chat_submission_receipts",
        sa.Column("turn_id", sa.Uuid(), primary_key=True),
        sa.Column("call", sa.SmallInteger(), primary_key=True),
        sa.Column("request_sha256", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
        sa.CheckConstraint("call BETWEEN 1 AND 8", name="ck_receipt_call"),
        sa.CheckConstraint(
            "status IN ('sent','uncertain','failed-before-send')", name="ck_receipt_status"
        ),
        sa.CheckConstraint(
            "request_sha256 IS NULL OR length(request_sha256) = 64", name="ck_receipt_hash"
        ),
        sa.CheckConstraint(
            "status = 'failed-before-send' OR request_sha256 IS NOT NULL",
            name="ck_receipt_sent_hash",
        ),
    )
    op.create_table(
        "attachment_deletions",
        sa.Column("attachment_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("pending", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id", "project_id"],
            ["conversations.id", "conversations.project_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_attachment_deletions_project_id", "attachment_deletions", ["project_id"])
    op.create_table(
        "attachment_purges",
        sa.Column("attachment_id", sa.Uuid(), primary_key=True),
        sa.Column("turn_id", sa.Uuid(), primary_key=True),
        sa.Column("confirmed_epoch", sa.Uuid()),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["attachment_deletions.attachment_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM chat_turn_pdf_selections")):
        raise RuntimeError("Cannot discard retained PDF turn selections")
    if (
        op.get_bind().scalar(sa.text("SELECT count(*) FROM chat_submission_receipts"))
        or op.get_bind().scalar(sa.text("SELECT count(*) FROM attachment_deletions"))
        or op.get_bind().scalar(
            sa.text("SELECT count(*) FROM chat_turns WHERE dispatch_rendered_sha256 IS NOT NULL")
        )
    ):
        raise RuntimeError("Cannot discard retained submission or cleanup proof")
    op.drop_table("attachment_purges")
    op.drop_index("ix_attachment_deletions_project_id", table_name="attachment_deletions")
    op.drop_table("attachment_deletions")
    op.drop_table("chat_submission_receipts")
    op.drop_table("chat_turn_pdf_selections")
    with op.batch_alter_table("chat_turns") as batch:
        batch.drop_constraint("ck_turn_submission_state", type_="check")
        for column in (
            "submission_state",
            "dispatch_rendered_sha256",
            "dispatch_manifest_sha256",
            "dispatch_manifest",
            "receipt_pending",
            "stop_confirmed",
        ):
            batch.drop_column(column)
