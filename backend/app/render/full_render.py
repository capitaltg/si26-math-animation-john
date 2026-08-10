import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from pydantic import BaseModel

from app.models.scene import TemplateRef

RENDER_TIMEOUT_SECONDS = 120
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _parallel_cap() -> int:
    raw = os.environ.get("RENDER_MAX_PARALLEL", "2")
    try:
        value = int(raw)
    except ValueError:
        value = 2
    return max(1, value)


#: Bounds concurrent Manim video-render subprocesses across all requests
#: (per-process, not per-session). Thumbnails share this cap intentionally —
#: they invoke the same worker; split into two semaphores if that starves either.
_RENDER_SEMAPHORE = threading.BoundedSemaphore(_parallel_cap())


class RenderTimeout(RuntimeError):
    """Raised when the Manim subprocess exceeds RENDER_TIMEOUT_SECONDS,
    when the caller's whole-job deadline expires while waiting for a render
    slot, or when the remaining budget can't cover the subprocess timeout.
    """


def render_scene_to_mp4(
    template: TemplateRef,
    params: BaseModel,
    output_path: Path,
    *,
    deadline: float | None = None,
) -> Path:
    return _run_render_worker(
        template, params, output_path, mode="full", chained=False, deadline=deadline
    )


def render_scene_thumbnail(
    template: TemplateRef,
    params: BaseModel,
    output_path: Path,
    *,
    deadline: float | None = None,
) -> Path:
    return _run_render_worker(
        template, params, output_path, mode="thumbnail", chained=False, deadline=deadline
    )


def render_chained_scene_to_mp4(
    template: TemplateRef,
    params: BaseModel,
    output_path: Path,
    *,
    deadline: float | None = None,
) -> Path:
    return _run_render_worker(
        template, params, output_path, mode="full", chained=True, deadline=deadline
    )


def render_chained_scene_thumbnail(
    template: TemplateRef,
    params: BaseModel,
    output_path: Path,
    *,
    deadline: float | None = None,
) -> Path:
    return _run_render_worker(
        template, params, output_path, mode="thumbnail", chained=True, deadline=deadline
    )


def _remaining_budget(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return deadline - time.monotonic()


def _run_render_worker(
    template: TemplateRef,
    params: BaseModel,
    output_path: Path,
    mode: str,
    chained: bool,
    deadline: float | None,
) -> Path:
    scratch_dir = tempfile.mkdtemp()
    try:
        params_json_path = Path(scratch_dir) / "params.json"
        params_json_path.write_text(json.dumps(params.model_dump(mode="json")))

        # Wait for a render slot, but not past the caller's whole-job deadline.
        # `Semaphore.acquire(timeout=None)` blocks indefinitely; we only pass a
        # timeout when a deadline was provided.
        remaining = _remaining_budget(deadline)
        if remaining is not None and remaining <= 0:
            raise RenderTimeout("job deadline exceeded before acquiring render slot")
        acquired = (
            _RENDER_SEMAPHORE.acquire(timeout=remaining)
            if remaining is not None
            else _RENDER_SEMAPHORE.acquire()
        )
        if not acquired:
            raise RenderTimeout(
                "job deadline exceeded while waiting for a render slot"
            )
        try:
            # Cap the subprocess timeout by the remaining deadline so a single
            # Manim invocation can't overshoot the whole-job budget.
            subprocess_timeout: float = RENDER_TIMEOUT_SECONDS
            remaining = _remaining_budget(deadline)
            if remaining is not None:
                if remaining <= 0:
                    raise RenderTimeout(
                        "job deadline exceeded before subprocess start"
                    )
                subprocess_timeout = min(RENDER_TIMEOUT_SECONDS, remaining)
            try:
                result = subprocess.run(
                    [
                        sys.executable, "-m", "app.render.render_worker",
                        template.model_dump_json(), str(params_json_path), str(output_path), mode, scratch_dir,
                        "chained" if chained else "solo",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=subprocess_timeout,
                    cwd=str(BACKEND_ROOT),
                )
            except subprocess.TimeoutExpired as exc:
                raise RenderTimeout(
                    f"Render subprocess timed out after {subprocess_timeout:.1f}s:\n"
                    f"{exc.stdout or ''}\n{exc.stderr or ''}"
                ) from exc
        finally:
            _RENDER_SEMAPHORE.release()

        if result.returncode != 0:
            raise RuntimeError(f"Render subprocess failed:\n{result.stdout}\n{result.stderr}")
        return output_path
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
