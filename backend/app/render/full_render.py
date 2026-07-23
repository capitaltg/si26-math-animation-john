import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

from app.models.scene import TemplateName

RENDER_TIMEOUT_SECONDS = 120
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def render_scene_to_mp4(template: TemplateName, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="full", chained=False)


def render_scene_thumbnail(template: TemplateName, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="thumbnail", chained=False)


def render_chained_scene_to_mp4(template: TemplateName, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="full", chained=True)


def _run_render_worker(
    template: TemplateName, params: BaseModel, output_path: Path, mode: str, chained: bool
) -> Path:
    scratch_dir = tempfile.mkdtemp()
    try:
        params_json_path = Path(scratch_dir) / "params.json"
        params_json_path.write_text(json.dumps(params.model_dump(mode="json")))

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "app.render.render_worker",
                    template.value, str(params_json_path), str(output_path), mode, scratch_dir,
                    "chained" if chained else "solo",
                ],
                capture_output=True,
                text=True,
                timeout=RENDER_TIMEOUT_SECONDS,
                cwd=str(BACKEND_ROOT),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Render subprocess timed out after {RENDER_TIMEOUT_SECONDS}s:\n"
                f"{exc.stdout or ''}\n{exc.stderr or ''}"
            ) from exc

        if result.returncode != 0:
            raise RuntimeError(f"Render subprocess failed:\n{result.stdout}\n{result.stderr}")
        return output_path
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
