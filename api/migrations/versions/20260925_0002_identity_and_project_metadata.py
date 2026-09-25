"""Add operator-managed identities, sessions, audit, limits, and metadata.

Revision ID: 20260925_0002
Revises: 20260925_0001
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0002"
down_revision: str | None = "20260925_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=127), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), server_default=sa.text("'user'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_role_active", "users", ["role", "is_active"], unique=False)

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 120", name="ck_projects_name_length"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_projects_owner_created", "projects", ["owner_user_id", "created_at"], unique=False
    )

    op.create_table(
        "web_sessions",
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("csrf_token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        "ix_web_sessions_user_expires", "web_sessions", ["user_id", "expires_at"], unique=False
    )

    op.create_table(
        "rate_limit_buckets",
        sa.Column("key_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("window_started", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_rate_limit_attempts_nonnegative"),
        sa.PrimaryKeyConstraint("key_hash"),
    )
    op.create_index(
        "ix_rate_limit_buckets_expires",
        "rate_limit_buckets",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("actor_kind IN ('operator', 'user')", name="ck_audit_actor_kind"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_actor_created",
        "audit_events",
        ["actor_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_project_created",
        "audit_events",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_audit_events_created", "audit_events", ["created_at"], unique=False)

    op.create_table(
        "bootstrap_state",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_bootstrap_state_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "bootstrap_state",
            sa.column("id", sa.SmallInteger()),
            sa.column("completed", sa.Boolean()),
        ),
        [{"id": 1, "completed": False}],
    )


def downgrade() -> None:
    op.drop_table("bootstrap_state")
    op.drop_index("ix_audit_events_created", table_name="audit_events")
    op.drop_index("ix_audit_events_project_created", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_rate_limit_buckets_expires", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
    op.drop_index("ix_web_sessions_user_expires", table_name="web_sessions")
    op.drop_table("web_sessions")
    op.drop_index("ix_projects_owner_created", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_users_role_active", table_name="users")
    op.drop_table("users")
