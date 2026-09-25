"""FastAPI entry point for the same-origin health endpoint."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_database_engine


class HealthResponse(BaseModel):
    status: str


def create_app(engine: Engine | None = None) -> FastAPI:
    """Create the API; an injected engine keeps health behavior testable."""
    application = FastAPI(
        title="Impostr API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
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
