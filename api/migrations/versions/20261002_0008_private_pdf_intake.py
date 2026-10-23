"""Private conversation-bound PDF originals and bounded derivative provenance.

Revision ID: 20261002_0008
Revises: 20261001_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0008"
down_revision: str | None = "20261001_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL bytea is authoritative; SQLite is only the existing unit-test seam.
    text_bytes = (
        "octet_length(text_content)"
        if op.get_bind().dialect.name == "postgresql"
        else "length(CAST(text_content AS BLOB))"
    )
    op.create_table(
        "project_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(32)),
        sa.Column("original", sa.LargeBinary()),
        sa.Column("original_size", sa.Integer()),
        sa.Column("original_sha256", sa.String(64)),
        sa.Column("text_content", sa.Text()),
        sa.Column("text_size", sa.Integer()),
        sa.Column("text_sha256", sa.String(64)),
        sa.Column("page_count", sa.Integer()),
        sa.Column("missing_pages", sa.JSON(none_as_null=True)),
        sa.Column("extraction_policy", sa.String(32)),
        sa.Column("qpdf_version", sa.String(16)),
        sa.Column("pdftotext_version", sa.String(16)),
        sa.Column("extractor_build_sha256", sa.String(64)),
        sa.Column("attempt_count", sa.SmallInteger(), nullable=False),
        sa.Column("lease_id", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["uploader_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "project_id"],
            ["conversations.id", "conversations.project_id"],
            ondelete="CASCADE",
            name="fk_attachment_conversation_project",
        ),
        sa.CheckConstraint("length(filename) BETWEEN 1 AND 180", name="ck_attachment_filename"),
        sa.CheckConstraint(
            "status IN ('pending','processing','ready','failed')", name="ck_attachment_status"
        ),
        sa.CheckConstraint(
            "original_size IS NULL OR original_size BETWEEN 1 AND 50000000",
            name="ck_attachment_original_size",
        ),
        sa.CheckConstraint(
            "(original_size IS NULL AND original_sha256 IS NULL) OR "
            "(original_size IS NOT NULL AND original_sha256 IS NOT NULL "
            "AND length(original_sha256) = 64)",
            name="ck_attachment_original_metadata",
        ),
        sa.CheckConstraint(
            "(status = 'failed' AND original IS NULL) OR "
            "(status <> 'failed' AND original IS NOT NULL AND original_size IS NOT NULL "
            "AND length(original) = original_size)",
            name="ck_attachment_original",
        ),
        sa.CheckConstraint(
            "(status = 'failed' AND failure_code IS NOT NULL AND failure_code IN "
            "('busy','invalid','encrypted','active_content','no_text','limit','timeout',"
            "'unavailable','upload_interrupted')) OR (status <> 'failed' AND failure_code IS NULL)",
            name="ck_attachment_failure",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 32767 AND "
            "((status = 'processing' AND lease_id IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(status <> 'processing' AND lease_id IS NULL AND lease_until IS NULL))",
            name="ck_attachment_lease",
        ),
        sa.CheckConstraint(
            "(status = 'ready' AND text_content IS NOT NULL AND text_size IS NOT NULL "
            "AND text_size BETWEEN 1 AND 131072 AND text_sha256 IS NOT NULL "
            "AND length(text_sha256) = 64 AND page_count IS NOT NULL "
            "AND page_count BETWEEN 1 AND 500 AND missing_pages IS NOT NULL "
            "AND length(CAST(missing_pages AS TEXT)) <= 2500 "
            "AND extraction_policy = 'imp017-text-v1' AND qpdf_version = '11.3.0' "
            "AND pdftotext_version = '22.12.0' AND extractor_build_sha256 IS NOT NULL "
            "AND length(extractor_build_sha256) = 64 "
            "AND extraction_policy IS NOT NULL AND qpdf_version IS NOT NULL "
            "AND pdftotext_version IS NOT NULL) OR "
            "(status <> 'ready' AND text_content IS NULL AND text_size IS NULL "
            "AND text_sha256 IS NULL AND page_count IS NULL AND missing_pages IS NULL "
            "AND extraction_policy IS NULL AND qpdf_version IS NULL "
            "AND pdftotext_version IS NULL AND extractor_build_sha256 IS NULL)",
            name="ck_attachment_derivative",
        ),
        sa.CheckConstraint(
            f"text_content IS NULL OR {text_bytes} = text_size", name="ck_attachment_text_bytes"
        ),
    )
    op.create_index(
        "ix_attachment_conversation_created",
        "project_attachments",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index("ix_attachment_status_lease", "project_attachments", ["status", "lease_until"])


def downgrade() -> None:
    # Never silently destroy retained originals/derivatives or safe failure history.
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM project_attachments")):
        raise RuntimeError("Cannot discard retained attachments")
    op.drop_table("project_attachments")
