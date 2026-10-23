"""Re-key existing v0003 projects with bounded Unicode-normalized digests.

Revision ID: 20260925_0004
Revises: 20260925_0003
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0004"
down_revision: str | None = "20260925_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    projects = sa.table(
        "projects",
        sa.column("id", sa.Uuid()),
        sa.column("owner_user_id", sa.Uuid()),
        sa.column("name", sa.String(length=120)),
        sa.column("name_key", sa.String(length=512)),
    )
    # A v0003 installation can have unhashed, expanded keys and legacy collision
    # suffixes. Recompute from display names; never truncate the comparison input.
    op.drop_index("uq_projects_owner_name_key", table_name="projects")
    seen: set[tuple[uuid.UUID, str]] = set()
    for project_id, owner_id, name in bind.execute(
        sa.select(projects.c.id, projects.c.owner_user_id, projects.c.name).order_by(
            projects.c.owner_user_id, projects.c.id
        )
    ):
        canonical = unicodedata.normalize("NFKC", name).strip().casefold()
        base = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        key = base
        counter = 0
        while (owner_id, key) in seen:
            counter += 1
            key = hashlib.sha256(
                f"{base}:legacy:{project_id}:{counter}".encode("ascii")
            ).hexdigest()
        seen.add((owner_id, key))
        bind.execute(projects.update().where(projects.c.id == project_id).values(name_key=key))
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "name_key", existing_type=sa.String(length=512), type_=sa.String(length=64)
        )
    op.create_index(
        "uq_projects_owner_name_key", "projects", ["owner_user_id", "name_key"], unique=True
    )


def downgrade() -> None:
    # Digest keys remain valid at v0003; expanding the column is sufficient.
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "name_key", existing_type=sa.String(length=64), type_=sa.String(length=512)
        )
