import pytest

from app.meta.artifacts import artifact_exists
from app.meta.dsl.expression import FieldRefNode, MultiplyNode
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.preview_render import render_preview_and_probe
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.render_probe import validate_rendered_quality


@pytest.fixture
def valid_manifest():
    return {
        "frame_size": [900, 500],
        "total_duration_seconds": 7.5,
        "conclusion_hold_seconds": 1.5,
        "simple_reveal_mode": "together",
        "frames": [
            {"beat_id": "reveal_values", "seconds": 1.5, "path": "probe-0.png", "non_background_pixels": 150},
            {"beat_id": "focus_middle", "seconds": 4.5, "path": "probe-1.png", "non_background_pixels": 150},
            {"beat_id": "show_answer", "seconds": 7.5, "path": "probe-2.png", "non_background_pixels": 200},
        ],
        "visual_bounds": {
            "values": [0, 0, 900, 120],
            "evaluated_answer": [200, 360, 700, 430],
        },
        "anchors": {"values.item[3].bottom": [451, 220]},
        "relations": {
            "median_callout": {
                "target_anchor": "values.item[3].bottom",
                "target": [451, 220],
                "tip": [451, 221],
                "bounds": [420, 225, 482, 260],
            },
        },
        "path_events": [],
        "declared_path_events": [],
        "dimension_anchor_checks": {},
        "state_events": [
            {"seconds": 1.5, "target": "values.item[3]", "role": "neutral"},
            {"seconds": 4.5, "target": "values.item[3]", "role": "focus"},
            {"seconds": 6.0, "target": "evaluated_answer", "role": "conclusion"},
        ],
        "final_answer_visible": True,
        "derivation_visible": True,
    }


@pytest.mark.parametrize("mutation,expected_code", [
    ("blank", "blank_probe_frame"),
    ("off_frame", "frame_out_of_bounds"),
    ("misaligned", "anchor_alignment_mismatch"),
    ("collision", "callout_collision"),
    ("state_order", "state_order_invalid"),
    ("path", "undeclared_path_event"),
    ("dimension", "dimension_anchor_mismatch"),
    ("answer", "final_answer_not_persistent"),
])
def test_rendered_quality_rejects_each_probe_failure(valid_manifest, mutation, expected_code):
    manifest = {**valid_manifest}
    if mutation == "blank":
        manifest["frames"] = [{**valid_manifest["frames"][0], "non_background_pixels": 0}]
    elif mutation == "off_frame":
        manifest["visual_bounds"] = {"values": [-1, 0, 900, 120]}
    elif mutation == "misaligned":
        manifest["relations"] = {"median_callout": {**valid_manifest["relations"]["median_callout"], "tip": [600, 400]}}
    elif mutation == "collision":
        manifest["visual_bounds"] = {**valid_manifest["visual_bounds"], "unrelated": [420, 225, 482, 260]}
    elif mutation == "state_order":
        manifest["state_events"] = [
            {"seconds": 1.0, "target": "values.item[3]", "role": "focus"},
            {"seconds": 2.0, "target": "values.item[3]", "role": "neutral"},
        ]
    elif mutation == "path":
        manifest["declared_path_events"] = ["rectangle.perimeter"]
    elif mutation == "dimension":
        manifest["dimension_anchor_checks"] = {"rectangle.edge[0]": False}
    elif mutation == "answer":
        manifest["final_answer_visible"] = False

    report = validate_rendered_quality(manifest)

    assert report.passed is False
    assert expected_code in [check.code for check in report.checks if not check.passed]


def test_rendered_quality_accepts_complete_manifest(valid_manifest):
    assert validate_rendered_quality(valid_manifest).passed is True


def test_rendered_report_surfaces_only_structured_failure(valid_manifest):
    valid_manifest["final_answer_visible"] = False
    report = validate_rendered_quality(valid_manifest)

    with pytest.raises(V3ValidationError, match="final_answer_not_persistent") as exc_info:
        report.require_passed()

    assert "traceback" not in str(exc_info.value).lower()


def test_preview_route_stores_only_a_passing_probed_final_frame(tmp_path):
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"}, "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the measured rectangle"},
            {"id": "trace_boundary", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "trace every edge of the boundary"},
            {"id": "show_answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the perimeter"},
        ],
        "variation_seed": "preview-probe",
    })
    program = compile_teaching_plan(
        plan, MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )

    artifact_hash, manifest = render_preview_and_probe(
        program, frozenset({"length", "width"}), {"length": 8, "width": 3}, tmp_path,
    )

    assert artifact_exists(tmp_path, artifact_hash)
    assert manifest["final_answer_visible"] is True
