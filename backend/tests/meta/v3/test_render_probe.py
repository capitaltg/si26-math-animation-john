import pytest

from app.meta.artifacts import artifact_exists
from app.meta.dsl.expression import FieldRefNode, LiteralNode, MultiplyNode
from app.meta.dsl.scene_program import RevealAction
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext, TargetRef
from app.meta.preview_render import render_preview_and_probe
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3ValidationError
from app.meta.v3 import render_probe
from app.meta.v3.render_probe import (
    ProbeRequest, run_probe_subprocess, validate_rendered_quality,
)


def _failure_codes(manifest) -> set[str]:
    return {check.code for check in validate_rendered_quality(manifest).checks if not check.passed}


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
        # `SAFE_FRAME` at this frame size: manim's default frame is 14.222 x 8
        # units, so the +/-6.6 x +/-3.6 safe box insets by 16 px horizontally
        # and 25 px vertically.
        "safe_frame": [16, 25, 884, 475],
        "visual_bounds": {
            "values": [20, 30, 880, 150],
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
        "declared_relations": ["median_callout"],
        "path_events": [],
        "declared_path_events": [],
        "dimension_anchor_checks": {},
        "declared_dimension_anchors": [],
        "dimension_labels": {},
        "declared_dimension_labels": [],
        "state_events": [
            {"seconds": 1.5, "target": "values.item[3]", "role": "neutral"},
            {"seconds": 4.5, "target": "values.item[3]", "role": "focus"},
            {"seconds": 6.0, "target": "evaluated_answer", "role": "conclusion"},
        ],
        "declared_state_events": [
            {"target": "values.item[3]", "role": "neutral"},
            {"target": "values.item[3]", "role": "focus"},
        ],
        "final_answer_visible": True,
        # What the final frame's answer statement reads as, beside what the last
        # `show_answer_stage` says it should. Equal here: a passing manifest.
        "final_answer_text": "2 × 3 = 6 m",
        "declared_answer_text": "2 × 3 = 6 m",
        "answer_anchor": None,
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
    ("unresolved_answer", "final_answer_not_persistent"),
    ("outside_safe_frame", "frame_out_of_bounds"),
    ("overlapping_visuals", "visual_overlap"),
    ("unlabelled_dimension", "dimension_label_missing"),
    ("blank_dimension_label", "dimension_label_missing"),
])
def test_rendered_quality_rejects_each_probe_failure(valid_manifest, mutation, expected_code):
    manifest = {**valid_manifest}
    if mutation == "blank":
        manifest["frames"] = [{**valid_manifest["frames"][0], "non_background_pixels": 0}]
    elif mutation == "off_frame":
        manifest["visual_bounds"] = {"values": [-1, 0, 900, 120]}
    elif mutation == "outside_safe_frame":
        # Inside the physical frame, outside the safe box layout targets. This
        # is the 16-px band the gate used to ignore -- exactly where the
        # published perimeter lesson's formula label came to rest, which is why
        # a label visibly touching the frame edge passed the rendered gate.
        manifest["visual_bounds"] = {
            **valid_manifest["visual_bounds"], "values": [4, 30, 880, 150],
        }
    elif mutation == "overlapping_visuals":
        manifest["visual_bounds"] = {
            **valid_manifest["visual_bounds"], "evaluated_answer": [800, 100, 880, 145],
        }
    elif mutation == "unlabelled_dimension":
        # A measurement visual that renders no measurements: the published
        # perimeter lesson drew a rectangle whose length and width appeared
        # nowhere, leaving nothing on screen to add up.
        manifest["declared_dimension_labels"] = ["rect"]
        manifest["dimension_labels"] = {"rect": {"length_label": "8 cm"}}
    elif mutation == "blank_dimension_label":
        manifest["declared_dimension_labels"] = ["rect"]
        manifest["dimension_labels"] = {
            "rect": {"length_label": "8 cm", "width_label": "   "},
        }
    elif mutation == "misaligned":
        manifest["relations"] = {"median_callout": {**valid_manifest["relations"]["median_callout"], "tip": [600, 400]}}
    elif mutation == "collision":
        manifest["visual_bounds"] = {**valid_manifest["visual_bounds"], "unrelated": [420, 225, 482, 260]}
    elif mutation == "state_order":
        # `values.item[3]` is `valid_manifest`'s answer anchor (see the median
        # callout and its bounds elsewhere in the fixture); a sibling item
        # receiving focus alongside it is what the check rejects now that it is
        # keyed on the declared anchor rather than a hardcoded neutral-before-
        # focus ordering on the item itself.
        manifest["answer_anchor"] = "values.item[3]"
        manifest["state_events"] = [
            {"seconds": 1.0, "target": "values.item[3]", "role": "neutral"},
            {"seconds": 2.0, "target": "values.item[3]", "role": "focus"},
            {"seconds": 3.0, "target": "values.item[0]", "role": "focus"},
        ]
    elif mutation == "path":
        manifest["declared_path_events"] = ["rectangle.perimeter"]
    elif mutation == "dimension":
        manifest["dimension_anchor_checks"] = {"rectangle.edge[0]": False}
    elif mutation == "answer":
        manifest["final_answer_visible"] = False
    elif mutation == "unresolved_answer":
        # The answer is on screen, but still reads as the unresolved work stage --
        # the defect `final_answer_visible` alone passed happily on.
        manifest["final_answer_text"] = "2 × 3 = ? m"

    report = validate_rendered_quality(manifest)

    assert report.passed is False
    assert expected_code in [check.code for check in report.checks if not check.passed]


def test_rendered_quality_accepts_complete_manifest(valid_manifest):
    assert validate_rendered_quality(valid_manifest).passed is True


def test_state_order_rejects_a_sibling_that_also_receives_focus(valid_manifest):
    valid_manifest["answer_anchor"] = "values.item[3]"
    valid_manifest["state_events"] = [
        {"seconds": 1.0, "target": "values.item[0]", "role": "neutral", "state_applied": True},
        {"seconds": 2.0, "target": "values.item[0]", "role": "focus", "state_applied": True},
        {"seconds": 3.0, "target": "values.item[3]", "role": "focus", "state_applied": True},
    ]
    valid_manifest["declared_state_events"] = []
    assert _failure_codes(valid_manifest) == {"state_order_invalid"}


def test_state_order_rejects_focus_before_the_others_are_dismissed(valid_manifest):
    valid_manifest["answer_anchor"] = "values.item[3]"
    valid_manifest["state_events"] = [
        {"seconds": 1.0, "target": "values.item[3]", "role": "focus", "state_applied": True},
        {"seconds": 2.0, "target": "values.item[0]", "role": "neutral", "state_applied": True},
    ]
    valid_manifest["declared_state_events"] = []
    assert _failure_codes(valid_manifest) == {"state_order_invalid"}


def test_state_order_accepts_the_answer_item_focused_last(valid_manifest):
    valid_manifest["answer_anchor"] = "values.item[3]"
    valid_manifest["state_events"] = [
        {"seconds": 1.0, "target": "values.item[0]", "role": "neutral", "state_applied": True},
        {"seconds": 2.0, "target": "values.item[6]", "role": "neutral", "state_applied": True},
        {"seconds": 3.0, "target": "values.item[3]", "role": "focus", "state_applied": True},
    ]
    valid_manifest["declared_state_events"] = []
    assert "state_order_invalid" not in _failure_codes(valid_manifest)


def test_state_order_passes_when_no_answer_anchor_is_declared(valid_manifest):
    valid_manifest["answer_anchor"] = None
    valid_manifest["state_events"] = []
    valid_manifest["declared_state_events"] = []
    assert "state_order_invalid" not in _failure_codes(valid_manifest)


@pytest.mark.parametrize("field", [
    "relations", "state_events", "path_events", "dimension_anchor_checks", "final_answer_visible",
    "final_answer_text", "declared_answer_text", "answer_anchor",
])
def test_rendered_quality_fails_closed_when_required_evidence_is_missing(valid_manifest, field):
    del valid_manifest[field]

    report = validate_rendered_quality(valid_manifest)

    assert report.passed is False
    assert "render_probe_contract_invalid" in [check.code for check in report.checks if not check.passed]


def test_rendered_quality_rejects_declared_state_not_observed_by_renderer(valid_manifest):
    valid_manifest["state_events"] = [
        {"seconds": 1.5, "target": "values.item[3]", "role": "neutral"},
    ]

    report = validate_rendered_quality(valid_manifest)

    assert report.passed is False
    assert "rendered_state_mismatch" in [check.code for check in report.checks if not check.passed]


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


def _legacy_shaped_program():
    """A compiled program rewritten into the shape stored before answer staging.

    A `scene_version: 3` program frozen before `show_answer_stage` existed
    reveals `evaluated_answer` in its conclude beat and stages it nowhere.
    `dynamic_templates.load` replays such a program verbatim -- no recompilation,
    no static gate -- so the renderer has to resolve its answer with no staging
    action to follow.
    """
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle area by multiplying its sides.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"}, "unit": "cm",
        },
        "strategy": "group_reveal",
        "beats": [
            {"id": "reveal_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the measured rectangle"},
            {"id": "multiply_sides", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "multiply the two side lengths"},
            {"id": "show_answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the area"},
        ],
        "variation_seed": "legacy-answer-probe",
    })
    program = compile_teaching_plan(
        plan, MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )
    conclusion = next(
        entry for entry in program.timeline
        if entry.action.kind == "set_role" and entry.action.role == "conclusion"
    )
    timeline = []
    for entry in program.timeline:
        if entry.action.kind == "show_answer_stage" or (
            entry.action.kind == "reveal"
            and any(target.visual_ref == "evaluated_answer" for target in entry.action.targets)
        ):
            continue
        if entry is conclusion:
            # The pre-branch conclude beat revealed the answer card and gave it
            # the conclusion role in one slot, so reuse this entry's timing.
            timeline.append(entry.model_copy(update={
                "action": RevealAction(
                    targets=[TargetRef(visual_ref="evaluated_answer")], mode="together",
                ),
            }))
        timeline.append(entry)
    return program.model_copy(update={"timeline": timeline})


def test_a_program_that_stages_nothing_resolves_its_answer_on_screen():
    """A stored program's replay must not end on the unresolved "?".

    Nothing recompiles a published template, and neither static nor rendered
    gates saw this: with the answer drawn as its `unknown` stage and no
    `show_answer_stage` to transform it, the final frame read "?" while
    `final_answer_visible` reported success and the text comparison was skipped.
    """
    manifest = run_probe_subprocess(ProbeRequest(
        scene_program=_legacy_shaped_program(),
        known_fields=["length", "width"],
        field_values={"length": 8, "width": 3},
    )).manifest

    # This fixture's answer expression is length x width and its plan names no
    # `answer_unit`, so the resolved statement reads "8 × 3 = 24".
    assert manifest["final_answer_text"] == "8 × 3 = 24"
    assert manifest["declared_answer_text"] == "8 × 3 = 24"
    assert validate_rendered_quality(manifest).passed is True


def _overcrowded_program():
    """Four measured rectangles: more than SAFE_FRAME can hold.

    Each rectangle's measured box is 6.75 x 2.68 (shape plus dimension labels),
    far too wide to sit beside another, so all four take full-width rows --
    with the answer's own row and the gap before each, 12.88 units of height
    against the 7.2-high instructional frame. `place_vertical_lesson` raises
    `below_minimum_text_scale` at 0.56 while resolving, before any frame is
    drawn.

    Three rectangles used to be enough, against a 6.0-high frame. Once the
    answer moved into the lesson column the instructional frame grew to the full
    safe frame, and three rectangles plus the answer row scaled to 0.74 -- above
    the 0.7 floor, so this fixture stopped reaching the failure path the test
    below exists to exercise. Hence the fourth.
    """
    def rectangle(ref):
        return {
            "kind": "rectangle_measurement", "ref": ref,
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"}, "unit": "cm",
        }

    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Compare the perimeters of four rectangles.",
        "primary_visual": rectangle("first"),
        "supporting_visuals": [rectangle("second"), rectangle("third"), rectangle("fourth")],
        "strategy": "boundary_trace",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "first"}],
             "intent": "show the first rectangle"},
            {"id": "organize", "kind": "organize", "targets": [{"visual_ref": "second"}],
             "intent": "show the second rectangle"},
            {"id": "derive", "kind": "derive",
             "targets": [{"visual_ref": "third"}, {"visual_ref": "fourth"}],
             "intent": "apply the perimeter formula to each"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "first"}],
             "intent": "state the perimeter"},
        ],
        "variation_seed": "overcrowded-probe",
    })
    return compile_teaching_plan(
        plan, MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )


def test_a_structured_failure_inside_the_probe_reaches_the_caller_intact():
    """A structured rejection from the subprocess must not flatten to a crash.

    Anything raising inside the probe was reported as `render_probe_failed`,
    "probe renderer exited unsuccessfully", hint "regenerate the candidate" --
    discarding the real code and its actionable hint, and leaving the retry loop
    nothing to act on. The subprocess stderr was discarded too, so an operator
    saw three burnt attempts and no traceback.
    """
    program = _overcrowded_program()
    # Asserted by intercepting the module's own logger call, not via `caplog`:
    # whether a record reaches a handler depends on global logging state that
    # other imports mutate (manim installs a root handler; a `dictConfig`
    # anywhere can set `Logger.disabled`, which `isEnabledFor` does not consult).
    # That made the same assertion pass alone and fail in the full suite.
    logged = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(render_probe.logger, "error", lambda *args: logged.append(args))
        with pytest.raises(V3ValidationError) as exc_info:
            run_probe_subprocess(ProbeRequest(
                scene_program=program,
                known_fields=["length", "width"],
                field_values={"length": 8, "width": 3},
            ))

    failure = exc_info.value.failure
    assert failure.code == "below_minimum_text_scale"
    assert failure.hint == "reduce visual content so the lesson remains readable"
    # And the operator gets the traceback the reviewer-facing failure omits.
    assert logged, "a probe crash must log the subprocess stderr for the operator"
    assert "below_minimum_text_scale" in " ".join(str(arg) for arg in logged[0])


def test_a_number_line_lesson_renders_with_its_marker_labels():
    """Labels are built from the payload inside the renderer, so only a real
    render proves the keys line up. The `vertex` and `object_set` bugs both
    compiled and passed the static gate, then raised inside `_build_visual`.
    """
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Place a distance in metres on a number line.",
        "primary_visual": {
            "kind": "number_line", "ref": "distance_line",
            "minimum": {"node": "literal", "value": 0},
            "maximum": {"node": "literal", "value": 3000},
            "markers": [
                {"node": "literal", "value": 0},
                {"node": "multiply", "operands": [
                    {"node": "field_ref", "field": "distance_km"},
                    {"node": "literal", "value": 1000},
                ]},
                {"node": "literal", "value": 3000},
            ],
        },
        "strategy": "group_reveal",
        "answer_unit": "meters",
        "variation_seed": "number-line-labels",
        "beats": [
            {"id": "show_line", "kind": "orient", "targets": [{"visual_ref": "distance_line"}],
             "intent": "show the scale from zero to three thousand metres"},
            {"id": "locate", "kind": "derive",
             "targets": [{"visual_ref": "distance_line", "part": "marker", "index": 1}],
             "intent": "locate the trail's length on the scale"},
            {"id": "state_total", "kind": "conclude", "targets": [{"visual_ref": "distance_line"}],
             "intent": "state the length in metres"},
        ],
    })
    program = compile_teaching_plan(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="distance_km"), LiteralNode(value=1000)]),
        frozenset({"distance_km"}),
        CompileContext(concept_family="transform_other", grade_band="3-5"),
    )

    manifest = run_probe_subprocess(ProbeRequest(
        scene_program=program,
        known_fields=["distance_km"],
        field_values={"distance_km": 1.5},
    )).manifest

    assert "distance_line" in manifest["visual_bounds"]
