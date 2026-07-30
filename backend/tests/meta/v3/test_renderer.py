from dataclasses import dataclass

import pytest
from manim import Text

from app.meta.dsl.expression import FieldRefNode, MultiplyNode
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.manim_measurer import FONT_SIZES, ManimTextMeasurer
from app.meta.v3.renderer import render_resolved_scene
from app.meta.v3.resolver import resolve_scene


class LiteralTextMeasurer:
    def measure(self, text: str, font_role: str):
        return len(text) * 0.3, 0.6


@dataclass
class PlayCall:
    index: int
    kind: str
    target_refs: tuple[str, ...] = ()
    target: tuple[str, str | None, int | None] | None = None
    role: str | None = None


class RecordingScene:
    def __init__(self):
        self.play_calls = []
        self.wait_calls = []

    def play(self, animation, **_kwargs):
        self.play_calls.append(PlayCall(
            index=len(self.play_calls),
            kind=animation._semantic_kind,
            target_refs=animation._semantic_target_refs,
            target=animation._semantic_target,
            role=animation._semantic_role,
        ))

    def wait(self, seconds):
        self.wait_calls.append(seconds)


@pytest.fixture
def resolved_median_scene():
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values",
            "ref": "values",
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
        "variation_seed": "median-renderer",
    })
    program = compile_teaching_plan(
        plan,
        FieldRefNode(field="v4"),
        frozenset({f"v{index}" for index in range(1, 8)}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )
    return resolve_scene(
        program,
        {f"v{index}": index for index in range(1, 8)},
        LiteralTextMeasurer(),
    )


def test_values_reveal_in_one_play_and_focus_changes_later(resolved_median_scene):
    scene = RecordingScene()
    render_resolved_scene(scene, resolved_median_scene)
    assert scene.play_calls[0].kind == "group_reveal"
    assert scene.play_calls[0].target_refs == ("values",)
    focus_call = next(call for call in scene.play_calls if call.kind == "set_role")
    assert focus_call.target == ("values", "item", 3)
    assert focus_call.role == "focus"
    assert focus_call.index > scene.play_calls[0].index


def test_manim_text_measurer_uses_the_renderer_font_table():
    measured = ManimTextMeasurer().measure("42", "math_value")
    text = Text("42", font_size=FONT_SIZES["math_value"])
    assert measured == pytest.approx((text.width, text.height))


def test_rectangle_renderer_maps_edges_and_plays_its_resolved_trace():
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Trace a rectangle perimeter.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"}, "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the rectangle"},
            {"id": "trace_boundary", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "trace its boundary"},
            {"id": "show_answer", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the result"},
        ],
        "variation_seed": "rectangle-renderer",
    })
    program = compile_teaching_plan(
        plan,
        MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="width")]),
        frozenset({"length", "width"}),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )
    resolved = resolve_scene(
        program, {"length": 8, "width": 3}, LiteralTextMeasurer(),
    )

    scene = RecordingScene()
    rendered = render_resolved_scene(scene, resolved)

    assert all(("rectangle", "edge", index) in rendered.targets for index in range(4))
    assert any(call.kind == "trace" for call in scene.play_calls)
