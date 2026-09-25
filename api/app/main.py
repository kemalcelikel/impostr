"""FastAPI application and same-origin API routing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.admin import router as admin_router
from app.auth import router as auth_router
from app.config import AppSettings
from app.database import get_database_engine
from app.dependencies import require_browser_mutation
from app.passwords import dummy_password_hash
from app.projects import router as projects_router


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if application.state.settings is None:
        application.state.settings = AppSettings.from_environment()
    dummy_password_hash()
    yield


def create_app(
    engine: Engine | None = None,
    settings: AppSettings | None = None,
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

    api_router = APIRouter(
        prefix="/api",
        dependencies=[Depends(require_browser_mutation)],
    )
    api_router.include_router(auth_router)
    api_router.include_router(admin_router)
    api_router.include_router(projects_router)
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

        response.headers["Cache-Control"] = "no-store"
        return HealthResponse(status="ok")

    return application


app = create_app()
