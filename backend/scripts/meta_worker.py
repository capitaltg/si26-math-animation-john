"""Dev-only polling worker for queued meta-template generation jobs."""

import logging
import os
import socket
from time import sleep
from typing import Callable

from app.config import get_settings
from app.meta.generation_pipeline import run_generation_job

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 2.0


def run_worker(
    *,
    owner: str,
    process_one: Callable = run_generation_job,
    wait: Callable[[float], None] = sleep,
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> None:
    """Process queued jobs until interrupted.

    Successful work drains immediately. An empty queue, a handled generation
    failure (both represented by ``None``), or an unexpected exception waits
    before the next poll to avoid a busy loop.
    """
    while True:
        try:
            draft = process_one(owner=owner)
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("Unexpected meta worker iteration failure")
            wait(poll_interval)
            continue

        if draft is None:
            wait(poll_interval)
            continue

        logger.info("Generated meta-template draft %s", draft.id)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    if not settings.meta_templates_enabled or not settings.meta_codegen_enabled:
        logger.info("Meta-template code generation is disabled; worker exiting")
        return 0

    owner = f"{socket.gethostname()}:{os.getpid()}"
    logger.info("Meta-template worker starting as %s", owner)
    try:
        run_worker(owner=owner)
    except KeyboardInterrupt:
        logger.info("Meta-template worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
