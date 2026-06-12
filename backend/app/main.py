"""FastAPI application entrypoint.

Wires together configuration, logging, CORS, and the versioned API router.
Database schema is managed by Alembic migrations (NOT create_all) so that
development, testing, and production share one reproducible schema history.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__

# Load-bearing import: pulling in app.db.base registers EVERY ORM model on the
# shared mapper before the first query runs. Without it, SQLAlchemy cannot
# resolve string-based relationships (e.g. relationship("Customer")) and auth
# login fails at runtime with "failed to locate a name". Do not remove.
from app.db import base as _model_registry  # noqa: F401
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    configure_logging()
    log = get_logger("app.startup")
    log.info("starting", project=settings.PROJECT_NAME, environment=settings.ENVIRONMENT)
    yield
    log.info("shutting_down")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=__version__,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.PROJECT_NAME, "docs": "/docs"}
