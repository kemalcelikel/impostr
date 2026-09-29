"""Application persistence models for identity, private metadata, and audit."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db import Base
from app.project_names import project_name_key


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        Index("ix_users_role_active", "role", "is_active"),
        UniqueConstraint("username", name="uq_users_username"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(127), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WebSession(Base):
    __tablename__ = "web_sessions"
    __table_args__ = (Index("ix_web_sessions_user_expires", "user_id", "expires_at"),)

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    csrf_token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_rate_limit_attempts_nonnegative"),
        Index("ix_rate_limit_buckets_expires", "expires_at"),
    )

    key_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    window_started: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("actor_kind IN ('operator', 'user')", name="ck_audit_actor_kind"),
        Index("ix_audit_events_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_events_project_created", "project_id", "created_at"),
        Index("ix_audit_events_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 120", name="ck_projects_name_length"),
        Index("ix_projects_owner_created", "owner_user_id", "created_at"),
        Index("uq_projects_owner_name_key", "owner_user_id", "name_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=lambda context: project_name_key(str(context.get_current_parameters()["name"])),
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectDocument(Base):
    __tablename__ = "project_documents"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('project', 'agents', 'backlog')", name="ck_project_documents_kind"
        ),
        CheckConstraint(
            "head_revision_number >= 1", name="ck_project_documents_head_revision_positive"
        ),
        UniqueConstraint("project_id", "kind", name="uq_project_documents_project_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    head_revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectDocumentRevision(Base):
    __tablename__ = "project_document_revisions"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="ck_document_revisions_number_positive"),
        CheckConstraint("origin IN ('template', 'human')", name="ck_document_revisions_origin"),
        CheckConstraint("length(content_sha256) = 64", name="ck_document_revisions_hash_length"),
        CheckConstraint(
            "(template_source IS NULL AND template_sha256 IS NULL) OR "
            "(template_source IS NOT NULL AND template_sha256 IS NOT NULL)",
            name="ck_document_revisions_template_provenance_pair",
        ),
        UniqueConstraint("document_id", "revision_number", name="uq_document_revisions_number"),
        Index("ix_document_revisions_author_created", "author_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    template_source: Mapped[str | None] = mapped_column(String(128))
    template_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentConflictProposal(Base):
    __tablename__ = "document_conflict_proposals"
    __table_args__ = (
        CheckConstraint(
            "expected_revision_number >= 1", name="ck_conflict_proposals_expected_positive"
        ),
        CheckConstraint(
            "observed_revision_number >= 1", name="ck_conflict_proposals_observed_positive"
        ),
        CheckConstraint("length(content_sha256) = 64", name="ck_conflict_proposals_hash_length"),
        Index("ix_conflict_proposals_document_created", "document_id", "created_at"),
        Index("ix_conflict_proposals_author_created", "author_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False
    )
    expected_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BootstrapState(Base):
    __tablename__ = "bootstrap_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_bootstrap_state_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
