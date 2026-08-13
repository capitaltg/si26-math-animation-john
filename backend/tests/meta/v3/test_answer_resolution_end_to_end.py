"""The kilometers lesson that motivated this work, end to end.

Its stored draft (`template_drafts` row `f029b56c`) authored a dead `? meters`
label, and the compiler appended a separate answer card into a reserved strip at
the bottom of the frame. This asserts the replacement: one statement that poses
the question, shows the multiplication, and resolves in place.
"""

from fractions import Fraction

from app.meta.dsl.expression import FieldRefNode, LiteralNode, MultiplyNode
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.quality import validate_static_quality
from app.meta.v3.resolver import resolve_scene


class _WidthPerCharacterMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.12, 0.4


def _kilometers_plan():
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": (
            "Convert a decimal number of kilometers to meters by multiplying by 1000."
        ),
        "primary_visual": {
            "kind": "bar", "ref": "km_bar",
            "value": {"node": "field_ref", "field": "distance_km"},
            "maximum": {"node": "literal", "value": 10.0},
        },
        "supporting_visuals": [
            {"kind": "label", "ref": "conversion_label", "text": "1 km = 1000 m"},
        ],
        # `magnitude_comparison` requires a literal bar value so the compile-time
        # sweep can address specific segments.
        # This lesson's bar takes a field-driven value, so it uses `group_reveal`
        # instead -- the strategy is not what the test asserts on.
        "strategy": "group_reveal",
        "answer_unit": "meters",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "km_bar"}],
             "intent": "show the distance in kilometers as a bar"},
            {"id": "reveal_conversion", "kind": "reveal",
             "targets": [{"visual_ref": "conversion_label"}],
             "intent": "reveal that one kilometer is one thousand meters"},
            {"id": "derive_meters", "kind": "derive",
             "targets": [{"visual_ref": "km_bar"}, {"visual_ref": "conversion_label"}],
             "intent": "multiply the kilometer value by one thousand"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "km_bar"}],
             "intent": "state the trail's length in meters"},
        ],
        "variation_seed": "km_to_m_decimal_trail",
    })


def _answer():
    return MultiplyNode(operands=[
        FieldRefNode(field="distance_km"), LiteralNode(value=1000),
    ])


def _program():
    return compile_teaching_plan(
        _kilometers_plan(), _answer(), frozenset({"distance_km"}),
        CompileContext(concept_family="unit_conversion", grade_band="3-5"),
    )


def test_the_kilometers_lesson_passes_every_static_quality_gate():
    plan, program = _kilometers_plan(), _program()

    report = validate_static_quality(plan, program)

    assert report.passed, [check for check in report.checks if not check.passed]


def test_the_kilometers_lesson_poses_shows_and_resolves_its_answer():
    program = _program()

    stages = [
        (entry.beat_id, entry.action.stage)
        for entry in program.timeline if entry.action.kind == "show_answer_stage"
    ]
    assert stages == [("derive_meters", "work"), ("conclude", "value")]


def test_the_resolved_statement_reads_as_a_conversion():
    resolved = resolve_scene(
        _program(), {"distance_km": Fraction(11, 4)}, _WidthPerCharacterMeasurer(),
    )

    stages = resolved.visual("evaluated_answer").measured.payload["stages"]
    assert stages == {
        "unknown": "? meters",
        "work": "2.75 × 1000 = ? meters",
        "value": "2.75 × 1000 = 2750 meters",
    }


def test_the_answer_is_not_pinned_to_the_bottom_of_the_frame():
    resolved = resolve_scene(
        _program(), {"distance_km": Fraction(11, 4)}, _WidthPerCharacterMeasurer(),
    )

    answer = resolved.visual("evaluated_answer")
    primary = resolved.visual("km_bar")
    assert answer.bounds.top <= primary.bounds.bottom + 1e-9
    # The answer participates in layout instead of occupying a reserved band.
    assert answer.bounds.bottom > -2.4


def test_the_rendered_final_frame_actually_shows_the_resolved_answer(tmp_path):
    """The one assertion that reaches all the way to drawn pixels.

    Everything above reads the compiled program and the resolved scene, and all
    of it passed while the rendered video ended on "2.75 × 1000 = ? meters": the
    conclude beat's `show_answer_stage(value)` and its `set_role(conclusion)` were
    two competing `Transform`s on one mobject, and the recolour -- whose target is
    a copy of the mobject as it stands, i.e. the work stage -- won. Nothing short
    of rendering observed it.
    """
    from app.meta.preview_render import render_preview_and_probe

    _artifact_hash, manifest = render_preview_and_probe(
        _program(), frozenset({"distance_km"}), {"distance_km": 2.75}, tmp_path,
    )

    assert manifest["final_answer_text"] == "2.75 × 1000 = 2750 meters"
    assert manifest["declared_answer_text"] == "2.75 × 1000 = 2750 meters"
