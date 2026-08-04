from fractions import Fraction

import pytest

from app.meta.dsl.expression import LiteralNode
from app.meta.dsl.scene_program import UnitTapeProgramVisual
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.resolver import evaluate_program_visual
from app.meta.v3.visual_registry import default_visual_registry


class LabelMeasurer:
    """Roughly `ManimTextMeasurer` at the label font size."""

    def measure(self, text: str, font_role: str):
        return len(text) * 0.3, 0.6


def test_a_program_tape_evaluates_its_two_expressions():
    visual = UnitTapeProgramVisual(
        ref="trail_tape",
        value=LiteralNode(node="literal", value=2.75),
        per_unit=LiteralNode(node="literal", value=1000),
        source_unit="km",
        target_unit="m",
    )

    spec, values = evaluate_program_visual(visual, {})

    assert spec.kind == "unit_tape"
    assert spec.initial_role == "structure"
    assert values == {
        "value": Fraction(11, 4), "per_unit": Fraction(1000),
        "source_unit": "km", "target_unit": "m",
    }
