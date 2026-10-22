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
    ForeignKeyConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship
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
        CheckConstraint(
            "origin IN ('template', 'human', 'agent')", name="ck_document_revisions_origin"
        ),
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


class ProjectDocumentPairApproval(Base):
    __tablename__ = "project_document_pair_approvals"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "project_revision_id",
            "agents_revision_id",
            name="uq_project_pair_approval_revisions",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "project_revision_id",
            "agents_revision_id",
            name="uq_project_pair_approval_snapshot",
        ),
        Index(
            "ix_project_pair_approvals_project_created",
            "project_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("project_document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    agents_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("project_document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    project_revision: Mapped[ProjectDocumentRevision] = relationship(
        foreign_keys=[project_revision_id]
    )
    agents_revision: Mapped[ProjectDocumentRevision] = relationship(
        foreign_keys=[agents_revision_id]
    )


class ProjectApprovalManifest(Base):
    __tablename__ = "project_approval_manifests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["pair_approval_id", "project_id", "project_revision_id", "agents_revision_id"],
            [
                "project_document_pair_approvals.id",
                "project_document_pair_approvals.project_id",
                "project_document_pair_approvals.project_revision_id",
                "project_document_pair_approvals.agents_revision_id",
            ],
            ondelete="CASCADE",
            name="fk_project_approval_manifests_pair_snapshot",
        ),
        UniqueConstraint(
            "project_id",
            "pair_approval_id",
            "backlog_revision_id",
            name="uq_project_approval_manifest_snapshot",
        ),
        Index(
            "ix_project_approval_manifests_project_created",
            "project_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    pair_approval_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    agents_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    backlog_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("project_document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
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


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("id", "project_id", name="uq_conversation_project"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    creator_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationPreference(Base):
    __tablename__ = "conversation_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "project_id"],
            ["conversations.id", "conversations.project_id"],
            ondelete="CASCADE",
            name="fk_preference_conversation_project",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)


class ProjectAttachment(Base):
    """Private originals and derivatives; never load blobs in metadata queries."""

    __tablename__ = "project_attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "project_id"],
            ["conversations.id", "conversations.project_id"],
            ondelete="CASCADE",
            name="fk_attachment_conversation_project",
        ),
        CheckConstraint("length(filename) BETWEEN 1 AND 180", name="ck_attachment_filename"),
        CheckConstraint(
            "status IN ('pending','processing','ready','failed','stored')",
            name="ck_attachment_status",
        ),
        CheckConstraint(
            "original_size IS NULL OR original_size BETWEEN 1 AND 50000000",
            name="ck_attachment_original_size",
        ),
        CheckConstraint(
            "(original_size IS NULL AND original_sha256 IS NULL) OR "
            "(original_size IS NOT NULL AND original_sha256 IS NOT NULL "
            "AND length(original_sha256) = 64)",
            name="ck_attachment_original_metadata",
        ),
        CheckConstraint(
            "(status = 'failed' AND original IS NULL) OR "
            "(status <> 'failed' AND original IS NOT NULL AND original_size IS NOT NULL "
            "AND length(original) = original_size)",
            name="ck_attachment_original",
        ),
        CheckConstraint(
            "(status = 'failed' AND failure_code IS NOT NULL AND failure_code IN "
            "('busy','invalid','encrypted','active_content','no_text','limit','timeout',"
            "'unavailable','upload_interrupted')) OR (status <> 'failed' AND failure_code IS NULL)",
            name="ck_attachment_failure",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 0 AND 32767 AND "
            "((status = 'processing' AND lease_id IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(status <> 'processing' AND lease_id IS NULL AND lease_until IS NULL))",
            name="ck_attachment_lease",
        ),
        CheckConstraint(
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
            name="ck_attachment_derivative",
        ),
        CheckConstraint(
            "text_content IS NULL OR octet_length(text_content) = text_size",
            name="ck_attachment_text_bytes",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "text_content IS NULL OR length(CAST(text_content AS BLOB)) = text_size",
            name="ck_attachment_text_bytes",
        ).ddl_if(dialect="sqlite"),
        Index("ix_attachment_conversation_created", "conversation_id", "created_at", "id"),
        Index("ix_attachment_status_lease", "status", "lease_until"),
        CheckConstraint(
            "(next_attempt_at IS NULL OR status = 'pending') AND "
            "(last_error_code IS NULL OR (status = 'pending' AND "
            "last_error_code IN ('busy','unavailable')))",
            name="ck_attachment_retry",
        ),
        CheckConstraint(
            "status <> 'stored' OR (attempt_count = 0 AND lease_id IS NULL "
            "AND lease_until IS NULL AND next_attempt_at IS NULL AND last_error_code IS NULL)",
            name="ck_attachment_native_fence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    uploader_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="stored")
    failure_code: Mapped[str | None] = mapped_column(String(32))
    original: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    original_size: Mapped[int | None] = mapped_column(Integer)
    original_sha256: Mapped[str | None] = mapped_column(String(64))
    text_content: Mapped[str | None] = mapped_column(Text, deferred=True)
    text_size: Mapped[int | None] = mapped_column(Integer)
    text_sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    missing_pages: Mapped[list[int] | None] = mapped_column(JSON(none_as_null=True))
    extraction_policy: Mapped[str | None] = mapped_column(String(32))
    qpdf_version: Mapped[str | None] = mapped_column(String(16))
    pdftotext_version: Mapped[str | None] = mapped_column(String(16))
    extractor_build_sha256: Mapped[str | None] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    lease_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChatTurn(Base):
    __tablename__ = "chat_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "project_id"],
            ["conversations.id", "conversations.project_id"],
            ondelete="CASCADE",
            name="fk_turn_conversation_project",
        ),
        UniqueConstraint("id", "project_id", name="uq_turn_project"),
        UniqueConstraint("id", "conversation_id", name="uq_turn_conversation"),
        UniqueConstraint("conversation_id", "request_id", name="uq_turn_request"),
        CheckConstraint(
            "state IN ('queued','dispatching','running','cancelling','completed','failed',"
            "'cancelled','interrupted')",
            name="ck_turn_state",
        ),
        CheckConstraint("event_count BETWEEN 0 AND 256", name="ck_turn_event_count"),
        CheckConstraint(
            "submission_state IN ('queued','sent','failed-before-send','uncertain')",
            name="ck_turn_submission_state",
        ),
        Index("ix_turn_state_created", "state", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    web_session_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    broker_epoch: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    native_session_id: Mapped[str | None] = mapped_column(String(140))
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    broker_cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dispatch_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pump_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_state: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    dispatch_rendered_sha256: Mapped[str | None] = mapped_column(String(64))
    dispatch_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    dispatch_manifest: Mapped[list[Any] | None] = mapped_column(JSON)
    receipt_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stop_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ChatSubmissionReceipt(Base):
    """Trusted host facts only; scope, epoch and manifest are inherited from the turn."""

    __tablename__ = "chat_submission_receipts"
    __table_args__ = (
        CheckConstraint("call BETWEEN 1 AND 8", name="ck_receipt_call"),
        CheckConstraint(
            "status IN ('sent','uncertain','failed-before-send')", name="ck_receipt_status"
        ),
        CheckConstraint(
            "request_sha256 IS NULL OR length(request_sha256) = 64", name="ck_receipt_hash"
        ),
        CheckConstraint(
            "status = 'failed-before-send' OR request_sha256 IS NOT NULL",
            name="ck_receipt_sent_hash",
        ),
        CheckConstraint(
            "reference_kind IN ('legacy-text-v1','native-original-v1')",
            name="ck_receipt_reference_kind",
        ),
        CheckConstraint(
            "request_size IS NULL OR request_size BETWEEN 1 AND 71303168",
            name="ck_receipt_request_size",
        ),
        CheckConstraint(
            "reference_kind <> 'native-original-v1' OR status = 'failed-before-send' OR "
            "(request_size IS NOT NULL AND authorization_id IS NOT NULL)",
            name="ck_receipt_native_authorized",
        ),
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_turns.id", ondelete="CASCADE"), primary_key=True
    )
    call: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reference_kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default="legacy-text-v1"
    )
    request_size: Mapped[int | None] = mapped_column(Integer)
    authorization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ChatSendAuthorization(Base):
    """One committed native call grant; metadata only, never replayed after lost ACK."""

    __tablename__ = "chat_send_authorizations"
    __table_args__ = (
        CheckConstraint("call BETWEEN 1 AND 8", name="ck_send_call"),
        CheckConstraint("request_size BETWEEN 1 AND 71303168", name="ck_send_request_size"),
        CheckConstraint("length(request_sha256) = 64", name="ck_send_request_hash"),
        CheckConstraint("length(original_manifest_sha256) = 64", name="ck_send_manifest_hash"),
        UniqueConstraint("authorization_id", name="uq_send_authorization_id"),
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_turns.id", ondelete="CASCADE"), primary_key=True
    )
    call: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    epoch: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    authorization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_size: Mapped[int] = mapped_column(Integer, nullable=False)
    original_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AttachmentDeletion(Base):
    """Durable removal fence/tombstone; no attachment FK or content copies."""

    __tablename__ = "attachment_deletions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "project_id"],
            ["conversations.id", "conversations.project_id"],
            ondelete="CASCADE",
        ),
    )
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AttachmentPurge(Base):
    """Per-turn cleanup proof survives an API crash/lost purge ACK."""

    __tablename__ = "attachment_purges"
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("attachment_deletions.attachment_id", ondelete="CASCADE"), primary_key=True
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_turns.id", ondelete="CASCADE"), primary_key=True
    )
    confirmed_epoch: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ChatTurnPdfSelection(Base):
    """Ordered request identity survives attachment deletion; never stores text.

    Deliberately no attachment FK: deleting a PDF must not erase turn idempotency.
    Versioned identity snapshots live in ChatTurn.payload references. Legacy hashes
    remain derivative hashes; migration never converts them into original hashes.
    """

    __tablename__ = "chat_turn_pdf_selections"
    __table_args__ = (
        CheckConstraint("position BETWEEN 0 AND 31", name="ck_turn_pdf_position"),
        CheckConstraint("length(expected_sha256) = 64", name="ck_turn_pdf_hash"),
        CheckConstraint(
            "reference_kind IN ('legacy-text-v1','native-original-v1')",
            name="ck_turn_pdf_kind",
        ),
    )

    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_turns.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default="native-original-v1"
    )


class ProjectTurnReservation(Base):
    __tablename__ = "project_turn_reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "project_id"],
            ["chat_turns.id", "chat_turns.project_id"],
            ondelete="CASCADE",
            name="fk_reservation_turn_project",
        ),
        UniqueConstraint("turn_id", name="uq_reservation_turn"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)


class ChatEvent(Base):
    __tablename__ = "chat_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "conversation_id"],
            ["chat_turns.id", "chat_turns.conversation_id"],
            ondelete="CASCADE",
            name="fk_event_turn_conversation",
        ),
        UniqueConstraint("turn_id", "sequence", name="uq_event_turn_sequence"),
        CheckConstraint("sequence BETWEEN 1 AND 256", name="ck_event_sequence"),
        Index("ix_event_conversation_id", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    turn_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatInteraction(Base):
    __tablename__ = "chat_interactions"
    __table_args__ = (
        UniqueConstraint("turn_id", "native_id", name="uq_interaction_native"),
        CheckConstraint("kind IN ('question','permission')", name="ck_interaction_kind"),
        CheckConstraint(
            "state IN ('pending','replying','replied','interrupted')", name="ck_interaction_state"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_turns.id", ondelete="CASCADE"), nullable=False
    )
    native_id: Mapped[str] = mapped_column(String(140), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reply: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reply_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reply_dispatched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reply_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    reply_session_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))


class AgentDocumentProposal(Base):
    __tablename__ = "agent_document_proposals"
    __table_args__ = (
        UniqueConstraint("turn_id", "document_id", name="uq_agent_proposal_document"),
        CheckConstraint("state IN ('imported','conflict')", name="ck_agent_proposal_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_turns.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False
    )
    base_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("project_document_revisions.id", ondelete="CASCADE"), nullable=False
    )
    observed_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("project_document_revisions.id", ondelete="CASCADE"), nullable=False
    )
    imported_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("project_document_revisions.id", ondelete="CASCADE")
    )
    conflict_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("document_conflict_proposals.id", ondelete="CASCADE")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.18.34")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
