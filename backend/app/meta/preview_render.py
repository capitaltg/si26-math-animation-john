import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app.meta.artifacts import store_artifact
from app.meta.dsl.animation import CompiledAnimation
from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.v3.render_probe import ProbeRequest, run_probe_subprocess, validate_rendered_quality
from app.render.full_render import BACKEND_ROOT, RENDER_TIMEOUT_SECONDS

# A thumbnail is rendered with save_last_frame, so it captures the animation's
# final state. Manim's default camera background is solid black, and a mobject
# only reaches a frame if some timed action (appear/transform/...) actually
# added it to the scene. An animation document that merely *builds* layout/visual
# nodes without ever appearing them therefore renders an all-black frame -- and,
# because such a scene also has zero playback duration, its full MP4 render
# produces no video file at all. Rejecting a blank preview here (so the draft
# fails validation and can never be approved) is the single check that catches
# both symptoms at the layer that matters: the actual rendered pixels.
_MIN_NON_BACKGROUND_PIXELS = 40


def _frame_is_blank(png_bytes: bytes) -> bool:
    from PIL import Image

    with Image.open(io.BytesIO(png_bytes)) as image:
        rgb = image.convert("RGB")
        background = rgb.getpixel((0, 0))
        non_background = sum(
            count for count, color in (rgb.getcolors(maxcolors=rgb.width * rgb.height) or [])
            if color != background
        )
    return non_background < _MIN_NON_BACKGROUND_PIXELS


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

        preview_bytes = output_path.read_bytes()
        if _frame_is_blank(preview_bytes):
            raise RuntimeError(
                "Preview render produced a blank frame: the animation never displays "
                "any content. Every visual must be shown with an 'appear' action (and "
                "held with a 'wait') for the template to render."
            )
        return store_artifact(artifact_root, preview_bytes)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


def render_preview_and_probe(
    scene_program: SceneProgramDocument,
    known_fields,
    values: dict,
    artifact_root: Path,
):
    request = ProbeRequest(
        scene_program=scene_program,
        known_fields=sorted(known_fields),
        field_values=values,
    )
    output = run_probe_subprocess(request)
    validate_rendered_quality(output.manifest).require_passed()
    artifact_hash = store_artifact(artifact_root, output.final_frame_bytes)
    return artifact_hash, output.manifest
