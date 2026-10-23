"""Durable retry timing for private PDF extraction; preserves 0008 intake.

Revision ID: 20261002_0009
Revises: 20261002_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0009"
down_revision: str | None = "20261002_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project_attachments") as batch:
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_error_code", sa.String(32)))
        batch.create_check_constraint(
            "ck_attachment_retry",
            "(next_attempt_at IS NULL OR status = 'pending') AND "
            "(last_error_code IS NULL OR (status = 'pending' AND "
            "last_error_code IN ('busy','unavailable')))",
        )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM project_attachments")):
        raise RuntimeError("Cannot discard retained attachments")
    with op.batch_alter_table("project_attachments") as batch:
        batch.drop_constraint("ck_attachment_retry", type_="check")
        batch.drop_column("last_error_code")
        batch.drop_column("next_attempt_at")
