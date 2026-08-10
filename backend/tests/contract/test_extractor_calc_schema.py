"""Contract: extractor output is shape-compatible with Python calc input.

`extract_params(source_text, ParamsCls)` returns a `ParamsCls` instance
built from the LLM's tool call. Downstream, the same instance is fed to
`ParamsCls.compute_answer()` — that method is the Python calculation
this project runs on top of the extracted values. If someone edits the
Params model but forgets to update `compute_answer` (or vice versa), the
per-template extraction happens fine and then the calc explodes at
runtime with an `AttributeError` — with no in-CI signal on main.

Per-template tests verify individual `compute_answer` implementations
against hand-picked inputs. What binds them is a single-place spec: for
**every** static template registered in `_REGISTRY`, one canonical input
must validate through `ParamsCls.model_validate` and drive
`compute_answer` to completion. Adding a template without adding an
entry here fails the enumeration guard.
"""

from fractions import Fraction

import pytest

from app.models.scene import TemplateName
from app.templates.registry import _REGISTRY


# One valid, minimal example per static template. Written to satisfy the
# Params model's own guards (positive numerators, denominator > 1, etc.),
# but otherwise trivial — the point is round-trip through the extractor's
# validator and into `compute_answer`, not to exercise pedagogical range.
CANONICAL_EXAMPLES: dict[TemplateName, dict] = {
    TemplateName.NUMBER_LINE: {
        "start": 4,
        "steps": [{"operation": "add", "amount": 3}],
    },
    TemplateName.ARRAY_GRID: {
        "rows": 2,
        "cols": 3,
        "steps": [],
    },
    TemplateName.BALANCE_SCALE: {
        "left_terms": [2, 3],
        "right_total": 5,
    },
    TemplateName.FRACTION_BAR: {
        "denominator": 4,
        "start_numerator": 1,
        "steps": [
            {"numerator": 1, "operation": "add"},
            {"numerator": 1, "operation": "add"},
        ],
    },
    TemplateName.FRACTION_OF_WHOLE: {
        "numerator": 1,
        "denominator": 4,
    },
    TemplateName.TEXT_CARD: {
        "headline": "answer",
        "lines": ["42"],
    },
}


def test_every_registered_static_template_has_a_canonical_example():
    """Guard: `CANONICAL_EXAMPLES` covers every entry in the static registry.

    A new template added to `_REGISTRY` without an entry here would
    escape the extractor→calc shape check. The test fails until the
    author supplies a canonical input for the new template's Params.
    """
    registered = set(_REGISTRY.keys())
    covered = set(CANONICAL_EXAMPLES.keys())

    missing = registered - covered
    stray = covered - registered

    assert not missing, (
        f"Static templates without a canonical example: {sorted(t.value for t in missing)}. "
        f"Add one entry per template to CANONICAL_EXAMPLES."
    )
    assert not stray, (
        f"Canonical examples for templates no longer in the registry: "
        f"{sorted(t.value for t in stray)}."
    )


@pytest.mark.parametrize(
    "template_name,example",
    list(CANONICAL_EXAMPLES.items()),
    ids=[t.value for t in CANONICAL_EXAMPLES],
)
def test_extractor_shape_drives_calc_without_error(template_name, example):
    """Simulates one end-to-end shape check per template.

    `extract_params(...)` returns `ParamsCls.model_validate(<tool_call>)`;
    passing our canonical dict through the same validator reproduces the
    exact instance shape a real extraction produces. Feeding that
    instance to `compute_answer` reproduces what the runtime does with
    the extracted values.

    An `AttributeError` from `compute_answer` means the Params schema
    lost a field the calc reads. A `ValidationError` from
    `model_validate` means the canonical example drifted from the
    schema — the author must update the example (or, if the schema
    change was intentional, verify the extractor prompt was updated too).
    """
    _scene_cls, params_cls = _REGISTRY[template_name]

    params = params_cls.model_validate(example)

    # Every template exposes `compute_answer` and it either returns a
    # Fraction or None (the latter for templates like text_card where
    # there is no numeric answer to compute). If a template ever grows a
    # different return contract this assertion tells us before the
    # runtime does.
    result = params.compute_answer()
    assert result is None or isinstance(result, Fraction), (
        f"{template_name.value}.compute_answer returned {type(result).__name__}; "
        f"expected Fraction or None."
    )
