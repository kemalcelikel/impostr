"""Explicit supported starter tuples; approval never consults installed templates."""

from __future__ import annotations

import hashlib
import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.document_contract import DOCUMENT_KINDS, MAX_DOCUMENT_BYTES
from app.models import ProjectDocument, ProjectDocumentRevision

TemplateProfile = Literal["legacy", "simplified"]
# Ordered PROJECT, AGENTS, BACKLOG (raw UTF-8 bytes). Legacy is the original
# 63c853c bundle. Changing installed examples does not change these pins.
SUPPORTED_STARTERS: dict[TemplateProfile, tuple[tuple[str, str], ...]] = {
    "legacy": (
        ("PROJECT.md.example", "3b2e686d807d186158c93fc8c6ee65076117b3327b6a22c384ccca232c2c853e"),
        ("AGENTS.md.example", "e256dc7a1088dfc829ed40716ff99b018a08a6d95e2dc64b6987194ac613fe82"),
        ("BACKLOG.md.example", "aa2f4000af2318242ad410ea6b32602611636e3f0399b7a677d42a06a883eb2d"),
    ),
    "simplified": (
        (
            "overnight-agent/PROJECT.md.example",
            "dda3dc322379fc12960ab9ba248f40f3d604e0ba6394150b4ef60d712a4b782f",
        ),
        (
            "overnight-agent/AGENTS.md.example",
            "7cb7f74f570681c51283191833bfa44468b225d9439f6834c6f28a9addaae2c3",
        ),
        (
            "overnight-agent/BACKLOG.md.example",
            "fa2e18762686cf21c43b6201505543d60caa9636b8aa19aad8db29f10c0d8b30",
        ),
    ),
}


def starter_identity(revision: ProjectDocumentRevision) -> tuple[str, str] | None:
    try:
        raw = revision.content.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    digest = hashlib.sha256(raw).hexdigest()
    if (
        not raw
        or len(raw) > MAX_DOCUMENT_BYTES
        or b"\x00" in raw
        or revision.revision_number != 1
        or revision.origin != "template"
        or revision.author_user_id is not None
        or revision.template_source is None
        or revision.template_sha256 != digest
        or revision.content_sha256 != digest
    ):
        return None
    return revision.template_source, digest


def resolve_template_profile(
    db: Session, project_id: uuid.UUID
) -> tuple[TemplateProfile, dict[str, ProjectDocumentRevision]] | None:
    # Only immutable seeds are read. In particular pair approval must not lock
    # the mutable backlog head or race its independent editing transaction.
    rows = db.execute(
        select(ProjectDocument, ProjectDocumentRevision)
        .join(ProjectDocumentRevision, ProjectDocumentRevision.document_id == ProjectDocument.id)
        .where(
            ProjectDocument.project_id == project_id, ProjectDocumentRevision.revision_number == 1
        )
    ).all()
    if len(rows) != len(DOCUMENT_KINDS):
        return None
    seeds = {document.kind: revision for document, revision in rows}
    if set(seeds) != set(DOCUMENT_KINDS):
        return None
    identity = tuple(starter_identity(seeds[kind]) for kind in DOCUMENT_KINDS)
    for profile, supported in SUPPORTED_STARTERS.items():
        if identity == supported:
            return profile, seeds
    return None
