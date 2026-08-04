# Answer Resolution In Place Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a generated lesson's answer resolve in place — `? meters` → `2.75 × 1000 = ? meters` → `2.75 × 1000 = 2750 meters` — laid out as part of the lesson column rather than as a card in a reserved bottom strip.

**Architecture:** The answer visual becomes a three-stage text statement whose stages are all derived from the `answer_expression` the scene program already carries. A new `show_answer_stage` program action drives the two transitions, played by manim `Transform` on the same mobject. The compiler owns the staging (first beat / last derive-or-focus beat / conclude); the plan supplies only `answer_unit`. `layout.CONCLUSION_BAND` is deleted so the answer arranges like any other visual.

**Tech Stack:** Python 3.14, pydantic v2, manim, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-answer-resolution-in-place-design.md`.
- Run tests from `backend/` with `.venv/bin/pytest` (the venv at `backend/.venv`, not the repo-root one).
- All work lands on branch `answer-resolution-in-place` (already created, spec already committed there).
- `pair_elimination` behaviour must not change: it declares no `evaluated_answer` visual and keeps `SceneProgramDocument.answer_anchor`.
- Every schema addition is additive with a default, so stored `plan_version: 3` and `scene_version: 3` documents deserialise unchanged.
- Follow the surrounding code's comment style: comments explain *why* a non-obvious choice was made, and name the failure mode that motivated it.
- Never add a `TODO`, speculative abstraction, or configurability the spec does not call for (`CLAUDE.md` §2).

---

### Task 1: Expression display printer

A pure, dependency-free module: turn an `ExpressionNode` plus field values into a one-line human-readable string, with minimal precedence-aware parenthesisation and terminating-decimal number formatting.

**Files:**
- Create: `backend/app/meta/v3/expression_display.py`
- Test: `backend/tests/meta/v3/test_expression_display.py`

**Interfaces:**
- Consumes: `app.meta.dsl.expression._evaluate(node, values) -> Fraction` (existing).
- Produces:
  - `format_number(value: Fraction) -> str`
  - `expression_display(node, values: Mapping[str, object]) -> str`
  - `has_operation(node) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/meta/v3/test_expression_display.py`:

```python
from fractions import Fraction

import pytest

from app.meta.dsl.expression import (
    AddNode, DivideNode, FieldRefNode, FractionNode, LiteralNode,
    MultiplyNode, SubtractNode,
)
from app.meta.v3.expression_display import (
    expression_display, format_number, has_operation,
)


def _literal(value):
    return LiteralNode(value=value)


def _field(name):
    return FieldRefNode(field=name)


@pytest.mark.parametrize(
    "value,expected",
    [
        (Fraction(2750), "2750"),
        (Fraction(11, 4), "2.75"),
        (Fraction(0), "0"),
        (Fraction(-7, 2), "-3.5"),
        (Fraction(1, 8), "0.125"),
        # A denominator with a prime factor other than 2 or 5 has no terminating
        # decimal, so it stays a fraction rather than being silently rounded.
        (Fraction(1, 3), "1/3"),
        (Fraction(2, 7), "2/7"),
    ],
)
def test_format_number_prefers_a_terminating_decimal(value, expected):
    assert format_number(value) == expected


def test_a_field_reference_shows_its_value_as_a_decimal():
    # `resolver._format_value` would render this Fraction as "11/4"; a lesson
    # about 2.75 kilometres has to say 2.75.
    node = _field("distance_km")
    assert expression_display(node, {"distance_km": Fraction(11, 4)}) == "2.75"


def test_the_kilometers_conversion_reads_as_one_multiplication():
    node = MultiplyNode(operands=[_field("distance_km"), _literal(1000)])
    values = {"distance_km": Fraction(11, 4)}
    assert expression_display(node, values) == "2.75 × 1000"


def test_a_looser_child_is_parenthesised():
    # "2 + 3 × 4" would evaluate to 14; the tree means 20.
    node = MultiplyNode(operands=[AddNode(operands=[_literal(2), _literal(3)]), _literal(4)])
    assert expression_display(node, {}) == "(2 + 3) × 4"


def test_a_tighter_child_needs_no_parentheses():
    node = AddNode(operands=[MultiplyNode(operands=[_literal(2), _literal(3)]), _literal(4)])
    assert expression_display(node, {}) == "2 × 3 + 4"


def test_the_right_operand_of_a_nested_subtraction_is_parenthesised():
    # Equal precedence, so a tier comparison alone would omit these parentheses
    # and turn 7 into 3.
    node = SubtractNode(operands=[_literal(10), SubtractNode(operands=[_literal(5), _literal(2)])])
    assert expression_display(node, {}) == "10 - (5 - 2)"


def test_the_right_operand_of_a_nested_division_is_parenthesised():
    node = DivideNode(operands=[_literal(100), DivideNode(operands=[_literal(10), _literal(2)])])
    assert expression_display(node, {}) == "100 ÷ (10 ÷ 2)"


def test_the_left_operand_of_a_nested_subtraction_needs_no_parentheses():
    node = SubtractNode(operands=[SubtractNode(operands=[_literal(10), _literal(5)]), _literal(2)])
    assert expression_display(node, {}) == "10 - 5 - 2"


def test_a_fraction_renders_as_a_ratio():
    node = FractionNode(operands=[_literal(1), _literal(3)])
    assert expression_display(node, {}) == "1/3"


def test_a_nested_fraction_denominator_is_parenthesised():
    node = FractionNode(operands=[
        _literal(1), FractionNode(operands=[_literal(2), _literal(3)]),
    ])
    assert expression_display(node, {}) == "1/(2/3)"


def test_a_four_operand_sum_joins_every_operand():
    node = AddNode(operands=[_literal(1), _literal(2), _literal(3), _literal(4)])
    assert expression_display(node, {}) == "1 + 2 + 3 + 4"


@pytest.mark.parametrize(
    "node,expected",
    [
        (LiteralNode(value=5), False),
        (FieldRefNode(field="distance_km"), False),
        (MultiplyNode(operands=[LiteralNode(value=2), LiteralNode(value=3)]), True),
        (FractionNode(operands=[LiteralNode(value=1), LiteralNode(value=3)]), True),
    ],
)
def test_has_operation_reports_whether_there_is_work_to_show(node, expected):
    assert has_operation(node) is expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_expression_display.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.meta.v3.expression_display'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/meta/v3/expression_display.py`:

```python
"""Render an answer expression as one line of learner-facing text.

The expression tree is unambiguous; a one-line string is not. So flattening has
to add the parentheses the tree implies -- and only those, since a K-8 lesson
should read like a textbook rather than like a parser's output.
"""

from collections.abc import Mapping
from decimal import Decimal, localcontext
from fractions import Fraction

from app.meta.dsl.expression import _evaluate

_ATOMS = frozenset({"literal", "field_ref"})

#: Higher binds tighter. `fraction` sits above the arithmetic operators because
#: it renders as a ratio with no separating spaces, so it never needs
#: parentheses of its own when it appears as an operand.
_PRECEDENCE = {"add": 1, "subtract": 1, "multiply": 2, "divide": 2, "fraction": 3}

_SYMBOLS = {"add": "+", "subtract": "-", "multiply": "×", "divide": "÷"}

#: Operators for which `a - (b - c)` differs from `a - b - c`. Their RIGHT
#: operand needs parentheses even at equal precedence, which a tier comparison
#: alone cannot detect: both nodes sit in the same tier.
_NON_ASSOCIATIVE = frozenset({"subtract", "divide", "fraction"})

#: Enough digits for any terminating decimal this DSL can produce.
#: `_to_fraction` caps denominators at 10**9, so at most ~30 decimal places.
_DECIMAL_PRECISION = 40


def has_operation(node) -> bool:
    """Whether the expression contains work worth showing.

    A bare field reference or literal has no arithmetic to display, so its
    `work` stage would repeat the value it is about to resolve to.
    """
    return node.node not in _ATOMS


def format_number(value: Fraction) -> str:
    """A terminating decimal when the value has one, else `numerator/denominator`.

    `resolver._format_value` renders any non-integer as a ratio, so substituting
    2.75 into a displayed expression would print "11/4". A fraction terminates
    in base ten exactly when its reduced denominator's only prime factors are 2
    and 5, so test for that rather than rounding and hoping.
    """
    remainder = value.denominator
    for factor in (2, 5):
        while remainder % factor == 0:
            remainder //= factor
    if remainder != 1:
        return f"{value.numerator}/{value.denominator}"
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        return str(Decimal(value.numerator) / Decimal(value.denominator))


def expression_display(node, values: Mapping[str, object]) -> str:
    return _display(node, values, parent=None, is_right=False)


def _display(node, values, parent, is_right) -> str:
    if node.node in _ATOMS:
        return format_number(_evaluate(node, values))
    if node.node == "fraction":
        numerator, denominator = node.operands
        text = (
            f"{_display(numerator, values, node.node, False)}"
            f"/{_display(denominator, values, node.node, True)}"
        )
    else:
        separator = f" {_SYMBOLS[node.node]} "
        text = separator.join(
            _display(operand, values, node.node, index > 0)
            for index, operand in enumerate(node.operands)
        )
    if _needs_parentheses(node.node, parent, is_right):
        return f"({text})"
    return text


def _needs_parentheses(child, parent, is_right) -> bool:
    if parent is None:
        return False
    if _PRECEDENCE[child] < _PRECEDENCE[parent]:
        return True
    return (
        _PRECEDENCE[child] == _PRECEDENCE[parent]
        and is_right
        and parent in _NON_ASSOCIATIVE
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_expression_display.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/meta/v3/expression_display.py backend/tests/meta/v3/test_expression_display.py
git commit -m "feat: render an answer expression as one line of learner text"
```

---

### Task 2: Schema for the staged answer

Add the program action that drives a stage transition, and the one plan field the model supplies.

**Files:**
- Modify: `backend/app/meta/dsl/scene_program.py` (add class after `MoveAction` at `:129-133`; extend the `ProgramAction` union at `:136-142`)
- Modify: `backend/app/meta/dsl/teaching_plan.py` (add field to `TeachingPlanDocument` at `:178-189`)
- Test: `backend/tests/meta/dsl/test_scene_program_schema.py`, `backend/tests/meta/dsl/test_teaching_plan_schema.py`

**Interfaces:**
- Produces:
  - `ShowAnswerStageAction(kind="show_answer_stage", target: TargetRef, stage: Literal["work", "value"])`, a member of the `ProgramAction` union
  - `TeachingPlanDocument.answer_unit: str` (default `""`, max length 20)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/meta/dsl/test_scene_program_schema.py`:

```python
def test_a_show_answer_stage_action_parses_from_the_program_action_union():
    from pydantic import TypeAdapter

    from app.meta.dsl.scene_program import ProgramAction, ShowAnswerStageAction

    action = TypeAdapter(ProgramAction).validate_python({
        "kind": "show_answer_stage",
        "target": {"visual_ref": "evaluated_answer"},
        "stage": "work",
    })

    assert isinstance(action, ShowAnswerStageAction)
    assert action.stage == "work"


def test_the_unknown_stage_is_not_an_addressable_stage():
    """The unknown text is what the visual is DRAWN as, so the ordinary reveal
    puts it on screen. Only the two transitions away from it are actions."""
    from pydantic import ValidationError

    from app.meta.dsl.scene_program import ShowAnswerStageAction

    with pytest.raises(ValidationError):
        ShowAnswerStageAction(
            target=TargetRef(visual_ref="evaluated_answer"), stage="unknown",
        )
```

If `pytest` and `TargetRef` are not already imported at the top of that file, add
`import pytest` and `from app.meta.dsl.v3_common import TargetRef` to its imports.

Append to `backend/tests/meta/dsl/test_teaching_plan_schema.py`:

```python
def test_answer_unit_defaults_to_empty_so_stored_plans_still_parse():
    from app.meta.dsl.teaching_plan import TeachingPlanDocument

    plan = TeachingPlanDocument.model_validate(_minimal_plan_payload())

    assert plan.answer_unit == ""


def test_answer_unit_carries_the_unit_of_the_result():
    from app.meta.dsl.teaching_plan import TeachingPlanDocument

    plan = TeachingPlanDocument.model_validate(
        {**_minimal_plan_payload(), "answer_unit": "meters"},
    )

    assert plan.answer_unit == "meters"
```

Read the existing test file first and reuse whatever plan-payload helper it
already defines; if there is none, add this one beside the new tests:

```python
def _minimal_plan_payload():
    return {
        "plan_version": 3,
        "learning_objective": "Convert kilometres to metres.",
        "primary_visual": {
            "kind": "bar", "ref": "km_bar",
            "value": {"node": "field_ref", "field": "distance_km"},
            "maximum": {"node": "literal", "value": 10.0},
        },
        "strategy": "magnitude_comparison",
        "beats": [
            {"id": "orient", "kind": "orient", "targets": [{"visual_ref": "km_bar"}],
             "intent": "show the distance as a bar"},
            {"id": "derive", "kind": "derive", "targets": [{"visual_ref": "km_bar"}],
             "intent": "multiply by one thousand"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "km_bar"}],
             "intent": "state the length in metres"},
        ],
        "variation_seed": "km-to-m",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`:
`.venv/bin/pytest tests/meta/dsl/test_scene_program_schema.py tests/meta/dsl/test_teaching_plan_schema.py -q`
Expected: `ImportError: cannot import name 'ShowAnswerStageAction'`, and the
`answer_unit` tests failing on `extra="forbid"` / missing attribute.

- [ ] **Step 3: Add the action to the scene program**

In `backend/app/meta/dsl/scene_program.py`, after `MoveAction`:

```python
class ShowAnswerStageAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["show_answer_stage"] = "show_answer_stage"
    #: Always the answer visual. Carried explicitly, rather than being implied,
    #: so every existing consumer that discovers targets generically --
    #: `resolver.action_targets`, `quality._targets`,
    #: `quality.check_unused_visual` -- sees this action without modification.
    target: TargetRef
    stage: Literal["work", "value"]
```

and add it to the union:

```python
ProgramAction = Annotated[
    Union[
        RevealAction, SetRoleAction, TraceAction, ShowRelationAction,
        DrawAction, TransformAction, MoveAction, ShowAnswerStageAction,
    ],
    Field(discriminator="kind"),
]
```

- [ ] **Step 4: Add the plan field**

In `backend/app/meta/dsl/teaching_plan.py`, inside `TeachingPlanDocument`, after `strategy`:

```python
    #: The unit of the computed result ("meters"), empty when unitless. The
    #: compiler puts it on the answer visual's suffix; the model authors nothing
    #: else about answer presentation.
    answer_unit: ProseText = Field(default="", max_length=20)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run from `backend/`:
`.venv/bin/pytest tests/meta/dsl/test_scene_program_schema.py tests/meta/dsl/test_teaching_plan_schema.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/meta/dsl/scene_program.py backend/app/meta/dsl/teaching_plan.py \
        backend/tests/meta/dsl/test_scene_program_schema.py \
        backend/tests/meta/dsl/test_teaching_plan_schema.py
git commit -m "feat: add the show_answer_stage action and answer_unit"
```

---

### Task 3: Resolve, measure and render the stages

The answer visual stops masquerading as a label. It resolves to a dict of stage texts, is measured at the widest stage so nothing reflows, and renders as one `Text` per stage with `Transform` between them.

**Files:**
- Modify: `backend/app/meta/v3/resolver.py:134-137` (the `answer_expression` branch)
- Modify: `backend/app/meta/v3/visual_registry.py` (add `_measure_answer` beside `_measure_label` at `:263`; register it in `default_visual_registry`)
- Modify: `backend/app/meta/v3/renderer.py` (`RenderedScene` at `:32-37`; `_build_vertical_lesson` at `:81-94`; `_initial_role` at `:210-225`; `_action_animation` at `:392-408`)
- Test: `backend/tests/meta/v3/test_visual_registry.py`, `backend/tests/meta/v3/test_scene_resolver.py`, `backend/tests/meta/v3/test_renderer.py`

**Interfaces:**
- Consumes: `expression_display`, `format_number`, `has_operation` from Task 1; `ShowAnswerStageAction` from Task 2.
- Produces:
  - resolved answer payload `{"stages": {"unknown": str, "work": str (optional), "value": str}}` on a spec of `kind="answer_expression"`
  - `RenderedScene.answer_stages: dict[str, dict[str, object]]` — visual ref → stage name → mobject

- [ ] **Step 1: Write the failing resolver and registry tests**

Append to `backend/tests/meta/v3/test_scene_resolver.py`:

```python
def test_an_answer_expression_resolves_to_three_stages():
    from app.meta.dsl.scene_program import AnswerProgramVisual
    from app.meta.dsl.expression import FieldRefNode, LiteralNode, MultiplyNode
    from app.meta.v3.resolver import evaluate_program_visual

    visual = AnswerProgramVisual(
        ref="evaluated_answer",
        expression=MultiplyNode(operands=[
            FieldRefNode(field="distance_km"), LiteralNode(value=1000),
        ]),
        suffix=" meters",
    )

    spec, payload = evaluate_program_visual(visual, {"distance_km": Fraction(11, 4)})

    assert spec.kind == "answer_expression"
    assert payload["stages"] == {
        "unknown": "? meters",
        "work": "2.75 × 1000 = ? meters",
        "value": "2.75 × 1000 = 2750 meters",
    }


def test_an_answer_with_no_arithmetic_has_no_work_stage():
    """A bare field reference has nothing to show, so a work stage would just
    print the value it is about to resolve to."""
    from app.meta.dsl.scene_program import AnswerProgramVisual
    from app.meta.dsl.expression import FieldRefNode
    from app.meta.v3.resolver import evaluate_program_visual

    visual = AnswerProgramVisual(
        ref="evaluated_answer", expression=FieldRefNode(field="total"), suffix=" apples",
    )

    _spec, payload = evaluate_program_visual(visual, {"total": Fraction(7)})

    assert payload["stages"] == {"unknown": "? apples", "value": "7 apples"}
```

Append to `backend/tests/meta/v3/test_visual_registry.py`:

```python
def test_the_answer_visual_is_measured_at_its_widest_stage():
    """Layout has to reserve the final width, or the statement reflows mid-scene."""
    from app.meta.v3.visual_registry import default_visual_registry

    spec = type("Spec", (), {"kind": "answer_expression", "ref": "evaluated_answer"})()
    stages = {
        "unknown": "? m",
        "work": "2.75 × 1000 = ? m",
        "value": "2.75 × 1000 = 2750 m",
    }

    measured = default_visual_registry().measure(
        spec, {"stages": stages}, LiteralTextMeasurer(),
    )

    widest, _height = LiteralTextMeasurer().measure(stages["value"], "label")
    assert measured.bounds.right - measured.bounds.left == pytest.approx(widest)
    assert measured.payload["stages"] == stages
```

Check `LiteralTextMeasurer` in that file returns width proportional to text
length; if it returns a constant, use the `_WidthPerCharacterMeasurer` pattern
from `tests/meta/v3/test_layout.py:11-13` inside this test instead.

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`:
`.venv/bin/pytest tests/meta/v3/test_scene_resolver.py tests/meta/v3/test_visual_registry.py -q`
Expected: the resolver tests fail on `payload["text"]` having no `"stages"` key;
the registry test fails with `ValueError: unknown semantic visual answer_expression`.

- [ ] **Step 3: Resolve the stages**

In `backend/app/meta/v3/resolver.py`, add the import:

```python
from app.meta.v3.expression_display import expression_display, format_number, has_operation
```

and replace the `answer_expression` branch of `evaluate_program_visual`:

```python
    if kind == "answer_expression":
        value = format_number(_evaluate(visual.expression, values))
        stages = {"unknown": f"{visual.prefix}?{visual.suffix}"}
        if has_operation(visual.expression):
            work = expression_display(visual.expression, values)
            stages["work"] = f"{visual.prefix}{work} = ?{visual.suffix}"
            stages["value"] = f"{visual.prefix}{work} = {value}{visual.suffix}"
        else:
            stages["value"] = f"{visual.prefix}{value}{visual.suffix}"
        return _evaluated_spec(visual), {"stages": stages}
```

`_evaluated_spec` already carries `kind`, `ref` and `initial_role`, so the
answer no longer has to masquerade as a label.

- [ ] **Step 4: Measure the widest stage**

In `backend/app/meta/v3/visual_registry.py`, beside `_measure_label`:

```python
def _measure_answer(*, spec, values, measurer):
    """Reserve the widest stage, so resolving the answer never reflows the lesson."""
    stages = values["stages"]
    measured = [measurer.measure(text, "label") for text in stages.values()]
    width = max(width for width, _height in measured)
    height = max(height for _width, height in measured)
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(-width / 2, width / 2, -height / 2, height / 2),
        parts={},
        payload={"stages": stages},
    )
```

and register it in `default_visual_registry`, after the `label` registration:

```python
    registry.register("answer_expression", _measure_answer)
```

`_SUPPORTED_STRATEGIES` needs no entry: `VisualRegistry.measure` only indexes it
when `strategy is not None`, and the single call site (`resolver.py:78`) never
passes one.

- [ ] **Step 5: Run the resolver and registry tests**

Run from `backend/`:
`.venv/bin/pytest tests/meta/v3/test_scene_resolver.py tests/meta/v3/test_visual_registry.py -q`
Expected: the two new resolver tests and the new registry test pass. Other tests
in these files may now fail where they assert the old `{"text": ...}` answer
payload — leave those; Task 8 sweeps them.

- [ ] **Step 6: Write the failing renderer test**

Append to `backend/tests/meta/v3/test_renderer.py`:

```python
def test_the_answer_renders_every_stage_and_transforms_between_them():
    """The unknown stage is the mobject on screen; the transitions mutate it in
    place, so `dynamic_render_worker._answer_visible` keeps finding the same
    mobject in the final frame."""
    from manim import Transform

    from app.meta.dsl.v3_common import TargetRef
    from app.meta.v3.geometry import Bounds, MeasuredVisual, PlacedVisual, Point
    from app.meta.v3.renderer import _action_animation, _build_vertical_lesson

    stages = {"unknown": "? m", "work": "2 × 3 = ? m", "value": "2 × 3 = 6 m"}
    measured = MeasuredVisual(
        ref="evaluated_answer",
        bounds=Bounds(-1, 1, -0.2, 0.2),
        parts={},
        paths={},
        payload={"stages": stages},
    )
    scene = _resolved_scene_with([PlacedVisual(measured, Point(0, 0), 1.0)])

    rendered = _build_vertical_lesson(scene, "ocean")

    assert set(rendered.answer_stages["evaluated_answer"]) == {"unknown", "work", "value"}
    assert rendered.visuals["evaluated_answer"] is (
        rendered.answer_stages["evaluated_answer"]["unknown"]
    )

    action = _resolved_action_for(
        ShowAnswerStageAction(target=TargetRef(visual_ref="evaluated_answer"), stage="work"),
    )
    assert isinstance(_action_animation(action, rendered, _reveal, "ocean"), Transform)
```

Read `tests/meta/v3/test_renderer.py` first and build `_resolved_scene_with`,
`_resolved_action_for` and `_reveal` from whatever helpers it already has for
constructing a `ResolvedScene` and a `ResolvedAction`; reuse them rather than
adding parallel ones. Import `ShowAnswerStageAction` from
`app.meta.dsl.scene_program`.

- [ ] **Step 7: Run the renderer test to verify it fails**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_renderer.py -q`
Expected: `AttributeError: 'RenderedScene' object has no attribute 'answer_stages'`.

- [ ] **Step 8: Build and animate the stages**

In `backend/app/meta/v3/renderer.py`, add `field` to the dataclasses import and
extend `RenderedScene`:

```python
from dataclasses import dataclass, field
```

```python
@dataclass(frozen=True)
class RenderedScene:
    visuals: dict[str, object]
    targets: dict[tuple[str, str | None, int | None], object]
    relations: dict[str, object]
    roles: dict[tuple[str, str | None, int | None], str]
    #: Answer visual ref -> stage name -> mobject. Deliberately NOT in
    #: `targets`: a plan may address the answer, never one of its stages.
    answer_stages: dict[str, dict[str, object]] = field(default_factory=dict)
```

In `_build_vertical_lesson`, replace the body of the visual loop:

```python
    answer_stages: dict[str, dict[str, object]] = {}
    for placed in scene.visuals:
        payload = placed.measured.payload
        if isinstance(payload, dict) and "stages" in payload:
            root, stages = _build_answer_stages(placed, palette)
            answer_stages[placed.measured.ref] = stages
            children = {}
        else:
            root, children = _build_visual(placed, palette)
        visuals[placed.measured.ref] = root
        targets[(placed.measured.ref, None, None)] = root
        targets.update({(placed.measured.ref, part, index): child for (part, index), child in children.items()})
        role = _initial_role(placed.measured.ref, payload)
        roles[(placed.measured.ref, None, None)] = role
        roles.update({(placed.measured.ref, part, index): role for part, index in children})
    relations = {relation.ref: _build_relation(relation, palette) for relation in scene.relations}
    return RenderedScene(
        visuals=visuals, targets=targets, relations=relations, roles=roles,
        answer_stages=answer_stages,
    )
```

Add the builder beside `_build_visual`:

```python
def _build_answer_stages(placed, palette: str):
    """One Text per stage, all centred on the same point.

    Every stage is built up front because `Transform` needs a target mobject to
    morph into, and only the `unknown` stage is ever added to the scene: the
    transitions mutate that one mobject rather than adding new ones.
    """
    style = resolve_semantic_style(palette, _initial_role(placed.measured.ref, placed.measured.payload))
    stages = {
        stage: _text(text, "label", placed.bounds.center, placed.scale)
        for stage, text in placed.measured.payload["stages"].items()
    }
    for mobject in stages.values():
        _apply_style(mobject, style)
    return stages["unknown"], stages
```

Extend `_initial_role` so it does not depend on the visual's ref:

```python
    if ref == "evaluated_answer" or "stages" in payload or "values" in payload or "text" in payload:
        return "neutral"
```

Add the animation branch in `_action_animation`, before the `raise`:

```python
    if kind == "show_answer_stage":
        target = action.targets[0].ref
        return Transform(
            _target_mobject(rendered, target),
            rendered.answer_stages[target.visual_ref][action.action.stage],
        )
```

- [ ] **Step 9: Run the renderer test to verify it passes**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_renderer.py -q`
Expected: the new test passes.

- [ ] **Step 10: Commit**

```bash
git add backend/app/meta/v3/resolver.py backend/app/meta/v3/visual_registry.py \
        backend/app/meta/v3/renderer.py backend/tests/meta/v3/
git commit -m "feat: resolve, measure and render the answer's stages"
```

---

### Task 4: Lay the answer out in the lesson column

Delete the reserved bottom strip. The answer arranges like any other visual, forced last in the column so it reads as the outcome.

**Files:**
- Modify: `backend/app/meta/v3/layout.py:10-16` (frame constants), `:53-77` (`place_vertical_lesson`), `:80-101` (`_arrange`); delete `_place_centered_stack` at `:261-276` if nothing else calls it
- Test: `backend/tests/meta/v3/test_layout.py`, `backend/tests/meta/v3/test_scene_resolver.py:205-260`

**Interfaces:**
- Produces: `layout.ANSWER_REF = "evaluated_answer"`; `place_vertical_lesson` keeps its signature and return order (one `PlacedVisual` per input, in input order).

- [ ] **Step 1: Write the failing tests**

In `backend/tests/meta/v3/test_layout.py`, replace the `_answer` helper (`:21-23`)
so it builds a real staged answer:

```python
def _answer(text, measurer):
    spec = type("Spec", (), {"kind": "answer_expression", "ref": "evaluated_answer"})()
    return default_visual_registry().measure(
        spec, {"stages": {"unknown": "?", "value": text}}, measurer,
    )
```

and append:

```python
def test_the_answer_is_the_last_row_of_the_lesson_column():
    measurer = _WidthPerCharacterMeasurer()
    placed = place_vertical_lesson([
        _label("primary", "bar", measurer),
        _label("conversion", "1 km = 1000 m", measurer),
        _answer("2.75 x 1000 = 2750 meters", measurer),
    ])
    by_ref = {item.measured.ref: item for item in placed}

    answer = by_ref["evaluated_answer"]
    assert answer.bounds.top <= by_ref["primary"].bounds.bottom + 1e-9
    for item in placed:
        assert item.bounds.bottom >= SAFE_FRAME.bottom - 1e-9
        assert item.bounds.top <= SAFE_FRAME.top + 1e-9


def test_the_answer_is_not_confined_to_a_bottom_band():
    """The lesson column is centred as a unit, so a short lesson's answer sits
    near the middle rather than being pinned to the frame's bottom edge."""
    measurer = _WidthPerCharacterMeasurer()
    primary, answer = place_vertical_lesson([
        _label("primary", "bar", measurer),
        _answer("7", measurer),
    ])

    column_center = (primary.bounds.top + answer.bounds.bottom) / 2
    assert column_center == pytest.approx(0.0, abs=1e-9)
    assert answer.bounds.bottom > -2.4


def test_a_wide_answer_does_not_get_sorted_above_the_primary_visual():
    """`_balanced_pair` splits wide rows between above and below by extent, so
    without an explicit rule the answer could land over the lesson."""
    measurer = _WidthPerCharacterMeasurer()
    placed = place_vertical_lesson([
        _label("primary", "bar", measurer),
        _label("wide_support", "a" * 40, measurer),
        _answer("b" * 40, measurer),
    ])
    by_ref = {item.measured.ref: item for item in placed}

    assert by_ref["evaluated_answer"].bounds.top <= by_ref["primary"].bounds.bottom + 1e-9


def test_an_answer_only_scene_is_centred_rather_than_failing_to_place():
    measurer = _WidthPerCharacterMeasurer()
    answer, = place_vertical_lesson([_answer("2750 meters", measurer)])

    assert answer.bounds.center.y == pytest.approx(0.0)
```

In `backend/tests/meta/v3/test_scene_resolver.py`, the four band tests at
`:205-260` assert the deleted strip. Rewrite them:

- `test_vertical_layout_centers_primary_and_reserves_conclusion_band` → rename to
  `test_vertical_layout_centers_the_column_including_the_answer` and assert
  `conclusion.bounds.top < primary.bounds.bottom` plus both inside `SAFE_FRAME`,
  dropping every `-2.4` assertion and the `primary.bounds.center.y == 0.6` one
  (the column centre moves now that the band is gone; assert
  `(primary.bounds.top + conclusion.bounds.bottom) / 2 == pytest.approx(0.0)` instead).
- `test_vertical_layout_scales_visuals_and_gaps_inside_safe_frame` → keep as is;
  it only asserts `SAFE_FRAME` containment and gap scaling.
- `test_vertical_layout_keeps_primary_centered_with_supporting_and_conclusion_visuals`
  → drop the `conclusion.bounds.top <= -2.4` assertion and the hard-coded
  `primary.bounds.center.y == 0.6`; keep the side-gap assertion.
- `test_vertical_layout_places_a_conclusion_only_scene_without_scaling_error` →
  assert `conclusion.bounds.center.y == pytest.approx(0.0)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`:
`.venv/bin/pytest tests/meta/v3/test_layout.py tests/meta/v3/test_scene_resolver.py -q`
Expected: the new layout tests fail with the answer pinned below `-2.4`, and the
answer-only test fails with `center.y == -3.0`.

- [ ] **Step 3: Remove the band**

In `backend/app/meta/v3/layout.py`, replace the frame constants:

```python
SAFE_FRAME = Bounds(-6.6, 6.6, -3.6, 3.6)
MIN_TEXT_SCALE = 0.7
GAP = 0.45
#: The answer used to be placed in a reserved strip at the bottom of the frame,
#: which read as a caption stapled under the lesson rather than as its outcome.
#: It is now arranged with everything else, so the instructional frame is the
#: whole safe frame.
INSTRUCTIONAL_FRAME = SAFE_FRAME
ANSWER_REF = "evaluated_answer"
```

Simplify `place_vertical_lesson`:

```python
def place_vertical_lesson(measured_visuals: Sequence[MeasuredVisual]) -> list[PlacedVisual]:
    arrangement = _arrange(measured_visuals)
    scale = min(1.0, _fit_instructional_scale(arrangement, INSTRUCTIONAL_FRAME))
    if scale < MIN_TEXT_SCALE:
        raise V3ValidationError(V3Failure(
            code="below_minimum_text_scale",
            path="visuals",
            expected=f"a uniform scale of at least {MIN_TEXT_SCALE:g}",
            observed=f"{scale:g}",
            hint="reduce visual content so the lesson remains readable",
        ))
    placed_by_ref = {
        item.measured.ref: item
        for item in _place_instructional(arrangement, INSTRUCTIONAL_FRAME, scale)
    }
    return [placed_by_ref[item.ref] for item in measured_visuals]
```

Force the answer to the bottom of the column in `_arrange`:

```python
def _arrange(instructional: Sequence[MeasuredVisual]) -> _Arrangement:
    """Send each supporting visual beside the primary, or to a row of its own.

    A visual placed beside the primary has to fit in half the frame minus the
    primary's half-width -- roughly 3 units, against the 13.2 a full-width row
    offers. Forcing every supporting visual into that slot meant one ordinary
    label ("Perimeter = 2 x (length + width)", 6.6 units) shrank the whole
    lesson's uniform scale below MIN_TEXT_SCALE and failed the candidate
    outright, for want of using space the frame already had.

    The split is decided on unscaled measurements so it does not depend on the
    scale being solved for.

    The answer is exempt from the split: it always takes the last row. Left to
    `_balanced_pair`, a wide answer statement would be sorted into `above` by
    extent and end up over the lesson it concludes.
    """
    if not instructional:
        return _Arrangement(None, [], [], [], [])
    answer = next((item for item in instructional if item.ref == ANSWER_REF), None)
    rest = [item for item in instructional if item is not answer]
    if not rest:
        return _Arrangement(answer, [], [], [], [])
    primary, *supporting = rest
    budget = _side_budget(primary, INSTRUCTIONAL_FRAME)
    beside = [item for item in supporting if _width(item) <= budget]
    stacked = [item for item in supporting if _width(item) > budget]
    left, right = _balanced_pair(beside, _stack_width)
    above, below = _balanced_pair(stacked, lambda items: _stack_height(items, GAP))
    if answer is not None:
        below = [*below, answer]
    return _Arrangement(primary, left, right, above, below)
```

Delete `_place_centered_stack` and the now-unused `_fit_scale` if nothing else
references them — check with
`grep -rn "_place_centered_stack\|_fit_scale" backend/app backend/tests` first,
and leave anything still referenced alone.

- [ ] **Step 4: Run the tests to verify they pass**

Run from `backend/`:
`.venv/bin/pytest tests/meta/v3/test_layout.py tests/meta/v3/test_scene_resolver.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/meta/v3/layout.py backend/tests/meta/v3/test_layout.py \
        backend/tests/meta/v3/test_scene_resolver.py
git commit -m "feat: lay the answer out as the lesson column's last row"
```

---

### Task 5: Stage the answer, and move the two gates that depend on the old timing

The compiler reveals the unresolved answer in the first beat, shows the work at the last derive-or-focus beat, and resolves the value at conclude. Two quality gates encode the old "answer appears only at conclude" contract and must change with it — a reviewer cannot accept one without the other, so they land together.

**Files:**
- Modify: `backend/app/meta/v3/beat_expander.py` (imports; `expand` at `:56-105`; `_beat_kind_actions` conclude branch at `:242-250`; add `_work_beat_id`)
- Modify: `backend/app/meta/v3/quality.py:101-124` (`check_answer_timing`), `:127-145` (`check_conclusion_hold`)
- Test: `backend/tests/meta/v3/test_teaching_compiler.py`, `backend/tests/meta/v3/test_quality.py`

**Interfaces:**
- Consumes: `ShowAnswerStageAction` (Task 2), `has_operation` (Task 1).
- Produces: for a plan declaring an answer, the timeline contains exactly one `reveal` of `evaluated_answer` in the first beat, at most one `show_answer_stage(stage="work")`, and exactly one `show_answer_stage(stage="value")` in the conclude beat alongside `set_role(conclusion)`.

- [ ] **Step 1: Write the failing compiler tests**

Append to `backend/tests/meta/v3/test_teaching_compiler.py`. Reuse the existing
`published_perimeter_plan`, `perimeter_answer` and `compile_context` fixtures:

```python
def test_the_unresolved_answer_is_revealed_in_the_first_beat(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    reveals = [
        entry for entry in program.timeline
        if entry.action.kind == "reveal"
        and any(target.visual_ref == "evaluated_answer" for target in entry.action.targets)
    ]
    assert len(reveals) == 1
    assert reveals[0].beat_id == published_perimeter_plan.beats[0].id


def test_the_work_stage_lands_on_the_derive_beat_and_the_value_on_conclude(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    program = compile_teaching_plan(
        published_perimeter_plan, perimeter_answer,
        frozenset({"length", "width"}), compile_context,
    )

    stages = {
        entry.action.stage: entry.beat_id
        for entry in program.timeline if entry.action.kind == "show_answer_stage"
    }
    work_beat = next(
        beat.id for beat in reversed(published_perimeter_plan.beats[:-1])
        if beat.kind in {"derive", "focus"}
    )
    assert stages == {"work": work_beat, "value": published_perimeter_plan.beats[-1].id}


def test_the_answer_unit_becomes_the_answer_visual_suffix(
    published_perimeter_plan, perimeter_answer, compile_context,
):
    plan = published_perimeter_plan.model_copy(update={"answer_unit": "cm"})

    program = compile_teaching_plan(
        plan, perimeter_answer, frozenset({"length", "width"}), compile_context,
    )

    answer, = [visual for visual in program.visuals if visual.ref == "evaluated_answer"]
    assert answer.suffix == " cm"


def test_an_answer_with_no_arithmetic_gets_no_work_stage(
    published_perimeter_plan, compile_context,
):
    """`has_operation` is false for a bare field reference, so there is nothing
    to show and the lesson goes straight from "?" to the value."""
    bare_answer = FieldRefNode(field="length")

    program = compile_teaching_plan(
        published_perimeter_plan, bare_answer,
        frozenset({"length", "width"}), compile_context,
    )

    stages = {
        entry.action.stage for entry in program.timeline
        if entry.action.kind == "show_answer_stage"
    }
    assert stages == {"value"}


def test_pair_elimination_still_declares_no_answer_visual(
    median_plan, answer, compile_context,
):
    program = compile_teaching_plan(
        median_plan, answer, frozenset({f"v{i}" for i in range(1, 8)}), compile_context,
    )

    assert not [visual for visual in program.visuals if visual.ref == "evaluated_answer"]
    assert not [entry for entry in program.timeline if entry.action.kind == "show_answer_stage"]
    assert program.answer_anchor is not None
```

Add `from app.meta.dsl.expression import FieldRefNode` to that file's imports if
it is not already there.

Two existing tests in this file assert the old timing and must be updated in this
same task:

- `:490-503` (the test asserting the single answer reveal has
  `beat_id == "conclude"`) — change the expected beat to
  `published_perimeter_plan.beats[0].id`, and rename it to say
  `..._is_revealed_once_in_the_first_beat`.
- `:222-235` (`trace < answer_reveal`) — the answer reveal is now the *first*
  thing on the timeline, so this ordering no longer holds. Reassert the intent
  against the resolved value instead: find the index of the
  `show_answer_stage(stage="value")` entry and assert `trace < value_index`.

- [ ] **Step 2: Run the compiler tests to verify they fail**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_teaching_compiler.py -q`
Expected: the new tests fail because no `show_answer_stage` action is ever
emitted and the answer reveal still sits in `conclude`.

- [ ] **Step 3: Stage the answer in the beat expander**

In `backend/app/meta/v3/beat_expander.py`, extend the imports:

```python
from app.meta.dsl.scene_program import (
    AnswerProgramVisual, BarProgramVisual, CalloutRelation, DrawAction,
    GridProgramVisual, LabelProgramVisual, MoveAction, NumberLineProgramVisual,
    ObjectSetProgramVisual, OrderedValuesProgramVisual, PartitionProgramVisual,
    ProgramAction, RectangleProgramVisual, RevealAction, SetRoleAction,
    ShowAnswerStageAction, ShowRelationAction, TraceAction, TransformAction,
)
from app.meta.dsl.v3_common import TargetRef
from app.meta.v3.expression_display import has_operation
```

Give the answer visual its unit, in `expand`:

```python
        if plan.strategy != "pair_elimination":
            # The answer is one of the collection's own values, already on
            # screen. Suppressed at declaration rather than at reveal because
            # `quality.check_unused_visual` fails any visual absent from the
            # timeline.
            visuals.append(AnswerProgramVisual(
                ref="evaluated_answer",
                expression=self.answer_expression,
                suffix=f" {plan.answer_unit}" if plan.answer_unit else "",
            ))
```

Declare the staging targets before the beat loop in `expand`:

```python
        answer_declared = any(visual.ref == "evaluated_answer" for visual in visuals)
        answer_target = TargetRef(visual_ref="evaluated_answer")
        work_beat_id = self._work_beat_id(plan) if answer_declared else None
```

and inside the beat loop, after the `custom_actions` loop and before
`_beat_timing`:

```python
            if answer_declared and beat_index == 0:
                # The unresolved "? unit" is on screen from the start, so the
                # lesson poses its question before answering it. A separate
                # reveal rather than an extra target on the beat: folding it in
                # would also subject the answer to the beat kind's own role
                # change, focusing it before anything has been derived.
                actions.extend(self._reveal_unrevealed(plan, [answer_target], revealed))
            if beat.id == work_beat_id:
                actions.append(
                    ShowAnswerStageAction(target=answer_target, stage="work")
                )
```

Add the beat selector as an **instance** method — the answer expression reaches
the expander through `BeatExpander.__init__`, not through the plan, so this
cannot be a `@staticmethod` taking only `plan`:

```python
    def _work_beat_id(self, plan):
        """The beat that shows the answer's arithmetic, if there is any to show.

        `TeachingPlanDocument.require_focus_and_conclusion_order` guarantees a
        `focus` or `derive` beat before `conclude`, so a slot always exists. The
        last one is chosen so the work appears as late as possible while still
        preceding the conclusion.
        """
        if not has_operation(self.answer_expression):
            return None
        return next(
            beat.id for beat in reversed(plan.beats[:-1])
            if beat.kind in {"derive", "focus"}
        )
```

Replace the `conclude` branch of `_beat_kind_actions` (`:242-250`):

```python
        if beat.kind == "conclude":
            if plan.strategy == "pair_elimination":
                return self._median_callout(plan, beat, relations)
            # The answer is already on screen as "? unit", revealed in the first
            # beat, so conclude resolves it rather than introducing it.
            answer_target = TargetRef(visual_ref="evaluated_answer")
            return [
                ShowAnswerStageAction(target=answer_target, stage="value"),
                *self._role_change(answer_target, "conclusion", current_roles),
            ]
```

`revealed` is no longer touched here, so drop the `revealed.add(...)` line — the
first-beat reveal already recorded it.

- [ ] **Step 4: Run the compiler tests**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_teaching_compiler.py -q`
Expected: the new tests pass. Tests that call `validate_static_quality` may now
fail on `premature_answer_emphasis` or `conclusion_hold_too_short` — that is what
the next two steps fix.

- [ ] **Step 5: Write the failing quality-gate tests**

Append to `backend/tests/meta/v3/test_quality.py`, reusing its existing
`Candidate` dataclass and plan helpers:

```python
def test_the_first_beat_placeholder_reveal_does_not_trip_the_conclusion_hold():
    """`check_conclusion_hold` used to take the minimum duration across EVERY
    entry naming `evaluated_answer`. The first-beat reveal is far shorter than
    the 1.5s floor, so the check failed on a correct lesson."""
    candidate = _perimeter_candidate()

    report = validate_static_quality(candidate.plan, candidate.program)

    hold = next(check for check in report.checks if check.code == "conclusion_hold_too_short")
    assert hold.passed, hold.detail


def test_an_answer_revealed_late_is_rejected():
    candidate = _perimeter_candidate()
    reveal_index = next(
        index for index, entry in enumerate(candidate.program.timeline)
        if entry.action.kind == "reveal"
        and any(target.visual_ref == "evaluated_answer" for target in entry.action.targets)
    )
    moved = candidate.program.timeline[reveal_index].model_copy(
        update={"beat_id": candidate.plan.beats[-1].id},
    )
    timeline = list(candidate.program.timeline)
    timeline[reveal_index] = moved
    program = candidate.program.model_copy(update={"timeline": timeline})

    report = validate_static_quality(candidate.plan, program)

    assert not report.passed
    assert any(check.code == "answer_placeholder_missing" for check in report.checks)


def test_the_resolved_value_may_not_appear_before_conclude():
    candidate = _perimeter_candidate()
    value_index = next(
        index for index, entry in enumerate(candidate.program.timeline)
        if entry.action.kind == "show_answer_stage" and entry.action.stage == "value"
    )
    moved = candidate.program.timeline[value_index].model_copy(
        update={"beat_id": candidate.plan.beats[0].id},
    )
    timeline = list(candidate.program.timeline)
    timeline[value_index] = moved
    program = candidate.program.model_copy(update={"timeline": timeline})

    report = validate_static_quality(candidate.plan, program)

    assert not report.passed
    assert any(
        check.code == "premature_answer_emphasis" and not check.passed
        for check in report.checks
    )


def test_a_staged_perimeter_candidate_passes_every_gate():
    candidate = _perimeter_candidate()

    report = validate_static_quality(candidate.plan, candidate.program)

    assert report.passed, [check for check in report.checks if not check.passed]
```

Add a `_perimeter_candidate()` helper to that file if one does not already exist,
built from the file's existing `_perimeter_plan()` and its answer expression by
calling `compile_teaching_plan` — mirror however the file already produces a
`Candidate`.

- [ ] **Step 6: Run the quality tests to verify they fail**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_quality.py -q`
Expected: `conclusion_hold_too_short` fails on the staged candidate, and the two
new gate tests fail because no `answer_placeholder_missing` code exists.

- [ ] **Step 7: Rewrite the two gates**

In `backend/app/meta/v3/quality.py`, replace `check_answer_timing`:

```python
def check_answer_timing(plan, program) -> QualityCheck:
    """The answer is posed early as "? unit" and resolved only at conclude.

    This check used to require the opposite -- that `evaluated_answer` appear
    ONLY in conclude -- because the answer was a card drawn at the end. Now the
    unresolved placeholder is what the first beat reveals, and the resolved
    value is a stage transition, so the timing contract moves with it.
    """
    answer = next((visual for visual in program.visuals if visual.ref == "evaluated_answer"), None)
    if answer is None:
        # `pair_elimination` states its answer with one of its own values.
        return _passed("premature_answer_emphasis", "visuals")
    if getattr(answer, "initial_role", "neutral") != "neutral":
        return _failed(
            "premature_answer_emphasis", "visuals.evaluated_answer.initial_role",
            "the evaluated answer must begin neutral",
        )

    reveals = [
        index for index, entry in enumerate(program.timeline)
        if entry.action.kind == "reveal"
        and any(target.visual_ref == "evaluated_answer" for target in entry.action.targets)
    ]
    first_beat_id = program.timeline[0].beat_id
    if len(reveals) != 1 or program.timeline[reveals[0]].beat_id != first_beat_id:
        return _failed(
            "answer_placeholder_missing", "timeline",
            "the unresolved answer must be revealed exactly once, in the first beat, "
            "so the lesson poses its question before answering it",
        )

    # Only the FINAL beat may be `conclude`
    # (`TeachingPlanDocument.require_focus_and_conclusion_order`), so that is the
    # one beat in which the resolved value may appear. Kept as an independent
    # second layer: if the plan schema's beat-order rule is ever relaxed, this
    # check still fails the candidate rather than silently reporting success.
    conclusion_id = plan.beats[-1].id if plan.beats[-1].kind == "conclude" else None
    seen = []
    for index, entry in enumerate(program.timeline):
        if entry.action.kind != "show_answer_stage":
            continue
        stage = entry.action.stage
        if stage in seen:
            return _failed(
                "premature_answer_emphasis", f"timeline[{index}].action.stage",
                f"the {stage} stage is shown more than once",
            )
        seen.append(stage)
        if stage == "value" and entry.beat_id != conclusion_id:
            return _failed(
                "premature_answer_emphasis", f"timeline[{index}].beat_id",
                "the resolved answer may only appear in conclude",
            )
    if seen not in ([], ["value"], ["work", "value"]):
        return _failed(
            "premature_answer_emphasis", "timeline",
            f"answer stages must run work then value; found {seen}",
        )
    return _passed("premature_answer_emphasis", "visuals.evaluated_answer")
```

and replace `check_conclusion_hold`:

```python
def check_conclusion_hold(program) -> QualityCheck:
    """Every action of the final acting beat must hold for the floor.

    Scoped to that beat rather than to every entry naming `evaluated_answer`:
    the answer is now revealed in the FIRST beat too, and that short reveal
    would otherwise set the minimum and fail the check on a correct lesson.
    `timeline.schedule_beats` identifies its own conclusion the same way.
    """
    final_beat_id = program.timeline[-1].beat_id
    conclusion_entries = [entry for entry in program.timeline if entry.beat_id == final_beat_id]
    conclusion_end = max(entry.at_seconds + entry.duration_seconds for entry in conclusion_entries)
    shortest_conclusion_action = min(entry.duration_seconds for entry in conclusion_entries)
    if (
        shortest_conclusion_action + 1e-9 < MIN_CONCLUSION_HOLD_SECONDS
        or conclusion_end > program.total_duration_seconds + 1e-9
    ):
        return _failed("conclusion_hold_too_short", "timeline", "the conclusion must remain visible for at least 1.5 seconds")
    return _passed("conclusion_hold_too_short", "timeline")
```

- [ ] **Step 8: Run both test files to verify they pass**

Run from `backend/`:
`.venv/bin/pytest tests/meta/v3/test_quality.py tests/meta/v3/test_teaching_compiler.py -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/meta/v3/beat_expander.py backend/app/meta/v3/quality.py \
        backend/tests/meta/v3/test_quality.py backend/tests/meta/v3/test_teaching_compiler.py
git commit -m "feat: pose the answer early and resolve it at conclude"
```

---

### Task 6: Gates for a dead placeholder and unshown work

Two new gates. One rejects a model-authored `?` label competing with the system's answer — the exact kilometers fault. The other makes "visible work before the answer" enforceable.

**Files:**
- Modify: `backend/app/meta/v3/quality.py` (add two checks; register both in `validate_static_quality` at `:54-73`)
- Modify: `docs/superpowers/specs/2026-08-04-answer-resolution-in-place-design.md` (the `check_strategy_affordance` paragraph)
- Test: `backend/tests/meta/v3/test_quality.py`

**Interfaces:**
- Consumes: `has_operation` (Task 1).
- Produces: `check_answer_stand_in(program)` with code `answer_stand_in_label`; `check_answer_work_shown(program)` with code `answer_work_not_shown`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/meta/v3/test_quality.py`:

```python
def test_a_label_using_a_question_mark_as_the_answer_is_rejected():
    """The kilometers draft authored `? meters` while the compiler appended its
    own answer, so the lesson showed two answers, one of them dead."""
    from app.meta.v3.quality import check_answer_stand_in

    program = _perimeter_candidate().program
    program = program.model_copy(update={
        "visuals": [*program.visuals, LabelProgramVisual(ref="answer_label", text="? meters")],
    })

    check = check_answer_stand_in(program)

    assert not check.passed
    assert check.code == "answer_stand_in_label"


def test_a_question_prompt_label_is_left_alone():
    """A stand-in uses "?" as a value, so the mark sits mid-string; a question
    ends with it."""
    from app.meta.v3.quality import check_answer_stand_in

    program = _perimeter_candidate().program
    program = program.model_copy(update={
        "visuals": [
            *program.visuals,
            LabelProgramVisual(ref="prompt", text="What is the perimeter?"),
        ],
    })

    assert check_answer_stand_in(program).passed


def test_an_answer_with_arithmetic_must_show_its_work():
    from app.meta.v3.quality import check_answer_work_shown

    program = _perimeter_candidate().program
    timeline = [
        entry for entry in program.timeline
        if not (entry.action.kind == "show_answer_stage" and entry.action.stage == "work")
    ]
    stripped = program.model_copy(update={"timeline": timeline})

    check = check_answer_work_shown(stripped)

    assert not check.passed
    assert check.code == "answer_work_not_shown"


def test_a_staged_candidate_shows_its_work():
    from app.meta.v3.quality import check_answer_work_shown

    assert check_answer_work_shown(_perimeter_candidate().program).passed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_quality.py -q`
Expected: `ImportError: cannot import name 'check_answer_stand_in'`.

- [ ] **Step 3: Add the two gates**

In `backend/app/meta/v3/quality.py`, add the import:

```python
from app.meta.v3.expression_display import has_operation
```

and the checks:

```python
def check_answer_stand_in(program) -> QualityCheck:
    """No label may stand in for the answer.

    The system supplies the answer statement, so a label like "? meters" is a
    second, dead answer competing with it -- which is exactly what the
    kilometers draft produced. A question prompt is legitimate teaching, and a
    stand-in is distinguishable from one without reading the wording: a stand-in
    uses "?" as a value, so the mark sits mid-string, while a question ends with
    it.
    """
    for index, visual in enumerate(program.visuals):
        if visual.kind != "label":
            continue
        if "?" in visual.text[:-1]:
            return _failed(
                "answer_stand_in_label", f"visuals[{index}].text",
                "this label stands in for the answer; the system supplies the answer "
                "statement, so remove the label and name the unit in answer_unit",
            )
    return _passed("answer_stand_in_label", "visuals")


def check_answer_work_shown(program) -> QualityCheck:
    """An answer with arithmetic must show that arithmetic before resolving.

    Without this, a `derive` beat whose targets already hold their role compiles
    to a bare recolour and the lesson states its answer having demonstrated
    nothing -- the kilometers lesson's original failing.
    """
    answer = next((visual for visual in program.visuals if visual.ref == "evaluated_answer"), None)
    if answer is None or not has_operation(answer.expression):
        return _passed("answer_work_not_shown", "timeline")
    if not any(
        entry.action.kind == "show_answer_stage" and entry.action.stage == "work"
        for entry in program.timeline
    ):
        return _failed(
            "answer_work_not_shown", "timeline",
            "the answer's arithmetic is never shown; give the lesson a derive or focus "
            "beat before its conclusion so the calculation appears before the answer",
        )
    return _passed("answer_work_not_shown", "timeline")
```

Register both in `validate_static_quality`, after `check_answer_timing`:

```python
        check_answer_timing(plan, program),
        check_answer_stand_in(program),
        check_answer_work_shown(program),
```

- [ ] **Step 4: Amend the spec to match**

The spec says the derive requirement is folded into
`check_strategy_affordance`. It is a separate check instead, because a failed
check's `code` is fed back to the model as repair feedback
(`draft_generation._reviewer_feedback_context`) and reusing
`static_process_visual` for a missing work stage would name the wrong problem.
In `docs/superpowers/specs/2026-08-04-answer-resolution-in-place-design.md`,
replace the `check_strategy_affordance` paragraph's heading and first sentence
with:

```markdown
**New `check_answer_work_shown`.** When a program declares `evaluated_answer`
and its `answer_expression` contains at least one operation, the timeline must
contain a `work` stage. A separate check rather than a clause inside
`check_strategy_affordance`, so the failure reports its own code
(`answer_work_not_shown`) rather than borrowing `static_process_visual`, which
would name the wrong problem in the repair feedback the model reads.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_quality.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/meta/v3/quality.py backend/tests/meta/v3/test_quality.py \
        docs/superpowers/specs/2026-08-04-answer-resolution-in-place-design.md
git commit -m "feat: reject a dead answer placeholder and unshown work"
```

---

### Task 7: Teach the model the new contract

The prompt currently tells the model the answer appears only at conclude, which is now false, and says nothing about `answer_unit`.

**Files:**
- Modify: `backend/app/meta/draft_generation.py:52-56` (inside `_DRAFT_SYSTEM_PROMPT`)
- Test: `backend/tests/meta/test_draft_generation.py`

**Interfaces:**
- Consumes: `answer_unit` (Task 2).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/meta/test_draft_generation.py`:

```python
def test_the_prompt_hands_answer_presentation_to_the_system():
    from app.meta.draft_generation import _DRAFT_SYSTEM_PROMPT

    assert "answer_unit" in _DRAFT_SYSTEM_PROMPT
    assert 'never put "?" in a label' in _DRAFT_SYSTEM_PROMPT
    # The old instruction is false now: the unresolved answer appears from the
    # first beat, and only its VALUE waits for conclude.
    assert "introduced only during\nconclude" not in _DRAFT_SYSTEM_PROMPT
    assert "the final evaluated answer is introduced only during" not in _DRAFT_SYSTEM_PROMPT
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `backend/`:
`.venv/bin/pytest tests/meta/test_draft_generation.py::test_the_prompt_hands_answer_presentation_to_the_system -q`
Expected: FAIL — `answer_unit` is absent and the old sentence is present.

- [ ] **Step 3: Replace the sentence**

In `backend/app/meta/draft_generation.py`, inside `_DRAFT_SYSTEM_PROMPT`, replace:

```python
    "custom actions only inside their owning beat. All answer-related visuals "
    "start neutral, and the final evaluated answer is introduced only during "
    "conclude. Simple collections reveal together. Perimeter explanations use "
```

with:

```python
    "custom actions only inside their owning beat. The system supplies the "
    "answer statement and stages it for you: it appears from the first beat as "
    "an unresolved \"? unit\", shows its arithmetic at the derive beat, and "
    "resolves to the value only at conclude. Name the unit of the result in "
    "answer_unit (\"meters\"; empty if unitless). Never author a label standing "
    "in for the answer, and never put \"?\" in a label. "
    "Simple collections reveal together. Perimeter explanations use "
```

- [ ] **Step 4: Run the test to verify it passes**

Run from `backend/`: `.venv/bin/pytest tests/meta/test_draft_generation.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/meta/draft_generation.py backend/tests/meta/test_draft_generation.py
git commit -m "feat: tell the model the system stages the answer"
```

---

### Task 8: End-to-end on the kilometers lesson, and a green suite

Prove the whole thing on the lesson that motivated it, and sweep the tests that still assume the old answer shape.

**Files:**
- Test: create `backend/tests/meta/v3/test_answer_resolution_end_to_end.py`
- Modify (as failures dictate): `backend/tests/meta/test_demo_end_to_end.py:582-590`, `backend/tests/meta/v3/test_render_probe.py`, `backend/tests/meta/test_v3_demo_quality.py`, `backend/tests/render/test_full_render.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.

- [ ] **Step 1: Write the end-to-end test**

Create `backend/tests/meta/v3/test_answer_resolution_end_to_end.py`:

```python
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
        "strategy": "magnitude_comparison",
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
    # The old reserved band was y in [-3.6, -2.4]; nothing pins the answer there.
    assert answer.bounds.bottom > -2.4
```

- [ ] **Step 2: Run it to verify it fails or passes for the right reasons**

Run from `backend/`: `.venv/bin/pytest tests/meta/v3/test_answer_resolution_end_to_end.py -q`
Expected: all four pass if Tasks 1–7 are complete. If any fail, fix the
implementation — not the assertions: these are the spec's success criterion.

- [ ] **Step 3: Run the full suite and read every failure**

Run from `backend/`: `.venv/bin/pytest -q`

Expect fallout in tests that assume the old answer shape. For each, update the
test to the new contract — do not weaken an assertion to make it pass:

- `tests/meta/test_demo_end_to_end.py:590` reads
  `resolved.visual("evaluated_answer").measured.payload["text"]`. Change to
  `payload["stages"]["value"]`.
- `tests/meta/v3/test_render_probe.py:38,59,101` uses `evaluated_answer` in
  hand-written manifests. The probe does not whitelist action kinds and
  `_answer_visible` still reads `rendered.visuals["evaluated_answer"]`, so these
  should pass unchanged; if one fails, the manifest's expectations are what to
  reread, and only adjust what the new staging genuinely changed.
- `tests/meta/test_v3_demo_quality.py` and `tests/render/test_full_render.py`
  compile whole lessons. If a plan there now fails `answer_work_not_shown` or
  `answer_stand_in_label`, the plan fixture itself needs the fix the model will
  now be told to make: drop any `?` label, add `answer_unit`.

- [ ] **Step 4: Confirm the suite is green**

Run from `backend/`: `.venv/bin/pytest -q`
Expected: 0 failed. Paste the summary line into the commit body — do not claim
green without it (`superpowers:verification-before-completion`).

- [ ] **Step 5: Commit**

```bash
git add backend/tests
git commit -m "test: prove answer resolution end to end on the kilometers lesson"
```

- [ ] **Step 6: Render the lesson and look at it**

The suite does not prove the video reads well. Render the kilometers lesson and
watch the answer resolve:

```bash
cd backend && .venv/bin/pytest tests/render/test_full_render.py -q
```

then check `media/videos/1080p60/` for the produced file. Confirm by eye: the
`? meters` is present from the start, the multiplication appears mid-lesson, the
value replaces the `?` without the text jumping, and nothing sits in a detached
strip at the bottom. Report what you see — including anything that looks wrong.

---

## Self-Review

**Spec coverage.** Three-stage statement → Tasks 1, 3, 5. `ShowAnswerStageAction`
→ Task 2. `answer_unit` → Tasks 2, 5, 7. Compiler staging table → Task 5.
Layout / band deletion → Task 4. Rendering and measurement → Task 3. Expression
printing incl. non-associativity → Task 1. All four quality-gate changes →
Tasks 5 (two) and 6 (two). Prompt → Task 7. Compatibility (additive schema,
defaults) → Tasks 2 and 8. Verification list → Tasks 1–8, with the spec's
success criterion asserted in Task 8 Step 1.

**Deliberate deviation from the spec, amended in Task 6 Step 4.** The derive
requirement is a separate `check_answer_work_shown` rather than a clause inside
`check_strategy_affordance`, so the repair feedback the model reads carries the
right code.

**Naming consistency.** `expression_display`, `format_number`, `has_operation`
(Task 1) are used under those exact names in Tasks 3, 5 and 6.
`RenderedScene.answer_stages` (Task 3) is read under that name in Task 3 Step 8.
`layout.ANSWER_REF` (Task 4) is defined and used only within Task 4.
`_work_beat_id` is an instance method reading `self.answer_expression`, since
`TeachingPlanDocument` carries no expression.

**Not covered, by design.** `docs/meta-template-demo.md` describes the demo
runbook's two published lessons; neither its text nor the published templates
need changing for this work (see the spec's Compatibility section).
