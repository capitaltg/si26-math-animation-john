import json
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

from app.models.scene import TemplateName


def render_scene_to_mp4(template: TemplateName, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="full")


def render_scene_thumbnail(template: TemplateName, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="thumbnail")


def _run_render_worker(template: TemplateName, params: BaseModel, output_path: Path, mode: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    params_json_path = output_path.with_suffix(".params.json")
    params_json_path.write_text(json.dumps(params.model_dump(mode="json")))

    result = subprocess.run(
        [
            sys.executable, "-m", "app.render.render_worker",
            template.value, str(params_json_path), str(output_path), mode,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Render subprocess failed:\n{result.stdout}\n{result.stderr}")
    return output_path
