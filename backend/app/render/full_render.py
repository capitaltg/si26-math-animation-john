import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
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
    """Raised when the Manim subprocess exceeds RENDER_TIMEOUT_SECONDS."""


def render_scene_to_mp4(template: TemplateRef, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="full", chained=False)


def render_scene_thumbnail(template: TemplateRef, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="thumbnail", chained=False)


def render_chained_scene_to_mp4(template: TemplateRef, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="full", chained=True)


def render_chained_scene_thumbnail(template: TemplateRef, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="thumbnail", chained=True)


def _run_render_worker(
    template: TemplateRef, params: BaseModel, output_path: Path, mode: str, chained: bool
) -> Path:
    scratch_dir = tempfile.mkdtemp()
    try:
        params_json_path = Path(scratch_dir) / "params.json"
        params_json_path.write_text(json.dumps(params.model_dump(mode="json")))

        with _RENDER_SEMAPHORE:
            try:
                result = subprocess.run(
                    [
                        sys.executable, "-m", "app.render.render_worker",
                        template.model_dump_json(), str(params_json_path), str(output_path), mode, scratch_dir,
                        "chained" if chained else "solo",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=RENDER_TIMEOUT_SECONDS,
                    cwd=str(BACKEND_ROOT),
                )
            except subprocess.TimeoutExpired as exc:
                raise RenderTimeout(
                    f"Render subprocess timed out after {RENDER_TIMEOUT_SECONDS}s:\n"
                    f"{exc.stdout or ''}\n{exc.stderr or ''}"
                ) from exc

        if result.returncode != 0:
            raise RuntimeError(f"Render subprocess failed:\n{result.stdout}\n{result.stderr}")
        return output_path
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
