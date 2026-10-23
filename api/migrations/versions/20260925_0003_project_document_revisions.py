"""Add private project drafts, immutable revisions, and conflict proposals.

Revision ID: 20260925_0003
Revises: 20260925_0002
Create Date: 2026-09-25
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0003"
down_revision: str | None = "20260925_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _legacy_name_key(name: str) -> str:
    """Freeze the v0003 Unicode normalization rule inside this migration."""
    canonical = unicodedata.normalize("NFKC", name).strip().casefold()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    projects = sa.table(
        "projects",
        sa.column("id", sa.Uuid()),
        sa.column("owner_user_id", sa.Uuid()),
        sa.column("name", sa.String(length=120)),
        sa.column("name_key", sa.String(length=512)),
    )
    op.add_column("projects", sa.Column("name_key", sa.String(length=512), nullable=True))

    # Preserve every metadata-only project even if historic direct inserts used
    # names that collide after Unicode case-folding; new inserts will use the
    # unmodified canonical key and be rejected on collision.
    seen: set[tuple[uuid.UUID, str]] = set()
    existing_projects = bind.execute(
        sa.select(projects.c.id, projects.c.owner_user_id, projects.c.name).order_by(
            projects.c.owner_user_id, projects.c.id
        )
    )
    for project_id, owner_user_id, name in existing_projects:
        canonical_key = _legacy_name_key(name)
        name_key = canonical_key
        suffix_number = 0
        while (owner_user_id, name_key) in seen:
            suffix_number += 1
            name_key = hashlib.sha256(
                f"{canonical_key}:legacy:{project_id}:{suffix_number}".encode("ascii")
            ).hexdigest()
        seen.add((owner_user_id, name_key))
        bind.execute(projects.update().where(projects.c.id == project_id).values(name_key=name_key))

    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "name_key",
            existing_type=sa.String(length=512),
            nullable=False,
        )
    op.create_index(
        "uq_projects_owner_name_key",
        "projects",
        ["owner_user_id", "name_key"],
        unique=True,
    )

    op.create_table(
        "project_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "head_revision_number", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('project', 'agents', 'backlog')", name="ck_project_documents_kind"
        ),
        sa.CheckConstraint(
            "head_revision_number >= 1", name="ck_project_documents_head_revision_positive"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "kind", name="uq_project_documents_project_kind"),
    )
    op.create_table(
        "project_document_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("template_source", sa.String(length=128), nullable=True),
        sa.Column("template_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("revision_number >= 1", name="ck_document_revisions_number_positive"),
        sa.CheckConstraint("origin IN ('template', 'human')", name="ck_document_revisions_origin"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_document_revisions_hash_length"),
        sa.CheckConstraint(
            "(template_source IS NULL AND template_sha256 IS NULL) OR "
            "(template_source IS NOT NULL AND template_sha256 IS NOT NULL)",
            name="ck_document_revisions_template_provenance_pair",
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["project_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "revision_number", name="uq_document_revisions_number"),
    )
    op.create_index(
        "ix_document_revisions_author_created",
        "project_document_revisions",
        ["author_user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "document_conflict_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("expected_revision_number", sa.Integer(), nullable=False),
        sa.Column("observed_revision_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expected_revision_number >= 1", name="ck_conflict_proposals_expected_positive"
        ),
        sa.CheckConstraint(
            "observed_revision_number >= 1", name="ck_conflict_proposals_observed_positive"
        ),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_conflict_proposals_hash_length"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["project_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conflict_proposals_document_created",
        "document_conflict_proposals",
        ["document_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_conflict_proposals_author_created",
        "document_conflict_proposals",
        ["author_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_conflict_proposals_author_created", table_name="document_conflict_proposals")
    op.drop_index(
        "ix_conflict_proposals_document_created", table_name="document_conflict_proposals"
    )
    op.drop_table("document_conflict_proposals")
    op.drop_index("ix_document_revisions_author_created", table_name="project_document_revisions")
    op.drop_table("project_document_revisions")
    op.drop_table("project_documents")
    op.drop_index("uq_projects_owner_name_key", table_name="projects")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("name_key")
