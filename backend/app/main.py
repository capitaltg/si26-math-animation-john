import logging
from contextlib import asynccontextmanager

from botocore.exceptions import NoCredentialsError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.middleware import ClientIPMiddleware
from app.quota import BedrockDisabled, BedrockQuotaExceeded
from app.routes import router, store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Registries live in memory; anything left under root_dir belongs to a
    # previous process and no live entry or reservation can claim it.
    try:
        removed = store.sweep_orphans()
        if removed:
            logger.info("Removed %d orphan session file(s) on startup", removed)
    except Exception:
        logger.exception("Orphan sweep failed during startup")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Math Animation Generator", lifespan=_lifespan)

    @app.exception_handler(NoCredentialsError)
    async def missing_aws_credentials(_request, exc):
        logger.exception("AWS credentials are unavailable", exc_info=exc)
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Document analysis is unavailable because AWS credentials "
                    "are not configured"
                )
            },
        )

    @app.exception_handler(BedrockDisabled)
    async def _bedrock_disabled(_request, exc: BedrockDisabled):
        logger.warning("Bedrock call refused by kill switch: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "AI features are temporarily disabled by the operator."},
        )

    @app.exception_handler(BedrockQuotaExceeded)
    async def _bedrock_quota(_request, exc: BedrockQuotaExceeded):
        logger.warning("Bedrock quota exhausted: %s", exc)
        message = (
            "The demo has reached its usage quota — please try again later."
            if exc.scope == "global"
            else "You've hit the per-user quota for this demo — please try again in an hour."
        )
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(exc.retry_after_seconds)},
            content={
                "detail": message,
                "scope": exc.scope,
                "retry_after_seconds": exc.retry_after_seconds,
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # ClientIPMiddleware must run BEFORE any code that reads the client-IP
    # ContextVar. Starlette runs middleware in reverse-add order, so this
    # add_middleware() call after CORS still lands it outside CORS.
    app.add_middleware(ClientIPMiddleware)
    app.include_router(router)
    if get_settings().meta_templates_enabled:
        from app.meta.review_api import router as meta_review_router
        from app.meta.teacher_api import router as meta_teacher_router
        # The teacher router first: its /meta/my/... paths must not be swallowed
        # by the admin router's /meta/drafts/{draft_id} style patterns.
        app.include_router(meta_teacher_router)
        app.include_router(meta_review_router)
    return app


app = create_app()
