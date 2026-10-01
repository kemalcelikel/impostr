"""Durable conversations, committed dispatch and agent proposal provenance.

Revision ID: 20261001_0007
Revises: 20260930_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0007"
down_revision: str | None = "20260930_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id(name: str = "id", *, primary: bool = False, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Uuid(), primary_key=primary, nullable=nullable)


def _created() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    with op.batch_alter_table("project_document_revisions") as batch:
        batch.drop_constraint("ck_document_revisions_origin", type_="check")
        batch.create_check_constraint(
            "ck_document_revisions_origin", "origin IN ('template','human','agent')"
        )
    op.create_table(
        "conversations",
        _id(primary=True),
        _id("project_id"),
        _id("creator_user_id"),
        sa.Column("title", sa.String(120), nullable=False),
        _created(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creator_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "project_id", name="uq_conversation_project"),
    )
    op.create_table(
        "conversation_preferences",
        _id("user_id", primary=True),
        _id("project_id", primary=True),
        _id("conversation_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "project_id"],
            ["conversations.id", "conversations.project_id"],
            ondelete="CASCADE",
            name="fk_preference_conversation_project",
        ),
    )
    op.create_table(
        "chat_turns",
        _id(primary=True),
        _id("project_id"),
        _id("conversation_id"),
        _id("request_id"),
        _id("actor_user_id"),
        sa.Column("web_session_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        _id("broker_epoch", nullable=True),
        sa.Column("native_session_id", sa.String(140), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("broker_cursor", sa.Integer(), nullable=False),
        sa.Column("output_bytes", sa.Integer(), nullable=False),
        _created(),
        sa.Column("dispatch_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pump_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "project_id"],
            ["conversations.id", "conversations.project_id"],
            ondelete="CASCADE",
            name="fk_turn_conversation_project",
        ),
        sa.UniqueConstraint("id", "project_id", name="uq_turn_project"),
        sa.UniqueConstraint("id", "conversation_id", name="uq_turn_conversation"),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_turn_request"),
        sa.CheckConstraint(
            "state IN ('queued','dispatching','running','cancelling','completed',"
            "'failed','cancelled','interrupted')",
            name="ck_turn_state",
        ),
        sa.CheckConstraint("event_count BETWEEN 0 AND 256", name="ck_turn_event_count"),
    )
    op.create_index("ix_turn_state_created", "chat_turns", ["state", "created_at"])
    op.create_table(
        "project_turn_reservations",
        _id("project_id", primary=True),
        _id("turn_id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["turn_id", "project_id"],
            ["chat_turns.id", "chat_turns.project_id"],
            ondelete="CASCADE",
            name="fk_reservation_turn_project",
        ),
        sa.UniqueConstraint("turn_id", name="uq_reservation_turn"),
    )
    op.create_table(
        "chat_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _id("conversation_id"),
        _id("turn_id"),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        _created(),
        sa.ForeignKeyConstraint(
            ["turn_id", "conversation_id"],
            ["chat_turns.id", "chat_turns.conversation_id"],
            ondelete="CASCADE",
            name="fk_event_turn_conversation",
        ),
        sa.UniqueConstraint("turn_id", "sequence", name="uq_event_turn_sequence"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 256", name="ck_event_sequence"),
    )
    op.create_index("ix_event_conversation_id", "chat_events", ["conversation_id", "id"])
    op.create_table(
        "chat_interactions",
        _id(primary=True),
        _id("turn_id"),
        sa.Column("native_id", sa.String(140), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("reply", sa.JSON(), nullable=True),
        _id("reply_request_id", nullable=True),
        sa.Column("reply_dispatched", sa.Boolean(), nullable=False),
        _id("reply_actor_user_id", nullable=True),
        sa.Column("reply_session_hash", sa.LargeBinary(32), nullable=True),
        sa.ForeignKeyConstraint(["reply_actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("turn_id", "native_id", name="uq_interaction_native"),
        sa.CheckConstraint("kind IN ('question','permission')", name="ck_interaction_kind"),
        sa.CheckConstraint(
            "state IN ('pending','replying','replied','interrupted')", name="ck_interaction_state"
        ),
    )
    op.create_table(
        "agent_document_proposals",
        _id(primary=True),
        _id("turn_id"),
        _id("document_id"),
        _id("base_revision_id"),
        _id("observed_revision_id"),
        _id("imported_revision_id", nullable=True),
        _id("conflict_proposal_id", nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("agent_version", sa.String(16), nullable=False),
        _created(),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["project_documents.id"], ondelete="CASCADE"),
        *[
            sa.ForeignKeyConstraint([column], ["project_document_revisions.id"], ondelete="CASCADE")
            for column in ("base_revision_id", "observed_revision_id", "imported_revision_id")
        ],
        sa.ForeignKeyConstraint(
            ["conflict_proposal_id"], ["document_conflict_proposals.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("turn_id", "document_id", name="uq_agent_proposal_document"),
        sa.CheckConstraint("state IN ('imported','conflict')", name="ck_agent_proposal_state"),
    )


def downgrade() -> None:
    # Never relabel generated history as human. An operator must retain this schema
    # once generated revisions exist; downgrading an unused synthetic schema is safe.
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT count(*) FROM project_document_revisions WHERE origin='agent'")
    ):
        raise RuntimeError("Cannot discard agent provenance")
    for table in (
        "agent_document_proposals",
        "chat_interactions",
        "chat_events",
        "project_turn_reservations",
        "chat_turns",
        "conversation_preferences",
        "conversations",
    ):
        op.drop_table(table)
    with op.batch_alter_table("project_document_revisions") as batch:
        batch.drop_constraint("ck_document_revisions_origin", type_="check")
        batch.create_check_constraint(
            "ck_document_revisions_origin", "origin IN ('template','human')"
        )
