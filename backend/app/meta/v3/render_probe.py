"""Render-probe orchestration and checks that require renderer evidence."""

import io
import json
import logging
import math
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.dsl.v3_common import (
    MAX_SCENE_SECONDS,
    MIN_CONCLUSION_HOLD_SECONDS,
    MIN_SCENE_SECONDS,
)
from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.quality import QualityCheck, QualityReport
from app.render.full_render import BACKEND_ROOT, RENDER_TIMEOUT_SECONDS


# Distances are compared after each coordinate is divided by the rendered frame
# dimensions. This keeps the same tolerance meaningful at every render quality.
ANCHOR_TOLERANCE = 0.02
_MIN_NON_BACKGROUND_PIXELS = 40

logger = logging.getLogger(__name__)


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
    # The contract runs first and short-circuits so downstream checks may
    # dereference typed fields directly: a manifest missing `frame_size` or
    # carrying `NaN`/zero dimensions would otherwise crash inside
    # `_normalized_distance`/`_pixel_x` before the failing contract check ever
    # got reported.
    contract = check_manifest_contract(manifest)
    if not contract.passed:
        return QualityReport(False, [contract])
    checks = [
        contract,
        check_non_blank_frames(manifest),
        check_frame_bounds(manifest),
        check_visual_overlap(manifest),
        check_relation_alignment(manifest),
        check_callout_collisions(manifest),
        check_state_order(manifest),
        check_declared_path_events(manifest),
        check_dimension_labels(manifest),
        check_final_answer_persistence(manifest),
        check_work_beat_answer_persistence(manifest),
        check_rendered_duration(manifest),
        check_rendered_conclusion_hold(manifest),
    ]
    return QualityReport(all(check.passed for check in checks), checks)


def check_manifest_contract(manifest: dict) -> QualityCheck:
    required = {
        "frame_size": (list, tuple),
        "total_duration_seconds": (int, float),
        "conclusion_hold_seconds": (int, float),
        "final_beat_observed": bool,
        "simple_reveal_mode": (str, type(None)),
        "frames": list,
        "safe_frame": (list, tuple),
        "visual_bounds": dict,
        "anchors": dict,
        "relations": dict,
        "declared_relations": list,
        "path_events": list,
        "declared_path_events": list,
        "dimension_labels": dict,
        "declared_dimension_labels": list,
        "state_events": list,
        "declared_state_events": list,
        "final_answer_visible": bool,
        "final_answer_text": (str, type(None)),
        "declared_answer_text": (str, type(None)),
        "work_beat_id": (str, type(None)),
        "work_beat_answer_text": (str, type(None)),
        "declared_work_answer_text": (str, type(None)),
        "answer_anchor": (str, type(None)),
        "derivation_visible": bool,
    }
    for field, expected_type in required.items():
        if field not in manifest or not isinstance(manifest[field], expected_type):
            return _failed("render_probe_contract_invalid", field, "required probe evidence is missing or malformed")
    if len(manifest["frame_size"]) != 2 or not manifest["frames"]:
        return _failed("render_probe_contract_invalid", "frames", "probe needs a frame size and at least one sampled frame")
    # `visual_bounds` non-empty (not merely present) as defense-in-depth: every
    # teeth-bearing subset check downstream is `declared ⊆ observed`, so with no
    # observed bounds the whole manifest would pass by vacuous truth. In
    # production `visual_bounds` is always populated, but a renderer regression
    # or an upstream mis-emit shouldn't be able to skate past the gate.
    if not manifest["visual_bounds"]:
        return _failed("render_probe_contract_invalid", "visual_bounds", "probe emitted no visual bounds to evaluate")
    if not _numbers(manifest["frame_size"], 2):
        return _failed("render_probe_contract_invalid", "frame_size", "frame dimensions must be numeric")
    # A `[0, 500]` or `[NaN, 500]` frame size passes typing but blows up
    # `_normalized_distance` (division by zero) and `_pixel_x`/`_pixel_y` on
    # first use, so the contract rejects any non-finite or non-positive
    # dimension before downstream checks touch it.
    if not all(math.isfinite(v) and v > 0 for v in manifest["frame_size"]):
        return _failed("render_probe_contract_invalid", "frame_size", "frame dimensions must be positive and finite")
    for field in ("total_duration_seconds", "conclusion_hold_seconds"):
        if not math.isfinite(manifest[field]):
            # `NaN` compares False against every finite bound, so a manifest
            # carrying `NaN` here would silently pass both timing checks. Reject
            # up front rather than teaching each check to look for it.
            return _failed("render_probe_contract_invalid", field, "timing values must be finite")
    # Required, not defaulted: without it `check_frame_bounds` has no box to
    # compare against, and silently falling back to the physical frame would
    # reinstate the unguarded margin this evidence exists to close.
    if not _numbers(manifest["safe_frame"], 4):
        return _failed("render_probe_contract_invalid", "safe_frame", "the safe frame must be four numeric coordinates")
    if not all(_frame_contract(frame) for frame in manifest["frames"]):
        return _failed("render_probe_contract_invalid", "frames", "sampled frames need beat, time, and path evidence")
    if not all(_numbers(bounds, 4) for bounds in manifest["visual_bounds"].values()):
        return _failed("render_probe_contract_invalid", "visual_bounds", "visual bounds must be four numeric coordinates")
    if not all(_numbers(anchor, 2) for anchor in manifest["anchors"].values()):
        return _failed("render_probe_contract_invalid", "anchors", "anchors must be two numeric coordinates")
    if not all(_relation_contract(relation) for relation in manifest["relations"].values()):
        return _failed("render_probe_contract_invalid", "relations", "relation evidence is incomplete")
    if not all(isinstance(value, str) for field in ("declared_relations", "path_events", "declared_path_events", "declared_dimension_labels") for value in manifest[field]):
        return _failed("render_probe_contract_invalid", "manifest", "declared and observed identifiers must be strings")
    if not all(_state_contract(event, observed=True) for event in manifest["state_events"]):
        return _failed("render_probe_contract_invalid", "state_events", "observed state evidence is incomplete")
    if not all(_state_contract(event, observed=False) for event in manifest["declared_state_events"]):
        return _failed("render_probe_contract_invalid", "declared_state_events", "declared state evidence is incomplete")
    return _passed("render_probe_contract_invalid", "manifest")


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
            # Reviewer-facing failures carry no generated content or paths (see
            # this module's docstring), so the traceback goes to the operator log
            # instead of into the failure. Without it a probe crash left three
            # burnt generation attempts and no way to tell what broke.
            logger.error(
                "Probe renderer exited %s. stderr:\n%s",
                result.returncode, _tail(result.stderr),
            )
            raise _structured_failure_from_probe(manifest_path) or _probe_failure(
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
    """Every visible bound must stay inside the safe frame layout targets.

    Comparing against the *physical* frame instead left the margin between the
    two unguarded -- 16px horizontally at a 900px-wide render. A visual resting
    in that band reads as touching the frame edge while the gate reports it
    comfortably inside, which is how the published perimeter lesson shipped with
    its formula label against the left edge.
    """
    safe_frame = manifest.get("safe_frame", [])
    for ref, bounds in manifest.get("visual_bounds", {}).items():
        if not _inside(bounds, safe_frame):
            return _failed("frame_out_of_bounds", f"visual_bounds.{ref}", "a visible bound extends outside the safe frame")
    for ref, relation in manifest.get("relations", {}).items():
        if not _inside(relation.get("bounds", []), safe_frame):
            return _failed("frame_out_of_bounds", f"relations.{ref}.bounds", "a callout bound extends outside the safe frame")
    return _passed("frame_out_of_bounds", "visual_bounds")


def check_dimension_labels(manifest: dict) -> QualityCheck:
    """A measurement visual must render both of its measurements as text.

    Nothing in either gate layer confirmed that a `rectangle_measurement` put its
    length and width on screen, so a perimeter lesson could ship as a bare
    rectangle with no numbers to add up -- geometrically correct and
    pedagogically empty.
    """
    observed = manifest.get("dimension_labels", {})
    for ref in manifest.get("declared_dimension_labels", []):
        labels = observed.get(ref, {})
        for part in ("length_label", "width_label"):
            if not str(labels.get(part, "")).strip():
                return _failed(
                    "dimension_label_missing", f"dimension_labels.{ref}.{part}",
                    "a measured visual rendered no text for this dimension",
                )
    return _passed("dimension_label_missing", "dimension_labels")


def check_visual_overlap(manifest: dict) -> QualityCheck:
    """No two visuals may occupy the same pixels.

    `check_callout_collisions` only compares callouts against visuals, so two
    overlapping visuals were unchecked in either gate layer -- and text
    overrunning its reserved box collides with a neighbouring visual long before
    it reaches any frame edge.
    """
    bounds_by_ref = sorted(manifest.get("visual_bounds", {}).items())
    for index, (ref, bounds) in enumerate(bounds_by_ref):
        for other_ref, other_bounds in bounds_by_ref[index + 1:]:
            if _overlap(bounds, other_bounds):
                return _failed(
                    "visual_overlap", f"visual_bounds.{ref}",
                    f"visual bounds overlap those of {other_ref}",
                )
    return _passed("visual_overlap", "visual_bounds")


def check_relation_alignment(manifest: dict) -> QualityCheck:
    width, height = _frame_size(manifest)
    for ref, relation in manifest.get("relations", {}).items():
        target, tip = relation.get("target"), relation.get("tip")
        if not _points(target, tip) or _normalized_distance(target, tip, width, height) > ANCHOR_TOLERANCE:
            return _failed("anchor_alignment_mismatch", f"relations.{ref}", "callout tip is not aligned to its semantic anchor")
    missing = set(manifest.get("declared_relations", [])) - set(manifest.get("relations", {}))
    if missing:
        return _failed("rendered_relation_mismatch", "relations", "a declared relation was not rendered")
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
    observed = {(event.get("target"), event.get("role")) for event in manifest.get("state_events", [])}
    declared = {(event.get("target"), event.get("role")) for event in manifest.get("declared_state_events", [])}
    if not declared <= observed:
        return _failed("rendered_state_mismatch", "state_events", "a declared semantic state was not rendered")

    # Keyed on the program's declared answer anchor. The previous form named the
    # literal target `values.item[3]`, which is the demo fixture's ref and not
    # the published template's -- so on that template the check fell straight
    # through its own "no events" escape and never ran. It also required the
    # anchored item to pass through `neutral`, which is only true of a
    # collection that starts `neutral`.
    anchor = manifest.get("answer_anchor")
    if anchor is None:
        return _passed("state_order_invalid", "state_events")
    events = manifest.get("state_events", [])
    focus_seconds = [
        event.get("seconds") for event in events
        if event.get("target") == anchor and event.get("role") == "focus"
    ]
    if not focus_seconds:
        return _failed("state_order_invalid", "state_events", "the answer target never receives focus")
    collection = anchor.split(".", 1)[0]
    siblings = [
        event for event in events
        if str(event.get("target", "")).startswith(f"{collection}.item[")
        and event.get("target") != anchor
    ]
    if any(event.get("role") == "focus" for event in siblings):
        return _failed("state_order_invalid", "state_events", "a value other than the answer receives focus")
    dismissed = [event.get("seconds") for event in siblings if event.get("role") == "neutral"]
    if dismissed and min(focus_seconds) < max(dismissed):
        return _failed("state_order_invalid", "state_events", "the answer is focused before the other values are dismissed")
    return _passed("state_order_invalid", "state_events")


def check_declared_path_events(manifest: dict) -> QualityCheck:
    declared = set(manifest.get("declared_path_events", []))
    observed = set(manifest.get("path_events", []))
    missing = declared - observed
    if missing:
        return _failed("undeclared_path_event", "path_events", "a declared semantic path was not rendered")
    return _passed("undeclared_path_event", "path_events")


def check_rendered_duration(manifest: dict) -> QualityCheck:
    """The renderer's actually-elapsed time must sit within the scene budget.

    Read off `scene.elapsed` in the probe subprocess, so this catches a drift
    between the compiled `total_duration_seconds` the static gate approved and
    what manim wall-clocked -- a class of failure `check_duration` cannot see.
    """
    duration = manifest.get("total_duration_seconds", 0)
    if duration > MAX_SCENE_SECONDS + 1e-9:
        return _failed(
            "timeline_over_budget", "total_duration_seconds",
            "rendered scene exceeded the 24-second budget",
        )
    if duration + 1e-9 < MIN_SCENE_SECONDS:
        return _failed(
            "timeline_duration_out_of_bounds", "total_duration_seconds",
            "rendered scene was shorter than the 12-second minimum",
        )
    return _passed("timeline_duration", "total_duration_seconds")


def check_rendered_conclusion_hold(manifest: dict) -> QualityCheck:
    """The final beat must produce at least 1.5s of hold at render time.

    Static `check_conclusion_hold` bounds the shortest declared action in the
    conclude beat, but nothing observed the hold actually reaching the frame.
    Here `conclusion_hold_seconds` is the interval from the last final-beat
    semantic play's start to scene end, and `final_beat_observed` records
    whether that final beat produced any semantic play at all -- a conclude
    beat that compiled to nothing must fail the gate rather than fall back to
    an earlier beat's timing.
    """
    if not manifest.get("final_beat_observed", False):
        return _failed(
            "conclusion_hold_too_short", "final_beat_observed",
            "the final beat produced no semantic play at render time",
        )
    hold = manifest.get("conclusion_hold_seconds", 0)
    if hold + 1e-9 < MIN_CONCLUSION_HOLD_SECONDS:
        return _failed(
            "conclusion_hold_too_short", "conclusion_hold_seconds",
            "rendered conclusion holds for less than 3 seconds",
        )
    return _passed("conclusion_hold_too_short", "conclusion_hold_seconds")


def check_final_answer_persistence(manifest: dict) -> QualityCheck:
    if not manifest.get("final_answer_visible", False):
        return _failed("final_answer_not_persistent", "final_answer_visible", "evaluated answer is absent from the final frame")
    # Present is not the same as resolved. This check used to end above, and passed
    # on every lesson while the frame read "2.75 x 1000 = ? meters": the conclude
    # beat's recolour and its `show_answer_stage(value)` were two competing
    # transforms on one mobject, so the answer never resolved on screen. Hold the
    # final frame to what the last staging action says it should say.
    observed, declared = manifest.get("final_answer_text"), manifest.get("declared_answer_text")
    if declared is not None and observed != declared:
        return _failed(
            "final_answer_not_persistent", "final_answer_text",
            "final frame does not show the resolved answer",
        )
    return _passed("final_answer_not_persistent", "final_answer_visible")


def check_work_beat_answer_persistence(manifest: dict) -> QualityCheck:
    """The work beat's captured frame must SHOW the work stage.

    The conclude beat's `Transform` from `work` to `value` morphs one point set
    onto another over roughly a second, and for most of that second the answer
    is a smear of interpolated glyphs -- `8 x 3 = ?` does not become `8 x 3 = 24`
    by substitution but by dragging outlines. The same is true of the beat that
    transforms into `work`: the frame captured at that beat's end reads as a
    smear unless the transition has settled by then.

    Nothing observed the smear settling. `check_final_answer_persistence` holds
    the FINAL frame to the timeline's declared stage; every intermediate beat
    was assumed to settle without evidence. This is the same class of gap that
    let #77's central defect through -- every gate checked the timeline, none
    checked the frame -- and would let a future change that leaves the answer
    mid-morph when the beat ends slip past a green suite.

    A lesson whose answer expression has no arithmetic emits no `show_answer_
    stage(work)` action, so `declared_work_answer_text` is `None`. Treat that
    as "nothing to hold to" and pass, matching how the final-frame check
    handles a program that stages its answer nowhere.
    """
    declared = manifest.get("declared_work_answer_text")
    if declared is None:
        return _passed("work_answer_not_persistent", "declared_work_answer_text")
    observed = manifest.get("work_beat_answer_text")
    if observed != declared:
        return _failed(
            "work_answer_not_persistent", "work_beat_answer_text",
            "work beat's captured frame does not show the work stage of the answer",
        )
    return _passed("work_answer_not_persistent", "work_beat_answer_text")


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
    contract = check_manifest_contract(manifest)
    if not contract.passed:
        raise _probe_failure(
            "render_probe_contract_invalid", contract.path, "complete probe evidence",
            contract.detail, "regenerate the candidate and retry the preview",
        )
    return manifest


def _attach_frame_evidence(manifest: dict, scratch_dir: Path) -> None:
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
        pixels, _ = _non_background_pixels(frame_path.read_bytes())
        frame["non_background_pixels"] = pixels


def _non_background_pixels(png_bytes: bytes) -> tuple[int, tuple[int, int]]:
    from PIL import Image

    with Image.open(io.BytesIO(png_bytes)) as image:
        rgb = image.convert("RGB")
        background = rgb.getpixel((0, 0))
        counts = rgb.getcolors(maxcolors=rgb.width * rgb.height) or []
        return sum(count for count, color in counts if color != background), (rgb.width, rgb.height)


def _frame_size(manifest: dict) -> tuple[float, float]:
    # `check_manifest_contract` runs first and rejects any manifest whose
    # `frame_size` isn't two numbers, so no silent fallback is needed here.
    size = manifest["frame_size"]
    return float(size[0]), float(size[1])


def _frame_contract(frame) -> bool:
    return (
        isinstance(frame, dict)
        and isinstance(frame.get("beat_id"), str)
        and isinstance(frame.get("seconds"), (int, float))
        and isinstance(frame.get("path"), str)
    )


def _relation_contract(relation) -> bool:
    return (
        isinstance(relation, dict)
        and isinstance(relation.get("target_anchor"), str)
        and _numbers(relation.get("target"), 2)
        and _numbers(relation.get("tip"), 2)
        and _numbers(relation.get("bounds"), 4)
    )


def _state_contract(event, *, observed: bool) -> bool:
    return (
        isinstance(event, dict)
        and isinstance(event.get("target"), str)
        and isinstance(event.get("role"), str)
        and (not observed or isinstance(event.get("seconds"), (int, float)))
    )


def _numbers(value, count: int) -> bool:
    return (
        isinstance(value, (list, tuple)) and len(value) == count
        and all(isinstance(item, (int, float)) for item in value)
    )


def _inside(bounds, frame) -> bool:
    if not (isinstance(frame, (list, tuple)) and len(frame) == 4):
        return False
    return (
        isinstance(bounds, (list, tuple)) and len(bounds) == 4
        and frame[0] <= bounds[0] <= bounds[2] <= frame[2]
        and frame[1] <= bounds[1] <= bounds[3] <= frame[3]
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


def _structured_failure_from_probe(manifest_path: Path) -> V3ValidationError | None:
    """The failure the worker rejected the candidate with, if it recorded one.

    Keeps a `below_minimum_text_scale` (or any other structured rejection) raised
    inside the subprocess reportable as itself, with its own actionable hint,
    rather than flattened into an opaque `render_probe_failed`.
    """
    failure_path = manifest_path.with_suffix(".failure.json")
    try:
        payload = json.loads(failure_path.read_text())
        return V3ValidationError(V3Failure(**payload))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _tail(stderr: str, limit: int = 4000) -> str:
    stderr = (stderr or "").strip()
    return stderr[-limit:] if len(stderr) > limit else stderr
