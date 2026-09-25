"""Creator-private project metadata reads; project creation is out of scope."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.audit import record_audit
from app.dependencies import CurrentActor, DbSession, load_active_actor
from app.models import Project

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectMetadataView(BaseModel):
    id: uuid.UUID
    name: str
    owner_user_id: uuid.UUID
    created_at: datetime


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
