"""Render-probe orchestration and checks that require renderer evidence."""

import io
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.quality import QualityCheck, QualityReport
from app.render.full_render import BACKEND_ROOT, RENDER_TIMEOUT_SECONDS


# Distances are compared after each coordinate is divided by the rendered frame
# dimensions. This keeps the same tolerance meaningful at every render quality.
ANCHOR_TOLERANCE = 0.02
_MIN_NON_BACKGROUND_PIXELS = 40


@dataclass(frozen=True)
class ProbeRequest:
    scene_program: SceneProgramDocument
    known_fields: list[str]
    field_values: dict


@dataclass(frozen=True)
class ProbeOutput:
    final_frame_bytes: bytes
    manifest: dict


def validate_rendered_quality(manifest: dict) -> QualityReport:
    checks = [
        check_non_blank_frames(manifest),
        check_frame_bounds(manifest),
        check_relation_alignment(manifest),
        check_callout_collisions(manifest),
        check_state_order(manifest),
        check_declared_path_events(manifest),
        check_dimension_attachments(manifest),
        check_final_answer_persistence(manifest),
    ]
    return QualityReport(all(check.passed for check in checks), checks)


def run_probe_subprocess(request: ProbeRequest) -> ProbeOutput:
    """Run the isolated renderer and retain only safe evidence after cleanup."""
    scratch_dir = Path(tempfile.mkdtemp())
    try:
        program_path = scratch_dir / "scene_program.json"
        known_fields_path = scratch_dir / "known_fields.json"
        values_path = scratch_dir / "field_values.json"
        output_path = scratch_dir / "probe-final.png"
        manifest_path = output_path.with_suffix(".json")
        program_path.write_text(request.scene_program.model_dump_json())
        known_fields_path.write_text(json.dumps(sorted(request.known_fields)))
        values_path.write_text(json.dumps(request.field_values))

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "app.render.dynamic_render_worker",
                    str(program_path), str(known_fields_path), str(values_path),
                    str(output_path), "probe", str(scratch_dir),
                ],
                capture_output=True,
                text=True,
                timeout=RENDER_TIMEOUT_SECONDS,
                cwd=str(BACKEND_ROOT),
            )
        except subprocess.TimeoutExpired as exc:
            raise _probe_failure(
                "render_probe_timeout", "render", "probe subprocess completed within the render timeout",
                "probe render timed out", "reduce scene complexity and regenerate the candidate",
            ) from exc

        if result.returncode != 0:
            raise _probe_failure(
                "render_probe_failed", "render", "probe subprocess to complete successfully",
                "probe renderer exited unsuccessfully", "regenerate the candidate and retry the preview",
            )
        if not output_path.is_file() or not manifest_path.is_file():
            raise _probe_failure(
                "render_probe_contract_invalid", "render", "probe frame and manifest files",
                "probe renderer did not produce the required evidence", "regenerate the candidate and retry the preview",
            )

        manifest = _load_manifest(manifest_path)
        _attach_frame_evidence(manifest, scratch_dir)
        return ProbeOutput(final_frame_bytes=output_path.read_bytes(), manifest=manifest)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


def check_non_blank_frames(manifest: dict) -> QualityCheck:
    frames = manifest.get("frames", [])
    if not frames:
        return _failed("blank_probe_frame", "frames", "probe produced no sampled frames")
    blank = next(
        (index for index, frame in enumerate(frames) if frame.get("non_background_pixels", 0) < _MIN_NON_BACKGROUND_PIXELS),
        None,
    )
    if blank is not None:
        return _failed("blank_probe_frame", f"frames[{blank}]", "sampled frame has no visible content")
    return _passed("blank_probe_frame", "frames")


def check_frame_bounds(manifest: dict) -> QualityCheck:
    width, height = _frame_size(manifest)
    for ref, bounds in manifest.get("visual_bounds", {}).items():
        if not _inside(bounds, width, height):
            return _failed("frame_out_of_bounds", f"visual_bounds.{ref}", "a visible bound extends outside the rendered frame")
    for ref, relation in manifest.get("relations", {}).items():
        if not _inside(relation.get("bounds", []), width, height):
            return _failed("frame_out_of_bounds", f"relations.{ref}.bounds", "a callout bound extends outside the rendered frame")
    return _passed("frame_out_of_bounds", "visual_bounds")


def check_relation_alignment(manifest: dict) -> QualityCheck:
    width, height = _frame_size(manifest)
    for ref, relation in manifest.get("relations", {}).items():
        target, tip = relation.get("target"), relation.get("tip")
        if not _points(target, tip) or _normalized_distance(target, tip, width, height) > ANCHOR_TOLERANCE:
            return _failed("anchor_alignment_mismatch", f"relations.{ref}", "callout tip is not aligned to its semantic anchor")
    return _passed("anchor_alignment_mismatch", "relations")


def check_callout_collisions(manifest: dict) -> QualityCheck:
    visual_bounds = manifest.get("visual_bounds", {})
    for relation_ref, relation in manifest.get("relations", {}).items():
        callout_bounds = relation.get("bounds", [])
        target_ref = str(relation.get("target_anchor", "")).split(".", 1)[0]
        for visual_ref, bounds in visual_bounds.items():
            if visual_ref != target_ref and _overlap(callout_bounds, bounds):
                return _failed("callout_collision", f"relations.{relation_ref}.bounds", "callout overlaps an unrelated visual")
    return _passed("callout_collision", "relations")


def check_state_order(manifest: dict) -> QualityCheck:
    events = [event for event in manifest.get("state_events", []) if event.get("target") == "values.item[3]"]
    if not events:
        return _passed("state_order_invalid", "state_events")
    neutral = next((event for event in events if event.get("role") == "neutral"), None)
    focus = next((event for event in events if event.get("role") == "focus"), None)
    if neutral is None or focus is None or neutral.get("seconds", float("inf")) >= focus.get("seconds", float("-inf")):
        return _failed("state_order_invalid", "state_events", "median item must be neutral before it receives focus")
    return _passed("state_order_invalid", "state_events")


def check_declared_path_events(manifest: dict) -> QualityCheck:
    declared = set(manifest.get("declared_path_events", []))
    observed = set(manifest.get("path_events", []))
    missing = declared - observed
    if missing:
        return _failed("undeclared_path_event", "path_events", "a declared semantic path was not rendered")
    return _passed("undeclared_path_event", "path_events")


def check_dimension_attachments(manifest: dict) -> QualityCheck:
    for ref, outcome in manifest.get("dimension_anchor_checks", {}).items():
        passed = outcome if isinstance(outcome, bool) else outcome.get("passed", False)
        if not passed:
            return _failed("dimension_anchor_mismatch", f"dimension_anchor_checks.{ref}", "dimension label is detached from its edge anchor")
    return _passed("dimension_anchor_mismatch", "dimension_anchor_checks")


def check_final_answer_persistence(manifest: dict) -> QualityCheck:
    if not manifest.get("final_answer_visible", False):
        return _failed("final_answer_not_persistent", "final_answer_visible", "evaluated answer is absent from the final frame")
    return _passed("final_answer_not_persistent", "final_answer_visible")


def _load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise _probe_failure(
            "render_probe_contract_invalid", "manifest", "valid probe JSON", "probe manifest is unreadable",
            "regenerate the candidate and retry the preview",
        ) from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("frames"), list):
        raise _probe_failure(
            "render_probe_contract_invalid", "manifest", "manifest object with sampled frames",
            "probe manifest has an invalid shape", "regenerate the candidate and retry the preview",
        )
    return manifest


def _attach_frame_evidence(manifest: dict, scratch_dir: Path) -> None:
    frame_size = None
    for index, frame in enumerate(manifest["frames"]):
        path = Path(str(frame.get("path", "")))
        if path.is_absolute() or path.name != str(frame.get("path", "")):
            raise _probe_failure(
                "render_probe_contract_invalid", f"frames[{index}].path", "relative frame filename",
                "probe frame path is invalid", "regenerate the candidate and retry the preview",
            )
        frame_path = scratch_dir / path
        if not frame_path.is_file():
            raise _probe_failure(
                "render_probe_contract_invalid", f"frames[{index}].path", "sampled frame file",
                "probe frame evidence is missing", "regenerate the candidate and retry the preview",
            )
        pixels, size = _non_background_pixels(frame_path.read_bytes())
        frame["non_background_pixels"] = pixels
        frame_size = frame_size or size
    if frame_size is not None:
        manifest.setdefault("frame_size", list(frame_size))


def _non_background_pixels(png_bytes: bytes) -> tuple[int, tuple[int, int]]:
    from PIL import Image

    with Image.open(io.BytesIO(png_bytes)) as image:
        rgb = image.convert("RGB")
        background = rgb.getpixel((0, 0))
        counts = rgb.getcolors(maxcolors=rgb.width * rgb.height) or []
        return sum(count for count, color in counts if color != background), (rgb.width, rgb.height)


def _frame_size(manifest: dict) -> tuple[float, float]:
    size = manifest.get("frame_size", [1, 1])
    if not isinstance(size, (list, tuple)) or len(size) != 2 or size[0] <= 0 or size[1] <= 0:
        return 1.0, 1.0
    return float(size[0]), float(size[1])


def _inside(bounds, width, height) -> bool:
    return (
        isinstance(bounds, (list, tuple)) and len(bounds) == 4
        and 0 <= bounds[0] <= bounds[2] <= width
        and 0 <= bounds[1] <= bounds[3] <= height
    )


def _points(target, tip) -> bool:
    return (
        isinstance(target, (list, tuple)) and isinstance(tip, (list, tuple))
        and len(target) == len(tip) == 2
    )


def _normalized_distance(target, tip, width, height) -> float:
    return (((target[0] - tip[0]) / width) ** 2 + ((target[1] - tip[1]) / height) ** 2) ** 0.5


def _overlap(first, second) -> bool:
    if not (isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)) and len(first) == len(second) == 4):
        return False
    return max(first[0], second[0]) < min(first[2], second[2]) and max(first[1], second[1]) < min(first[3], second[3])


def _passed(code: str, path: str) -> QualityCheck:
    return QualityCheck(code=code, passed=True, path=path, detail="passed")


def _failed(code: str, path: str, detail: str) -> QualityCheck:
    return QualityCheck(code=code, passed=False, path=path, detail=detail)


def _probe_failure(code: str, path: str, expected: str, observed: str, hint: str) -> V3ValidationError:
    return V3ValidationError(V3Failure(code=code, path=path, expected=expected, observed=observed, hint=hint))
