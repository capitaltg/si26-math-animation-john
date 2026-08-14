import json
import subprocess
import sys

from app.meta.dsl.expression import FieldRefNode, MultiplyNode
from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.resolver import resolve_scene
from app.render.dynamic_render_worker import _declared_state_events, _state_events
from app.render.full_render import BACKEND_ROOT

def _median_plan():
    # Identify-the-median-of-seven plan: it compiles to a scene program with a
    # "median_callout" relation targeting values.item[3].bottom, giving both the
    # probe test and the full/thumbnail-mode test below real (non-trivial)
    # layout and timeline evidence to assert against.
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [{"node": "field_ref", "field": f"v{index}"} for index in range(1, 8)],
        },
        "strategy": "pair_elimination",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together"},
            {"id": "organize_pairs", "kind": "organize", "targets": [{"visual_ref": "values"}],
             "intent": "pair values from the outside inward"},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "identify the unpaired middle value"},
            {"id": "show_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median"},
        ],
        "variation_seed": "worker-probe",
    })


def _median_scene_program():
    return compile_teaching_plan(
        _median_plan(), FieldRefNode(field="v4"), frozenset(f"v{index}" for index in range(1, 8)),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )


def test_worker_thumbnail_mode_renders_a_real_png_from_stored_scene_program(tmp_path):
    # Thumbnail mode loads the persisted SceneProgramDocument directly; exercise
    # that path end to end, separately from probe mode.
    program = _median_scene_program()
    program_path = tmp_path / "scene.json"
    fields_path = tmp_path / "fields.json"
    values_path = tmp_path / "values.json"
    output_path = tmp_path / "thumbnail.png"
    program_path.write_text(program.model_dump_json())
    fields_path.write_text(json.dumps([f"v{index}" for index in range(1, 8)]))
    values_path.write_text(json.dumps({f"v{index}": index for index in range(1, 8)}))

    result = subprocess.run(
        [
            sys.executable, "-m", "app.render.dynamic_render_worker", str(program_path),
            str(fields_path), str(values_path), str(output_path), "thumbnail", str(tmp_path),
        ],
        capture_output=True, text=True, cwd=BACKEND_ROOT, timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_worker_probe_mode_writes_final_frame_and_manifest(tmp_path):
    program = _median_scene_program()
    program_path = tmp_path / "scene.json"
    fields_path = tmp_path / "fields.json"
    values_path = tmp_path / "values.json"
    output_path = tmp_path / "probe-final.png"
    program_path.write_text(program.model_dump_json())
    fields_path.write_text(json.dumps([f"v{index}" for index in range(1, 8)]))
    values_path.write_text(json.dumps({f"v{index}": index for index in range(1, 8)}))

    result = subprocess.run(
        [
            sys.executable, "-m", "app.render.dynamic_render_worker", str(program_path),
            str(fields_path), str(values_path), str(output_path), "probe", str(tmp_path),
        ],
        capture_output=True, text=True, cwd=BACKEND_ROOT, timeout=120,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output_path.with_suffix(".json").read_text())
    assert output_path.read_bytes()
    assert [frame["beat_id"] for frame in manifest["frames"]] == [
        "reveal_values", "organize_pairs", "focus_middle", "show_answer",
    ]
    assert manifest["relations"]["median_callout"]["target_anchor"] == "values.item[3].bottom"
    assert {"target": "values.item[3]", "role": "focus"} in manifest["declared_state_events"]
    assert any(
        event["target"] == "values.item[3]" and event["role"] == "focus"
        for event in manifest["state_events"]
    )
    assert manifest["final_answer_visible"] is True


class _UnusedMeasurer:
    def measure(self, text, font_role):
        raise AssertionError("object_set measurement never calls the text measurer")


def test_declared_and_observed_reveal_roles_agree_for_a_visual_with_no_declared_role():
    """`_declared_state_events` was fixed to read a visual's actual initial
    role instead of a literal `"neutral"`; `_state_events` -- the *observed*
    half of `check_state_order`'s `declared <= observed` comparison -- must
    read it the same way or the two sides drift apart the moment a revealed
    collection isn't `neutral`. `object_set`'s payload carries no
    `initial_role` key at all, so `_initial_role` falls back to the shape
    derivation and returns `"structure"`: exactly the case that would have
    stayed silently wrong (hardcoded `"neutral"` on the observed side) had
    only the declared side been fixed.
    """
    program = SceneProgramDocument.model_validate({
        "scene_version": 3,
        "visuals": [{"kind": "object_set", "ref": "widgets", "count": {"node": "literal", "value": 3}}],
        "timeline": [{
            "at_seconds": 0.0, "duration_seconds": 1.0, "beat_id": "reveal_widgets",
            "action": {"kind": "reveal", "targets": [{"visual_ref": "widgets"}]},
        }],
        "total_duration_seconds": 12.0,
        "variation_seed": "state-event-agreement",
        "style_recipe": {"palette": "ocean", "composition": "vertical_lesson", "motion_variant": "smooth"},
    })
    resolved = resolve_scene(program, {}, _UnusedMeasurer())

    declared = _declared_state_events(resolved)
    assert declared and {event["role"] for event in declared} == {"structure"}

    render_events = [{
        "kind": "reveal", "seconds": 0.0,
        "targets": (("widgets", None, None),),
        "visible_targets": (("widgets", None, None),),
    }]
    observed = _state_events(render_events, resolved)

    declared_pairs = {(event["target"], event["role"]) for event in declared}
    observed_pairs = {(event["target"], event["role"]) for event in observed}
    assert declared_pairs <= observed_pairs
    assert {event["role"] for event in observed} == {"structure"}


def _perimeter_plan_with_dimension_callouts():
    # A rectangle_measurement plan whose derive beat requests callouts on the
    # declared "length_edge"/"width_edge" semantic parts (see
    # rectangle_measurement.py) -- the actual typed target a teaching plan
    # uses to label a dimension. No compiled relation ref ever contains the
    # substring "dimension" (the beat expander names callout relations
    # `callout_{beat}_{action}`), so this exercises defect C's real
    # production shape rather than a hand-built manifest literal.
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"},
            "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the measured rectangle"},
            {"id": "trace_boundary", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "trace every edge of the boundary",
             "custom_actions": [
                 {"kind": "callout", "text": "length", "target": {
                     "visual_ref": "rectangle", "part": "length_edge", "index": 0, "anchor": "bottom",
                 }},
                 {"kind": "callout", "text": "width", "target": {
                     "visual_ref": "rectangle", "part": "width_edge", "index": 0, "anchor": "left",
                 }},
             ]},
            {"id": "show_perimeter", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the perimeter"},
        ],
        "variation_seed": "worker-probe-dimensions",
    })


def _perimeter_scene_program_with_dimension_callouts():
    answer = MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")])
    return compile_teaching_plan(
        _perimeter_plan_with_dimension_callouts(), answer, frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )


def test_worker_probe_mode_reports_real_dimension_anchor_evidence_for_rectangle_callouts(tmp_path):
    program = _perimeter_scene_program_with_dimension_callouts()

    # Derived from the real compiled program, not a hand-picked literal: the
    # relations the compiler actually emitted for the length/width callouts.
    dimension_refs = {
        relation.ref for relation in program.relations
        if relation.target.part in {"length_edge", "width_edge"}
    }
    assert dimension_refs, "the plan's callouts must compile to real relations to exercise this test"

    program_path = tmp_path / "scene.json"
    fields_path = tmp_path / "fields.json"
    values_path = tmp_path / "values.json"
    output_path = tmp_path / "probe-final.png"
    program_path.write_text(program.model_dump_json())
    fields_path.write_text(json.dumps(["length", "width"]))
    values_path.write_text(json.dumps({"length": 5, "width": 3}))

    result = subprocess.run(
        [
            sys.executable, "-m", "app.render.dynamic_render_worker", str(program_path),
            str(fields_path), str(values_path), str(output_path), "probe", str(tmp_path),
        ],
        capture_output=True, text=True, cwd=BACKEND_ROOT, timeout=120,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output_path.with_suffix(".json").read_text())

    # The compiled dimension callouts must reach the manifest as real
    # relations -- `check_relation_alignment` then catches any that are
    # declared but not observed, so this is the observability half of that
    # gate rather than a separate contract.
    assert set(manifest["declared_relations"]) >= dimension_refs
    assert dimension_refs <= manifest["relations"].keys()
