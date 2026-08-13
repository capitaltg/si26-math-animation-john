import asyncio
import logging
from contextlib import asynccontextmanager

from botocore.exceptions import NoCredentialsError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.middleware import ClientIPMiddleware
from app.quota import BedrockDisabled, BedrockGuardUnavailable, BedrockQuotaExceeded
from app.routes import router, store

logger = logging.getLogger(__name__)


async def _periodic_media_sweep(interval: int, max_bytes: int):
    while True:
        try:
            await asyncio.sleep(interval)
            evicted = store.enforce_global_cap(max_bytes)
            if evicted:
                logger.info("Evicted %d media entries to hold media volume cap", evicted)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Periodic media sweep failed")


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

    settings = get_settings()
    sweep_task: asyncio.Task | None = None
    # Both must be strictly positive — interval 0 would asyncio.sleep(0) in a
    # tight loop and pin a CPU. A misconfigured .env should not brick the app,
    # so we log and skip rather than raise.
    if settings.media_max_bytes > 0 and settings.media_sweep_interval_seconds > 0:
        sweep_task = asyncio.create_task(
            _periodic_media_sweep(
                settings.media_sweep_interval_seconds, settings.media_max_bytes
            )
        )
    elif settings.media_max_bytes > 0:
        logger.warning(
            "MEDIA_MAX_BYTES is set but MEDIA_SWEEP_INTERVAL_SECONDS is not > 0; "
            "periodic media sweep disabled"
        )
    try:
        yield
    finally:
        if sweep_task is not None:
            sweep_task.cancel()
            try:
                await sweep_task
            except (asyncio.CancelledError, Exception):
                pass


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

    @app.exception_handler(BedrockGuardUnavailable)
    async def _bedrock_guard_unavailable(_request, exc: BedrockGuardUnavailable):
        # Fail-closed: rate-limit backend down while caps are configured. We
        # refuse the call rather than let it hit AWS unmetered.
        logger.error("Bedrock rate-limit backend unreachable: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "AI features are temporarily unavailable — please retry shortly."},
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

    cors_origins = [
        o.strip() for o in get_settings().cors_allow_origins.split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # ClientIPMiddleware must run BEFORE any code that reads the client-IP
    # ContextVar. Starlette runs middleware in reverse-add order, so this
    # add_middleware() call after CORS still lands it outside CORS.
    app.add_middleware(ClientIPMiddleware)
    @app.get("/healthz", include_in_schema=False)
    async def _healthz():
        # Liveness only — cheap, no external dependencies. Docker HEALTHCHECK
        # curls this; deep dependency checks would flap the healthcheck if
        # Postgres/Redis blip briefly and force nginx to drain the backend.
        return {"status": "ok"}

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
