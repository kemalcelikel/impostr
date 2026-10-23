"""Creator-private project metadata and named project creation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.dependencies import CurrentActor, DbSession, SettingsDependency, load_active_actor
from app.document_contract import DocumentKind
from app.models import Project
from app.project_documents import add_template_documents
from app.project_names import normalize_project_name, project_name_key
from app.project_templates import ProjectTemplate
from app.rate_limit import consume_rate_bucket

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectMetadataView(BaseModel):
    id: uuid.UUID
    name: str
    owner_user_id: uuid.UUID
    created_at: datetime


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return normalize_project_name(value)


def project_view(project: Project) -> ProjectMetadataView:
    created_at = project.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return ProjectMetadataView(
        id=project.id,
        name=project.name,
        owner_user_id=project.owner_user_id,
        created_at=created_at,
    )


def _duplicate_name(db: Session, owner_user_id: uuid.UUID, name_key: str) -> bool:
    return (
        db.scalar(
            select(Project.id)
            .where(Project.owner_user_id == owner_user_id, Project.name_key == name_key)
            .limit(1)
        )
        is not None
    )


@router.post("", response_model=ProjectMetadataView, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    settings: SettingsDependency,
) -> ProjectMetadataView:
    current_actor = load_active_actor(db, actor)
    rate_limit = consume_rate_bucket(
        db,
        settings=settings,
        scope="project-create",
        subject=str(current_actor.id),
        limit=20,
        window_seconds=60 * 60,
    )
    db.commit()
    if not rate_limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many project creations. Try again later.",
            headers={"Retry-After": str(rate_limit.retry_after_seconds)},
        )
    # The limiter committed the prior authentication snapshot. Keep the actor
    # locked through project creation so a committed deactivation wins or waits.
    current_actor = load_active_actor(db, actor, for_update=True)
    name_key = project_name_key(payload.name)
    if _duplicate_name(db, current_actor.id, name_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A project with this name already exists in your workspace.",
        )

    project = Project(
        id=uuid.uuid4(),
        name=payload.name,
        name_key=name_key,
        owner_user_id=current_actor.id,
        created_at=datetime.now(UTC),
    )
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _duplicate_name(db, current_actor.id, name_key):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A project with this name already exists in your workspace.",
            ) from exc
        raise

    templates = cast(dict[DocumentKind, ProjectTemplate], request.app.state.project_templates)
    add_template_documents(
        db,
        project.id,
        templates,
        created_at=project.created_at,
    )
    # Authorized document reads materialize the disposable mirror from committed DB heads.

    if current_actor.role == "admin":
        record_audit(
            db,
            action="admin.project.create",
            actor_user_id=current_actor.id,
            project_id=project.id,
            details={"document_kinds": ["project", "agents", "backlog"]},
        )
    db.commit()
    return project_view(project)


@router.get("", response_model=list[ProjectMetadataView])
def list_projects(
    db: DbSession,
    actor: CurrentActor,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> list[ProjectMetadataView]:
    current_actor = load_active_actor(db, actor)
    statement = select(Project).order_by(Project.created_at.desc(), Project.id)
    if current_actor.role != "admin":
        statement = statement.where(Project.owner_user_id == current_actor.id)
    projects = list(db.scalars(statement.offset(offset).limit(limit)).all())
    if current_actor.role == "admin":
        record_audit(
            db,
            action="admin.projects.read",
            actor_user_id=current_actor.id,
            details={
                "limit": limit,
                "offset": offset,
                "returned": len(projects),
                "project_ids": [str(project.id) for project in projects],
            },
        )
        db.commit()
    return [project_view(project) for project in projects]


@router.get("/{project_id}", response_model=ProjectMetadataView)
def get_project(
    project_id: uuid.UUID,
    db: DbSession,
    actor: CurrentActor,
) -> ProjectMetadataView:
    current_actor = load_active_actor(db, actor)
    project = db.scalar(select(Project).where(Project.id == project_id))
    if project is None or (
        current_actor.role != "admin" and project.owner_user_id != current_actor.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if current_actor.role == "admin":
        record_audit(
            db,
            action="admin.project.read",
            actor_user_id=current_actor.id,
            project_id=project.id,
        )
        db.commit()
    return project_view(project)
