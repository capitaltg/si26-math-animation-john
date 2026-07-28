import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app.meta.artifacts import store_artifact
from app.meta.dsl.animation import CompiledAnimation
from app.render.full_render import BACKEND_ROOT, RENDER_TIMEOUT_SECONDS


def render_and_store_preview(
    compiled_animation: CompiledAnimation,
    known_fields: frozenset[str],
    field_values: dict,
    artifact_root: Path,
) -> str:
    scratch_dir = tempfile.mkdtemp()
    try:
        anim_path = Path(scratch_dir) / "animation_document.json"
        anim_path.write_text(compiled_animation.document.model_dump_json())
        known_fields_path = Path(scratch_dir) / "known_fields.json"
        known_fields_path.write_text(json.dumps(sorted(known_fields)))
        values_path = Path(scratch_dir) / "field_values.json"
        values_path.write_text(json.dumps(field_values))
        output_path = Path(scratch_dir) / "preview.png"

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "app.render.dynamic_render_worker",
                    str(anim_path), str(known_fields_path), str(values_path),
                    str(output_path), "thumbnail", scratch_dir,
                ],
                capture_output=True,
                text=True,
                timeout=RENDER_TIMEOUT_SECONDS,
                cwd=str(BACKEND_ROOT),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Preview render timed out after {RENDER_TIMEOUT_SECONDS}s:\n"
                f"{exc.stdout or ''}\n{exc.stderr or ''}"
            ) from exc

        if result.returncode != 0:
            raise RuntimeError(f"Preview render failed:\n{result.stdout}\n{result.stderr}")

        return store_artifact(artifact_root, output_path.read_bytes())
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
