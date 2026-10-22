"""Retire derivative content and extraction scheduling, preserving native originals.

Revision ID: 20261022_0013
Revises: 20261014_0012

0011 already fenced legacy completions before native admission. Hold the attachment
DDL lock for this transaction too. No receipt, selection, deletion/purge tombstone,
turn JSON, conversation or approval is changed: historical text identity stays text.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261022_0013"
down_revision: str | None = "20261014_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("LOCK TABLE project_attachments IN ACCESS EXCLUSIVE MODE"))
    with op.batch_alter_table("project_attachments") as batch:
        for name in (
            "ck_attachment_derivative",
            "ck_attachment_text_bytes",
            "ck_attachment_lease",
            "ck_attachment_retry",
            "ck_attachment_native_fence",
        ):
            batch.drop_constraint(name, type_="check")
        batch.drop_index("ix_attachment_status_lease")
        for name in (
            "text_content",
            "text_size",
            "text_sha256",
            "page_count",
            "missing_pages",
            "extraction_policy",
            "qpdf_version",
            "pdftotext_version",
            "extractor_build_sha256",
            "attempt_count",
            "lease_id",
            "lease_until",
            "next_attempt_at",
            "last_error_code",
        ):
            batch.drop_column(name)
    # Retained bytes become stored regardless of the old parser's assessment.
    # Missing originals stay failed/unavailable; keep existing safe failure facts,
    # size/hash metadata and IDs, never fabricate bytes or reinterpret text hashes.
    op.execute(
        sa.text(
            "UPDATE project_attachments SET "
            "status = CASE WHEN original IS NOT NULL THEN 'stored' ELSE 'failed' END, "
            "failure_code = CASE WHEN original IS NOT NULL THEN NULL "
            "ELSE COALESCE(failure_code, 'unavailable') END"
        )
    )
    with op.batch_alter_table("project_attachments") as batch:
        batch.drop_constraint("ck_attachment_status", type_="check")
        batch.create_check_constraint("ck_attachment_status", "status IN ('failed','stored')")


def downgrade() -> None:
    raise RuntimeError("Retired PDF derivatives cannot be recovered; restore a prior backup")
