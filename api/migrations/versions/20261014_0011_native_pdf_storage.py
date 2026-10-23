"""Fence legacy extraction and version original PDF selections without erasing data.

Revision ID: 20261014_0011
Revises: 20261002_0010 (the preserved IMP-018 candidate)

PostgreSQL holds the attachment DDL lock through this transaction. Old completions
must pass processing/status/token CAS after that lock: stored/null leases cannot
match. Derivative columns and old turn/receipt JSON are retained until IMP-027.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0011"
down_revision: str | None = "20261002_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project_attachments") as batch:
        batch.drop_constraint("ck_attachment_status", type_="check")
        batch.create_check_constraint(
            "ck_attachment_status",
            "status IN ('pending','processing','ready','failed','stored')",
        )
        batch.drop_constraint("ck_attachment_derivative", type_="check")
        batch.create_check_constraint(
            "ck_attachment_derivative",
            "(status IN ('ready','stored') AND text_content IS NOT NULL AND text_size IS NOT NULL "
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
        )
        batch.create_check_constraint(
            "ck_attachment_native_fence",
            "status <> 'stored' OR (attempt_count = 0 AND lease_id IS NULL "
            "AND lease_until IS NULL AND next_attempt_at IS NULL AND last_error_code IS NULL)",
        )
    op.execute(
        sa.text(
            "UPDATE project_attachments SET status = 'stored', failure_code = NULL, "
            "attempt_count = 0, lease_id = NULL, lease_until = NULL, "
            "next_attempt_at = NULL, last_error_code = NULL WHERE original IS NOT NULL"
        )
    )
    with op.batch_alter_table("chat_turn_pdf_selections") as batch:
        # Existing expected_sha256 values identify TEXT, not original bytes.
        batch.add_column(
            sa.Column(
                "reference_kind", sa.String(24), nullable=False, server_default="legacy-text-v1"
            )
        )
        batch.create_check_constraint(
            "ck_turn_pdf_kind", "reference_kind IN ('legacy-text-v1','native-original-v1')"
        )


def downgrade() -> None:
    # Re-enabling extraction could erase retained originals. Restoring an actual
    # pre-transition backup is the only honest recovery of old leases/queue state.
    raise RuntimeError("Native storage transition cannot be downgraded; restore a prior backup")
