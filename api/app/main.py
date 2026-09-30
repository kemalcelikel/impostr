"""FastAPI application and same-origin API routing."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.admin import router as admin_router
from app.auth import router as auth_router
from app.backlog_tasks import router as backlog_tasks_router
from app.config import AppSettings
from app.database import get_database_engine
from app.dependencies import require_browser_mutation
from app.document_contract import DocumentKind
from app.document_pair_approvals import router as document_pair_approvals_router
from app.passwords import dummy_password_hash
from app.project_documents import (
    router as project_documents_router,
)
from app.project_documents import (
    seed_legacy_project_documents,
)
from app.project_templates import (
    ProjectTemplate,
    default_template_root,
    load_project_templates,
)
from app.projects import router as projects_router
from app.workspaces import WorkspaceStore

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if application.state.settings is None:
        application.state.settings = AppSettings.from_environment()
    dummy_password_hash()
    database_engine = application.state.database_engine or get_database_engine()
    templates = load_project_templates(application.state.template_root)
    application.state.project_templates = templates
    application.state.project_documents_ready = False
    try:
        _initialize_project_documents(application, database_engine, templates)
    except SQLAlchemyError:
        # Keep the API available for its health endpoint during a DB outage. The
        # first healthy probe retries legacy template backfill from PostgreSQL.
        logger.warning("Project document initialization deferred until the database is available.")
    yield


def _initialize_project_documents(
    application: FastAPI,
    database_engine: Engine,
    templates: dict[DocumentKind, ProjectTemplate],
) -> None:
    seed_legacy_project_documents(database_engine, templates)
    application.state.project_documents_ready = True


def create_app(
    engine: Engine | None = None,
    settings: AppSettings | None = None,
    *,
    workspace_root: Path | None = None,
    template_root: Path | None = None,
) -> FastAPI:
    """Create the API with injectable persistence and origin settings for tests."""
    application = FastAPI(
        title="Impostr API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.database_engine = engine
    application.state.settings = settings
    application.state.workspace_store = WorkspaceStore(
        workspace_root
        if workspace_root is not None
        else Path(os.environ.get("IMPOSTR_WORKSPACE_ROOT", "/workspaces"))
    )
    application.state.template_root = template_root or default_template_root()

    api_router = APIRouter(
        prefix="/api",
        dependencies=[Depends(require_browser_mutation)],
    )
    api_router.include_router(auth_router)
    api_router.include_router(admin_router)
    api_router.include_router(projects_router)
    api_router.include_router(project_documents_router)
    api_router.include_router(backlog_tasks_router)
    api_router.include_router(document_pair_approvals_router)
    application.include_router(api_router)

    @application.middleware("http")
    async def disable_api_caching(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @application.exception_handler(SQLAlchemyError)
    def database_failure(_: Request, __: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Database unavailable"},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @application.get("/api/health", response_model=HealthResponse, tags=["health"])
    def health(response: Response) -> HealthResponse:
        database_engine = engine if engine is not None else get_database_engine()
        try:
            with database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            ) from exc

        if not application.state.project_documents_ready:
            try:
                _initialize_project_documents(
                    application,
                    database_engine,
                    application.state.project_templates,
                )
            except SQLAlchemyError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database unavailable",
                ) from exc

        response.headers["Cache-Control"] = "no-store"
        return HealthResponse(status="ok")

    return application


app = create_app()
