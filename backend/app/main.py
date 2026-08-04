import logging

from botocore.exceptions import NoCredentialsError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routes import router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="Math Animation Generator")

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
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
