"""Dev-only meta-template codegen worker.

Phase 1: the codegen path does not exist yet, so this worker exits immediately
unless meta_codegen_enabled is set. The claim/complete/fail primitives it will
drive live in app.meta.jobs and are exercised by unit tests today.
"""
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    if not settings.meta_codegen_enabled:
        logger.info("meta_codegen_enabled is False; worker is a no-op in Phase 1")
        return 0
    raise NotImplementedError("codegen worker loop lands in Phase 3")


if __name__ == "__main__":
    raise SystemExit(main())
