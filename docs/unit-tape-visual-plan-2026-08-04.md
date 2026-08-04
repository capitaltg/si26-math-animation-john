# `unit_tape` Visual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the meta-generation loop produce a lesson for "convert 2.75 km to meters" by adding a `unit_tape` visual kind, a compiler-staged `unit_substitution` strategy, and the schema-level steering that stops the model reaching for `bar` on large magnitudes.

**Architecture:** A v3 visual kind is declared in five places and consumed in four. Declared: the plan schema (`dsl/teaching_plan.py`), the frozen program schema (`dsl/scene_program.py`), the resolver's expression-evaluation branch, the measurement factory registry (`v3/visual_registry.py`), and the compiler's part/expression maps. Consumed: the beat expander (which program-visual class and strategy staging), the static quality gate, the renderer, and the render probe. Every gate runs before a draft is persisted, so a kind that compiles but cannot render surfaces as `needs_manual_authoring`, never as a broken draft.

**Tech Stack:** Python 3.13, pydantic v2, manim, pytest, SQLite via SQLAlchemy, AWS Bedrock for generation.

## Global Constraints

- Design doc: `docs/unit-tape-visual-design-2026-08-04.md`. Read it before Task 1.
- Run tests with `backend/.venv/bin/pytest` from `backend/`. Never `python -m pytest`.
- `MAX_PART_CARDINALITY = 128` (`v3/visual_registry.py:84`) stays unchanged.
- `MAX_TAPE_BOXES = 8` is the new tape cap.
- Box count is `ceil(value)`; full boxes `floor(value)`; remainder `value - floor(value)`.
- All learner-facing numbers use `expression_display.format_number`, never `resolver._format_value` (which prints `11/4` for 2.75).
- Strategy vocabulary is a closed `Literal` in `TeachingPlanDocument.strategy`; `unit_substitution` is added to it and to `_SUPPORTED_STRATEGIES`.
- Existing tests must stay green. In particular `tests/meta/v3/test_visual_registry.py:173` asserts a two-marker `number_line` has exactly 2 parts — number-line labels are drawn from the payload, not registered as parts.
- Do not touch `regroup` or `magnitude_comparison` (issue #66). Out of scope.
- One commit per task, message style per repo history (`feat:`, `fix:`, `docs:`).

## File Structure

**Phase 1 — steering (PR1).** No new files.

- Modify `backend/app/meta/v3/visual_registry.py` — cardinality hint text; number-line label measurement.
- Modify `backend/app/meta/dsl/teaching_plan.py` — field descriptions on count-driven fields.
- Modify `backend/app/meta/draft_generation.py` — one system-prompt sentence.
- Modify `backend/app/meta/v3/renderer.py` — draw number-line marker labels.
- Modify `backend/tests/meta/v3/test_visual_registry.py` — new assertions.
- Create `backend/tests/meta/dsl/test_visual_field_descriptions.py` — the schema-reaches-the-model test.

**Phase 2 — the tape (PR2).**

- Modify `backend/app/meta/dsl/teaching_plan.py` — `UnitTapeVisual`, strategy enum, plan-shape validator.
- Modify `backend/app/meta/dsl/scene_program.py` — `UnitTapeProgramVisual`.
- Modify `backend/app/meta/v3/resolver.py` — `evaluate_program_visual` branch.
- Modify `backend/app/meta/v3/visual_registry.py` — `_measure_unit_tape`, `DEFERRED_PARTS`, derived cardinality, `_SUPPORTED_STRATEGIES`.
- Modify `backend/app/meta/v3/compiler.py` — `_EXPRESSION_FIELDS`, `_PART_CARDINALITY`.
- Modify `backend/app/meta/v3/beat_expander.py` — `_PROGRAM_VISUALS`, deferred-part bookkeeping, substitution staging.
- Modify `backend/app/meta/v3/quality.py` — `check_strategy_affordance`, `check_repeated_reveal`.
- Modify `backend/app/meta/v3/renderer.py` — `_build_unit_tape`.
- Create `backend/tests/meta/v3/test_unit_tape.py` — measurement, cardinality, compiler, expander, quality.
- Modify `backend/tests/meta/v3/test_render_probe.py` — one tape render.

---

# Phase 1 — steering (PR1)

Deliverable: slide 4 stops dead-ending. The model is told what count-driven fields cost, the repair hint names the cap and the alternative, and `number_line` is worth being steered to.

### Task 1: Put the cap and the alternative in the failure hint

**Files:**
- Modify: `backend/app/meta/v3/visual_registry.py:87-101`
- Test: `backend/tests/meta/v3/test_visual_registry.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_cardinality_failure(spec, field_name, observed, cap, unit_word) -> V3ValidationError`, used again in Task 8.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/meta/v3/test_visual_registry.py`:

```python
def test_the_cardinality_hint_carries_the_cap_and_an_alternative_kind():
    """The retry loop only forwards `code`, `path` and `hint`.

    `generation_pipeline.generate_and_validate_revision` builds its repair
    feedback from those three fields, so a ceiling stated only in `expected`
    never reaches the model. Two Bedrock attempts on job
    645f54b89af444fca04ea00a25d876cc both proposed `maximum=10000` unchanged,
    because "reduce the value driving this visual's size" named no target and no
    alternative -- and no value of `maximum` can draw 2750-out-of-10000 anyway.
    """
    with pytest.raises(V3ValidationError) as exc_info:
        default_visual_registry().measure(
            SimpleNamespace(kind="bar", ref="m_bar"),
            {"value": Fraction(2750), "maximum": Fraction(10000)},
            LiteralTextMeasurer(),
        )

    hint = exc_info.value.failure.hint
    assert "128" in hint
    assert "number_line" in hint
    assert "maximum" in hint
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_visual_registry.py::test_the_cardinality_hint_carries_the_cap_and_an_alternative_kind -v
```

Expected: FAIL — the hint is `reduce the value driving this visual's size (maximum=10000)`, so `"128"` and `"number_line"` are both absent.

- [ ] **Step 3: Replace `_require_renderable_cardinality`**

In `backend/app/meta/v3/visual_registry.py`, replace the existing function (lines 87-101) with:

```python
#: What to reach for when a count-driven visual is too large. `number_line`
#: places markers inside fixed +/-2.75 bounds, so its `maximum` is a scale and a
#: line from 0 to a million costs nothing to draw.
_LARGE_MAGNITUDE_ALTERNATIVE = "a number_line, whose maximum is a scale rather than a part count"


def _cardinality_failure(spec, field_name, observed, cap, unit_word) -> V3ValidationError:
    """A refusal that names the cap, the field, and what to use instead.

    The hint carries all three because it is the only one of these fields the
    generation retry loop forwards to the model
    (`draft_generation._STABLE_REPAIR_FEEDBACK_FIELDS`).
    """
    return V3ValidationError(V3Failure(
        code="visual_extent_unrenderable",
        path=f"visuals.{spec.ref}",
        expected=f"a {spec.kind} of at most {cap} parts",
        observed=f"{spec.ref} would draw {observed} parts ({field_name}={observed})",
        hint=(
            f"{spec.kind} draws one part per {unit_word}, at most {cap}; "
            f"reduce {field_name} (currently {observed}) or use {_LARGE_MAGNITUDE_ALTERNATIVE}"
        ),
    ))


def _require_renderable_cardinality(spec, values) -> None:
    for name in _CARDINALITY_FIELDS.get(spec.kind, ()):
        if name not in values:
            continue
        count = _whole(values[name], name) if _is_whole(values[name]) else None
        if count is not None and count <= MAX_PART_CARDINALITY:
            continue
        raise _cardinality_failure(
            spec, name, _describe(values[name]), MAX_PART_CARDINALITY, f"unit of {name}",
        )
```

- [ ] **Step 4: Run the whole registry suite**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_visual_registry.py -v
```

Expected: PASS, including the pre-existing `test_a_count_driven_visual_too_large_to_render_is_rejected_by_name` (it asserts `driver in failure.hint or driver in failure.observed`, and the field name is still in both).

- [ ] **Step 5: Commit**

```bash
git add backend/app/meta/v3/visual_registry.py backend/tests/meta/v3/test_visual_registry.py
git commit -m "fix: name the cap and an alternative kind in the cardinality hint"
```

---

### Task 2: Tell the model what count-driven fields cost

**Files:**
- Modify: `backend/app/meta/dsl/teaching_plan.py:28-66`
- Modify: `backend/app/meta/draft_generation.py:38-80`
- Test: `backend/tests/meta/dsl/test_visual_field_descriptions.py` (create)

**Interfaces:**
- Consumes: `MAX_PART_CARDINALITY` from `app.meta.v3.visual_registry`.
- Produces: nothing consumed by later tasks. Task 5 extends these description strings to mention `unit_tape`.

Background for the implementer: `draft_generation.propose_template_draft` sends `DraftProposal.model_json_schema()` to Bedrock as the tool schema. A pydantic `Field(description=...)` therefore lands in the model's prompt. This is the only channel that can prevent the mistake before it happens; the validator can only refuse it afterwards.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/meta/dsl/test_visual_field_descriptions.py`:

```python
"""Every field that drives a part count must say so in the tool schema.

`draft_generation.propose_template_draft` sends `DraftProposal.model_json_schema()`
to Bedrock, so a field's `description` is documentation the model actually reads.
`BarVisual.maximum` had none, and the model read it as an axis maximum: it
proposed 10000 for a 2750-metre answer, which `_measure_bar` would have built as
10000 rectangles.
"""

from app.meta.draft_generation import DraftProposal
from app.meta.v3.visual_registry import MAX_PART_CARDINALITY

#: Model class name -> fields whose value decides how many parts get drawn.
COUNT_DRIVEN_FIELDS = {
    "BarVisual": ("maximum",),
    "GridVisual": ("rows", "columns"),
    "ObjectSetVisual": ("count",),
    "PartitionVisual": ("parts",),
}


def _description(definitions, model_name, field_name) -> str:
    return definitions[model_name]["properties"][field_name].get("description", "")


def test_every_count_driven_field_states_its_cap_and_an_alternative():
    definitions = DraftProposal.model_json_schema()["$defs"]

    for model_name, field_names in COUNT_DRIVEN_FIELDS.items():
        for field_name in field_names:
            description = _description(definitions, model_name, field_name)
            assert str(MAX_PART_CARDINALITY) in description, f"{model_name}.{field_name} omits the cap"
            assert "number_line" in description, f"{model_name}.{field_name} omits the alternative"


def test_the_number_line_scale_is_not_described_as_a_count():
    """`number_line.maximum` and `bar.maximum` share a name and mean opposites."""
    definitions = DraftProposal.model_json_schema()["$defs"]

    description = _description(definitions, "NumberLineVisual", "maximum")
    assert "scale" in description
    assert str(MAX_PART_CARDINALITY) not in description
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/meta/dsl/test_visual_field_descriptions.py -v
```

Expected: FAIL — every description is currently empty. If the failure is instead a `KeyError` on a `$defs` name, print `sorted(DraftProposal.model_json_schema()["$defs"])` and use the names pydantic actually emitted; adjust `COUNT_DRIVEN_FIELDS` keys to match, and keep the rest of the test unchanged.

- [ ] **Step 3: Add the descriptions**

In `backend/app/meta/dsl/teaching_plan.py`, replace the five visual classes' count-driven fields:

```python
class NumberLineVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["number_line"] = "number_line"
    ref: GeneratedText
    minimum: ExpressionNode
    maximum: ExpressionNode = Field(description=(
        "The line's numeric scale, NOT a count of anything drawn. Markers land "
        "inside fixed bounds, so a line from 0 to a million costs no more to draw "
        "than one from 0 to 10. Use this visual for any magnitude too large to "
        "show as individual parts."
    ))
    markers: list[ExpressionNode] = Field(
        default_factory=list, max_length=16,
        description=(
            "The values to mark on the line, each labelled with its number. "
            "Include minimum and maximum among the markers when the learner needs "
            "the ends labelled."
        ),
    )


class GridVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["grid"] = "grid"
    ref: GeneratedText
    rows: ExpressionNode = Field(description=(
        "Number of rows. One cell rectangle is drawn per row x column, at most 128 "
        "cells in total; for a magnitude larger than that use a number_line."
    ))
    columns: ExpressionNode = Field(description=(
        "Number of columns. One cell rectangle is drawn per row x column, at most "
        "128 cells in total; for a magnitude larger than that use a number_line."
    ))


class PartitionVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["partition"] = "partition"
    ref: GeneratedText
    whole: ExpressionNode
    parts: ExpressionNode = Field(description=(
        "How many equal parts the whole is divided into, drawn one marker per "
        "part, at most 128. For a magnitude larger than that use a number_line."
    ))


class BarVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["bar"] = "bar"
    ref: GeneratedText
    value: ExpressionNode = Field(description=(
        "How much of the bar is filled, in the same units as maximum."
    ))
    maximum: ExpressionNode = Field(description=(
        "The bar's length as a COUNT of equal segments: one rectangle is drawn per "
        "unit, at most 128, and only about 29 fit the frame. This is NOT an axis "
        "maximum -- a quantity like 2750 out of 10000 must not be a bar. Show a "
        "magnitude that large on a number_line, whose maximum is a scale."
    ))


class ObjectSetVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["object_set"] = "object_set"
    ref: GeneratedText
    count: ExpressionNode = Field(description=(
        "How many objects to draw, one dot each, five per row, at most 128. For a "
        "magnitude larger than that use a number_line."
    ))
```

- [ ] **Step 4: Add the prompt sentence**

In `backend/app/meta/draft_generation.py`, inside `_DRAFT_SYSTEM_PROMPT`, immediately after the sentence ending `"Median ordered values use item-specific targets. "`, insert:

```python
        "Choose a visual whose parts a learner could count: bar, grid, "
        "object_set and partition each draw one part per unit, so a magnitude "
        "beyond a couple of dozen units belongs on a number_line, whose maximum "
        "is a scale rather than a part count. "
```

No test asserts this string. A `"number_line" in _DRAFT_SYSTEM_PROMPT` assertion would restate the edit rather than test behaviour, and the repo already tracks that class of non-discriminating test as issue #57.

- [ ] **Step 5: Run the new test plus the schema suites**

```bash
cd backend && .venv/bin/pytest tests/meta/dsl tests/meta/test_draft_generation.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/meta/dsl/teaching_plan.py backend/app/meta/draft_generation.py backend/tests/meta/dsl/test_visual_field_descriptions.py
git commit -m "feat: tell the model which visual fields are part counts"
```

---

### Task 3: Label the number line's markers

**Files:**
- Modify: `backend/app/meta/v3/visual_registry.py:158-175` (`_measure_number_line`)
- Modify: `backend/app/meta/v3/renderer.py:202-203` (the `markers` branch) and add a helper near `_line_visual`
- Test: `backend/tests/meta/v3/test_visual_registry.py`

**Interfaces:**
- Consumes: `expression_display.format_number`.
- Produces: `number_line` payload keys `marker_labels: tuple[str, ...]` and `label_center_y: float`, read by `renderer._number_line_labels`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/meta/v3/test_visual_registry.py`:

```python
def test_a_number_line_labels_each_marker_and_reserves_room_below_the_line():
    """A line of unlabelled dots shows a position without saying what it is.

    `number_line` is the kind the cardinality hint steers a large magnitude
    towards, so it has to teach that magnitude rather than show a bare line.
    Labels are payload, not parts: nothing addresses them, and
    `test_a_number_line_keeps_a_large_numeric_range` pins the part count.
    """
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="number_line", ref="line"),
        {"minimum": Fraction(0), "maximum": Fraction(3000),
         "markers": [Fraction(0), Fraction(2750), Fraction(3000)]},
        LiteralTextMeasurer(),
    )

    assert measured.payload["marker_labels"] == ("0", "2750", "3000")
    # The label strip sits below the line's own -0.2 extent.
    assert measured.bounds.bottom < -0.2
    assert measured.payload["label_center_y"] < -0.2
    # Horizontal bounds are untouched: `renderer._line_visual` draws the line
    # from bounds.left to bounds.right, so widening them stretches the line.
    assert (measured.bounds.left, measured.bounds.right) == (-2.75, 2.75)


def test_a_number_line_marker_label_is_a_decimal_not_a_ratio():
    measured = default_visual_registry().measure(
        SimpleNamespace(kind="number_line", ref="line"),
        {"minimum": Fraction(0), "maximum": Fraction(4), "markers": [Fraction(11, 4)]},
        LiteralTextMeasurer(),
    )

    assert measured.payload["marker_labels"] == ("2.75",)
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_visual_registry.py -k number_line -v
```

Expected: FAIL with `KeyError: 'marker_labels'`.

- [ ] **Step 3: Measure the labels**

In `backend/app/meta/v3/visual_registry.py`, add the import and constant near the top:

```python
from app.meta.v3.expression_display import format_number
```

```python
#: Clear of the line without crowding it, matching `rectangle_measurement.LABEL_GAP`.
MARKER_LABEL_GAP = 0.28
```

Replace `_measure_number_line` with:

```python
def _measure_number_line(*, spec, values, measurer):
    minimum, maximum = values["minimum"], values["maximum"]
    if maximum <= minimum:
        raise ValueError("number_line maximum must exceed minimum")
    left, right = -2.75, 2.75
    markers = values["markers"]
    parts = {}
    labels = []
    for index, marker in enumerate(markers):
        if not minimum <= marker <= maximum:
            raise ValueError(f"marker {marker} outside [{minimum}, {maximum}]")
        x = left + (right - left) * float((marker - minimum) / (maximum - minimum))
        parts[("marker", index)] = SemanticPart("marker", index, Bounds(x, x, 0, 0))
        labels.append(format_number(marker))
    # Reserve the strip the labels occupy, so layout does not place the next
    # visual on top of them. Horizontal bounds stay at +/-2.75: `_line_visual`
    # draws the line across the full bounds, so padding them lengthens the line.
    label_height = max(
        (measurer.measure(text, "label")[1] for text in labels), default=0.0,
    )
    bottom = -0.2 - MARKER_LABEL_GAP - label_height
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left, right, bottom, 0.2),
        parts=parts,
        payload={
            "minimum": minimum, "maximum": maximum, "markers": tuple(markers),
            "marker_labels": tuple(labels),
            "label_center_y": bottom + label_height / 2,
        },
    )
```

- [ ] **Step 4: Run the measurement tests**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_visual_registry.py -v
```

Expected: PASS, including `test_a_number_line_keeps_a_large_numeric_range` (`len(visual.parts) == 2` still holds — labels are payload).

- [ ] **Step 5: Draw the labels**

In `backend/app/meta/v3/renderer.py`, replace the `markers` branch of `_build_visual` (line 202-203):

```python
    elif "markers" in payload:
        root, children = _line_visual(bounds, measured, placed.offset, "marker")
        root.add(*_number_line_labels(measured, placed))
```

And add, immediately after `_line_visual`:

```python
def _number_line_labels(measured, placed):
    """The number under each tick.

    Added to the root group rather than registered as children: nothing addresses
    a tick label, and `measured.parts` is what the compiler validates plan targets
    against, so registering them would invent targets no plan should use.
    """
    payload = measured.payload
    y = payload["label_center_y"] + placed.offset.y
    return [
        _text(
            payload["marker_labels"][index],
            "label",
            Point(part.bounds.center.x + placed.offset.x, y),
            placed.scale,
        )
        for (part_name, index), part in sorted(measured.parts.items(), key=lambda item: item[0][1])
        if part_name == "marker"
    ]
```

- [ ] **Step 6: Render one to prove the labels reach a frame**

Add to `backend/tests/meta/v3/test_render_probe.py`. Note the call shape that file already uses: `ProbeRequest(scene_program=…, known_fields=[…], field_values={…})`, `known_fields` is a list of names, and `run_probe_subprocess(...)` returns an object whose `.manifest` holds the dict.

```python
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
            {"id": "state_total", "kind": "conclude", "targets": [{"visual_ref": "evaluated_answer"}],
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
        field_values={"distance_km": 2.75},
    )).manifest

    assert "distance_line" in manifest["visual_bounds"]
```

Add `LiteralNode` to that module's `app.meta.dsl.expression` import line (it already imports `FieldRefNode` and `MultiplyNode`).

- [ ] **Step 7: Run the probe test**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_render_probe.py -v
```

Expected: PASS. A `KeyError` on `label_center_y` or `marker_labels` means the payload and renderer disagree — fix the renderer, not the test.

- [ ] **Step 8: Commit**

```bash
git add backend/app/meta/v3/visual_registry.py backend/app/meta/v3/renderer.py backend/tests/meta/v3/test_visual_registry.py backend/tests/meta/v3/test_render_probe.py
git commit -m "feat: label a number line's markers so a steered lesson teaches magnitude"
```

---

### Task 4: Full suite and PR1

- [ ] **Step 1: Run everything**

```bash
cd backend && .venv/bin/pytest
```

Expected: PASS. If `.env` interference appears, note that the v3 merge fixed it; a real failure here is a real regression.

- [ ] **Step 2: Open PR1**

```bash
git push -u origin unit-tape-visual
gh pr create --title "Steer generation away from count-driven visuals for large magnitudes" --body "$(cat <<'EOF'
## Summary

Demo slide 4 (2.75 km to meters) dead-ended in `needs_manual_authoring`: the model proposed a `bar` with `maximum=10000`, the cardinality guard correctly refused 10000 segments, and the retry loop could not recover because the cap lived only in the failure's `expected` field, which is never sent to the model.

- The cardinality hint now names the cap, the field, and `number_line` as the alternative.
- Every count-driven field (`bar.maximum`, `grid.rows`/`columns`, `object_set.count`, `partition.parts`) describes what it draws and its cap in the tool schema the model reads; `number_line.maximum` says it is a scale.
- `number_line` labels each marker, so a lesson steered there teaches the magnitude instead of showing a bare line with dots.

Design: `docs/unit-tape-visual-design-2026-08-04.md`. The `unit_tape` visual from that design follows in a second PR.

## Test plan

- `backend/.venv/bin/pytest`
- New: cardinality-hint content, tool-schema descriptions, marker-label measurement and formatting, one number-line render through the probe.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

# Phase 2 — the tape (PR2)

Deliverable: a `unit_tape` lesson for 2.75 km → 2750 m that passes every gate and renders.

### Task 5: Declare the kind

**Files:**
- Modify: `backend/app/meta/dsl/teaching_plan.py`
- Modify: `backend/app/meta/dsl/scene_program.py:1-76`
- Modify: `backend/app/meta/v3/resolver.py:97-145`
- Test: `backend/tests/meta/v3/test_unit_tape.py` (create)

**Interfaces:**
- Produces: `UnitTapeVisual(kind, ref, value, per_unit, source_unit, target_unit)`; `UnitTapeProgramVisual(UnitTapeVisual)` with `initial_role: StyleRole = "structure"`; `evaluate_program_visual` returning values dict with keys `value`, `per_unit`, `source_unit`, `target_unit` (the first two as `Fraction`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/meta/v3/test_unit_tape.py`:

```python
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
```

Check how `LiteralNode` is constructed in `app/meta/dsl/expression.py` and match it — other tests in `tests/meta/v3/` build expression nodes already, so copy their form rather than guessing.

- [ ] **Step 2: Run to confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -v
```

Expected: FAIL with `ImportError: cannot import name 'UnitTapeProgramVisual'`.

- [ ] **Step 3: Add the plan schema class**

In `backend/app/meta/dsl/teaching_plan.py`, after `ObjectSetVisual`:

```python
class UnitTapeVisual(BaseModel):
    """A quantity in one unit, drawn as one box per whole unit, named in two units.

    The teaching visual for a conversion: each box carries the source unit's name
    and, revealed later by `unit_substitution`, the target unit's.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["unit_tape"] = "unit_tape"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value: ExpressionNode = Field(description=(
        "How many source units the quantity is, e.g. 2.75 for 2.75 kilometres. "
        "One box is drawn per whole unit plus one for any remainder, at most 8 "
        "boxes; for a larger magnitude use a number_line."
    ))
    per_unit: ExpressionNode = Field(description=(
        "How many target units make one source unit, e.g. 1000 for kilometres to "
        "metres. This is a label number, not a count -- nothing is drawn per "
        "target unit -- so it may be as large as the conversion requires."
    ))
    source_unit: ProseText = Field(min_length=1, max_length=20, description=(
        "The unit the quantity is given in, as it should read on screen: \"km\"."
    ))
    target_unit: ProseText = Field(min_length=1, max_length=20, description=(
        "The unit being converted to, as it should read on screen: \"m\"."
    ))
```

Add `UnitTapeVisual` to the `SemanticVisualSpec` union.

Extend `BarVisual.maximum`'s description (written in Task 2) so its final sentence reads:

```python
        "magnitude that large on a number_line, whose maximum is a scale, or on a "
        "unit_tape when the lesson converts between two units."
```

- [ ] **Step 4: Add the program schema class**

In `backend/app/meta/dsl/scene_program.py`, import `UnitTapeVisual` alongside the others and add:

```python
class UnitTapeProgramVisual(UnitTapeVisual):
    initial_role: StyleRole = "structure"
```

Add it to the `ProgramVisual` union.

- [ ] **Step 5: Add the resolver branch**

In `backend/app/meta/v3/resolver.py`, inside `evaluate_program_visual`, after the `object_set` branch:

```python
    if kind == "unit_tape":
        return _evaluated_spec(visual), {
            "value": _evaluate(visual.value, values),
            "per_unit": _evaluate(visual.per_unit, values),
            "source_unit": visual.source_unit,
            "target_unit": visual.target_unit,
        }
```

- [ ] **Step 6: Run the test**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/meta/dsl/teaching_plan.py backend/app/meta/dsl/scene_program.py backend/app/meta/v3/resolver.py backend/tests/meta/v3/test_unit_tape.py
git commit -m "feat: declare the unit_tape visual kind"
```

---

### Task 6: Measure the tape

**Files:**
- Modify: `backend/app/meta/v3/visual_registry.py`
- Test: `backend/tests/meta/v3/test_unit_tape.py`

**Interfaces:**
- Produces: parts `("box", i)`, `("source_label", i)`, `("target_label", i)` plus group parts `("source_label", None)` and `("target_label", None)`; payload `{"boxes": tuple[dict], "source_unit": str, "target_unit": str}` where each box dict has `source_label`, `target_label` and `fill_fraction`. Read by `renderer._build_unit_tape` in Task 11.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/meta/v3/test_unit_tape.py`:

```python
def _measure(value, per_unit=Fraction(1000)):
    from types import SimpleNamespace

    return default_visual_registry().measure(
        SimpleNamespace(kind="unit_tape", ref="trail_tape", initial_role="structure"),
        {"value": value, "per_unit": per_unit, "source_unit": "km", "target_unit": "m"},
        LabelMeasurer(),
    )


def test_a_tape_draws_one_box_per_whole_unit_plus_the_remainder():
    measured = _measure(Fraction(11, 4))

    boxes = measured.payload["boxes"]
    assert [box["source_label"] for box in boxes] == ["1 km", "1 km", "0.75 km"]
    assert [box["target_label"] for box in boxes] == ["1000 m", "1000 m", "750 m"]
    assert [box["fill_fraction"] for box in boxes] == [1.0, 1.0, 0.75]


def test_a_whole_valued_tape_has_no_partial_box():
    measured = _measure(Fraction(3))

    assert [box["fill_fraction"] for box in measured.payload["boxes"]] == [1.0, 1.0, 1.0]
    assert [box["source_label"] for box in measured.payload["boxes"]] == ["1 km"] * 3


def test_a_tape_exposes_a_group_part_per_label_class():
    """The compiler cannot enumerate box indices: the count comes from fixture
    params, which are unknown when the plan compiles. So one action has to be
    able to name every target label at once.
    """
    measured = _measure(Fraction(11, 4))

    group = measured.parts[("target_label", None)]
    per_box = [measured.parts[("target_label", index)] for index in range(3)]
    assert group.bounds.left == min(part.bounds.left for part in per_box)
    assert group.bounds.right == max(part.bounds.right for part in per_box)


def test_a_tape_puts_the_two_labels_in_different_halves_of_its_box():
    """Both labels are measured up front, so revealing the second cannot reflow."""
    measured = _measure(Fraction(2))

    box = measured.parts[("box", 0)].bounds
    source = measured.parts[("source_label", 0)].bounds
    target = measured.parts[("target_label", 0)].bounds
    assert source.bottom > target.top
    assert box.bottom <= target.bottom and source.top <= box.top


def test_a_tape_label_is_a_decimal_not_a_ratio():
    measured = _measure(Fraction(5, 2))

    assert measured.payload["boxes"][-1]["source_label"] == "0.5 km"
    assert measured.payload["boxes"][-1]["target_label"] == "500 m"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -v
```

Expected: FAIL with `ValueError: unknown semantic visual unit_tape`.

- [ ] **Step 3: Write the factory**

In `backend/app/meta/v3/visual_registry.py`, add the constants after `MAX_PART_CARDINALITY`:

```python
#: One box per whole unit stops being legible past this, and a ninth box would
#: not fit the 18.9-unit width limit with both labels inside it. `number_line`
#: covers larger magnitudes.
MAX_TAPE_BOXES = 8

_TAPE_BOX_HEIGHT = 1.1
_TAPE_BOX_GAP = 0.08
#: Breathing room either side of the widest label inside a box.
_TAPE_BOX_PADDING = 0.3
```

Add the factory near `_measure_bar`:

```python
def _measure_unit_tape(*, spec, values, measurer):
    """One box per whole source unit, each box measured for both of its labels.

    Both labels are measured even though only the source label is drawn at first:
    `unit_substitution` reveals the target label mid-lesson, and a box sized for
    the shorter text would have to grow when the longer one arrives -- reflowing
    the lesson under the learner. This is the reservation `_measure_answer` makes
    for the staged answer, applied per box.
    """
    value, per_unit = values["value"], values["per_unit"]
    source_unit, target_unit = values["source_unit"], values["target_unit"]
    if value <= 0 or per_unit <= 0:
        raise ValueError("unit_tape value and per_unit must be positive")
    full_boxes = int(value)
    remainder = value - full_boxes
    source_texts = [f"1 {source_unit}"] * full_boxes
    target_texts = [f"{format_number(per_unit)} {target_unit}"] * full_boxes
    if remainder:
        source_texts.append(f"{format_number(remainder)} {source_unit}")
        target_texts.append(f"{format_number(remainder * per_unit)} {target_unit}")
    box_width = _TAPE_BOX_PADDING + max(
        measurer.measure(text, "label")[0] for text in (*source_texts, *target_texts)
    )
    box_count = len(source_texts)
    width = box_count * box_width + (box_count - 1) * _TAPE_BOX_GAP
    left = -width / 2
    parts = {}
    for index in range(box_count):
        box_left = left + index * (box_width + _TAPE_BOX_GAP)
        box = Bounds(box_left, box_left + box_width, -_TAPE_BOX_HEIGHT / 2, _TAPE_BOX_HEIGHT / 2)
        parts[("box", index)] = SemanticPart("box", index, box)
        parts[("source_label", index)] = SemanticPart(
            "source_label", index, _tape_label_bounds(box, upper=True),
        )
        parts[("target_label", index)] = SemanticPart(
            "target_label", index, _tape_label_bounds(box, upper=False),
        )
    # A group part per label class, because the compiler stages the substitution
    # without knowing the box count -- `value` is a fixture param at compile time.
    for part_name in ("source_label", "target_label"):
        spans = [parts[(part_name, index)].bounds for index in range(box_count)]
        parts[(part_name, None)] = SemanticPart(part_name, None, Bounds(
            min(span.left for span in spans), max(span.right for span in spans),
            min(span.bottom for span in spans), max(span.top for span in spans),
        ))
    return _measured_visual(
        ref=spec.ref,
        bounds=Bounds(left, left + width, -_TAPE_BOX_HEIGHT / 2, _TAPE_BOX_HEIGHT / 2),
        parts=parts,
        payload={
            "boxes": tuple(
                {
                    "source_label": source_texts[index],
                    "target_label": target_texts[index],
                    "fill_fraction": 1.0 if index < full_boxes else float(remainder),
                }
                for index in range(box_count)
            ),
            "source_unit": source_unit,
            "target_unit": target_unit,
        },
    )


def _tape_label_bounds(box: Bounds, *, upper: bool) -> Bounds:
    """The upper or lower half of a box, where one of its two labels sits."""
    quarter = (box.top - box.bottom) / 4
    center_y = box.center.y + (quarter if upper else -quarter)
    return Bounds(box.left, box.right, center_y - quarter, center_y + quarter)
```

Register it in `default_visual_registry`, after `bar`:

```python
    registry.register("unit_tape", _measure_unit_tape)
```

Add the strategy support entry to `_SUPPORTED_STRATEGIES`:

```python
    "unit_tape": {"group_reveal", "unit_substitution"},
```

- [ ] **Step 4: Run the tests**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -v
```

Expected: PASS. `int(Fraction(11, 4))` is 2 (truncation, and the guard above rejects non-positive values, so truncation is a floor here).

- [ ] **Step 5: Commit**

```bash
git add backend/app/meta/v3/visual_registry.py backend/tests/meta/v3/test_unit_tape.py
git commit -m "feat: measure a unit_tape with both labels reserved per box"
```

---

### Task 7: Cap the box count

**Files:**
- Modify: `backend/app/meta/v3/visual_registry.py` (`_require_renderable_cardinality`)
- Test: `backend/tests/meta/v3/test_unit_tape.py`

**Interfaces:**
- Consumes: `_cardinality_failure` from Task 1.
- Produces: `_CARDINALITY_DERIVED: dict[str, tuple[str, int, Callable]]`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/meta/v3/test_unit_tape.py`:

```python
def test_a_tape_too_long_to_read_is_rejected_by_the_field_a_reviewer_can_change():
    """The count is derived, so the failure has to name `value`, not `9`.

    `_CARDINALITY_FIELDS` keys on field names present in the evaluated values,
    but a tape's box count is ceil(value) -- no field holds it. A failure naming
    the derived number would tell a reviewer to change something that is not in
    the plan.
    """
    with pytest.raises(V3ValidationError) as exc_info:
        _measure(Fraction(9))

    failure = exc_info.value.failure
    assert failure.code == "visual_extent_unrenderable"
    assert failure.path == "visuals.trail_tape"
    assert "value" in failure.hint
    assert "8" in failure.hint
    assert "number_line" in failure.hint


def test_a_tape_at_the_cap_still_measures():
    measured = _measure(Fraction(8))

    assert len(measured.payload["boxes"]) == 8


def test_the_tape_factory_never_runs_for_an_oversized_value():
    """The guard runs before the factory, as it does for `bar`."""
    from types import SimpleNamespace

    from app.meta.v3.visual_registry import VisualRegistry

    registry = VisualRegistry()

    def must_not_run(*, spec, values, measurer):
        raise AssertionError("the factory ran before the count was checked")

    registry.register("unit_tape", must_not_run)

    with pytest.raises(V3ValidationError):
        registry.measure(
            SimpleNamespace(kind="unit_tape", ref="huge"),
            {"value": Fraction(10**6), "per_unit": Fraction(1000),
             "source_unit": "km", "target_unit": "m"},
            LabelMeasurer(),
        )
```

- [ ] **Step 2: Run to confirm the first one fails**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -k cap -v
```

Expected: FAIL — nine boxes measure without complaint (and `test_the_tape_factory_never_runs_for_an_oversized_value` fails with the `AssertionError` from `must_not_run`).

- [ ] **Step 3: Add the derived cardinality check**

In `backend/app/meta/v3/visual_registry.py`, add after `_CARDINALITY_FIELDS`:

```python
#: Per KIND, the field a reviewer would change, its cap, and how the part count
#: is derived from that field's value. Separate from `_CARDINALITY_FIELDS`
#: because a tape's count is ceil(value): the number to name in the failure and
#: the number to compare against the cap are different numbers.
_CARDINALITY_DERIVED = {
    "unit_tape": ("value", MAX_TAPE_BOXES, lambda value: ceil(value)),
}
```

And extend the guard:

```python
def _require_renderable_cardinality(spec, values) -> None:
    for name in _CARDINALITY_FIELDS.get(spec.kind, ()):
        if name not in values:
            continue
        count = _whole(values[name], name) if _is_whole(values[name]) else None
        if count is not None and count <= MAX_PART_CARDINALITY:
            continue
        raise _cardinality_failure(
            spec, name, _describe(values[name]), MAX_PART_CARDINALITY, f"unit of {name}",
        )
    derived = _CARDINALITY_DERIVED.get(spec.kind)
    if derived is None:
        return
    name, cap, count_from = derived
    if name not in values:
        return
    if count_from(values[name]) > cap:
        raise _cardinality_failure(
            spec, name, _describe(values[name]), cap, "whole unit",
        )
```

`ceil` is already imported at the top of the module.

- [ ] **Step 4: Run the tests**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -v
```

Expected: PASS. The hint reads `unit_tape draws one part per whole unit, at most 8; reduce value (currently 9) or use a number_line, whose maximum is a scale rather than a part count`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/meta/v3/visual_registry.py backend/tests/meta/v3/test_unit_tape.py
git commit -m "feat: cap a unit_tape at eight boxes and name the field to change"
```

---

### Task 8: Compile a tape plan

**Files:**
- Modify: `backend/app/meta/v3/compiler.py:13-38`
- Modify: `backend/app/meta/dsl/teaching_plan.py` (strategy enum, plan-shape validator)
- Modify: `backend/app/meta/v3/beat_expander.py:23-32`
- Test: `backend/tests/meta/v3/test_unit_tape.py`

**Interfaces:**
- Consumes: `UnitTapeVisual`, `UnitTapeProgramVisual`.
- Produces: `compiler._literal_ceiling(expression) -> int | None`; `unit_substitution` in the strategy `Literal`; `TeachingPlanDocument.require_unit_substitution_shape`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/meta/v3/test_unit_tape.py`. Build the plan with a module-level helper so later tasks reuse it:

```python
def _tape_plan(strategy="unit_substitution", extra_beat_actions=None):
    """A four-beat conversion lesson: orient, name the rate, derive, conclude."""
    from app.meta.dsl.teaching_plan import TeachingPlanDocument

    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Convert a distance in kilometres to metres.",
        "primary_visual": {
            "kind": "unit_tape", "ref": "trail_tape",
            "value": {"node": "field_ref", "field": "distance_km"},
            "per_unit": {"node": "literal", "value": 1000},
            "source_unit": "km", "target_unit": "m",
        },
        "strategy": strategy,
        "answer_unit": "meters",
        "variation_seed": "trail_conversion",
        "beats": [
            {"id": "show_tape", "kind": "orient",
             "targets": [{"visual_ref": "trail_tape"}],
             "intent": "Show the trail as whole kilometres and part of one."},
            {"id": "name_rate", "kind": "focus",
             "targets": [{"visual_ref": "trail_tape", "part": "box", "index": 0}],
             "intent": "One kilometre is one thousand metres.",
             "custom_actions": extra_beat_actions or [
                 {"kind": "callout",
                  "target": {"visual_ref": "trail_tape", "part": "box", "index": 0, "anchor": "bottom"},
                  "text": "1 km = 1000 m"},
             ]},
            {"id": "rename_boxes", "kind": "derive",
             "targets": [{"visual_ref": "trail_tape"}],
             "intent": "Name every box in metres."},
            {"id": "state_total", "kind": "conclude",
             "targets": [{"visual_ref": "evaluated_answer"}],
             "intent": "Add the metres to get the total."},
        ],
    })


def _answer_expression():
    """distance_km x 1000, the metres the lesson concludes with."""
    from app.meta.dsl.expression import FieldRefNode, LiteralNode, MultiplyNode

    return MultiplyNode(operands=[
        FieldRefNode(field="distance_km"), LiteralNode(value=1000),
    ])


def _compile(plan):
    from app.meta.dsl.v3_common import CompileContext
    from app.meta.v3.compiler import compile_teaching_plan

    return compile_teaching_plan(
        plan,
        _answer_expression(),
        frozenset({"distance_km"}),
        CompileContext(concept_family="transform_other", grade_band="3-5"),
    )


def test_a_tape_plan_compiles_to_a_scene_program():
    program = _compile(_tape_plan())

    assert [visual.kind for visual in program.visuals] == ["unit_tape", "answer_expression"]


def test_unit_substitution_is_rejected_on_another_visual_kind():
    from app.meta.dsl.teaching_plan import TeachingPlanDocument

    payload = _tape_plan().model_dump()
    payload["primary_visual"] = {
        "kind": "bar", "ref": "trail_tape",
        "value": {"node": "literal", "value": 3},
        "maximum": {"node": "literal", "value": 5},
    }
    payload["beats"][1]["custom_actions"] = []
    payload["beats"][1]["targets"] = [
        {"visual_ref": "trail_tape", "part": "segment", "index": 0},
    ]

    with pytest.raises(V3ValidationError) as exc_info:
        _compile(TeachingPlanDocument.model_validate(payload))

    assert exc_info.value.failure.code == "incompatible_strategy"


def test_a_plan_may_not_stage_the_substitution_itself():
    """`unit_substitution` is a choreography the compiler owns.

    `compiler._validate_target` requires an index for any part target, so a plan
    could only reveal `target_label[0]` -- leaving the other boxes' labels
    invisible while an affordance check still saw a reveal. Only the compiler can
    name the group part, whose box count is unknown until fixture params arrive.
    Same division of labour as `require_pair_elimination_shape`.
    """
    from app.meta.dsl.teaching_plan import TeachingPlanDocument
    from pydantic import ValidationError

    payload = _tape_plan().model_dump()
    payload["beats"][1]["custom_actions"] = [
        {"kind": "reveal",
         "targets": [{"visual_ref": "trail_tape", "part": "target_label", "index": 0}]},
    ]

    with pytest.raises(ValidationError, match="target_label"):
        TeachingPlanDocument.model_validate(payload)
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -v
```

Expected: FAIL at plan validation — `unit_substitution` is not in the strategy `Literal`.

- [ ] **Step 3: Add the strategy and the plan-shape validator**

In `backend/app/meta/dsl/teaching_plan.py`, extend the `strategy` field:

```python
    strategy: Literal[
        "group_reveal", "short_stagger", "pair_elimination", "boundary_trace",
        "partition", "regroup", "magnitude_comparison", "unit_substitution",
    ]
```

And add a validator to `TeachingPlanDocument`:

```python
    @model_validator(mode="after")
    def require_unit_substitution_shape(self):
        """`unit_substitution` is staged by the compiler, not written by the plan.

        The compiler reveals every `target_label` at the derive beat using the
        visual's group part. A plan cannot express that: `_validate_target`
        requires an index for a part target, so a plan reveal could only name one
        box's label and would leave the rest unrevealed while still looking like
        an affordance. Same reasoning as `require_pair_elimination_shape`.
        """
        if self.strategy != "unit_substitution":
            return self
        for beat in self.beats:
            targets = [
                *beat.targets,
                *(
                    target
                    for action in beat.custom_actions
                    for target in (
                        *getattr(action, "targets", ()),
                        *(
                            getattr(action, attribute)
                            for attribute in ("target", "source")
                            if getattr(action, attribute, None) is not None
                        ),
                    )
                ),
            ]
            if any(target.part == "target_label" for target in targets):
                raise ValueError(
                    f"beat {beat.id!r} names target_label, which unit_substitution "
                    "stages on its own; remove the target or the custom action"
                )
        return self
```

- [ ] **Step 4: Wire the compiler maps**

In `backend/app/meta/v3/compiler.py`, add to `_EXPRESSION_FIELDS`:

```python
    "unit_tape": ("value", "per_unit"),
```

and to `_PART_CARDINALITY`:

```python
    "unit_tape": {
        "box": lambda spec: _literal_ceiling(spec.value),
        "source_label": lambda spec: _literal_ceiling(spec.value),
        "target_label": lambda spec: _literal_ceiling(spec.value),
    },
```

with the helper next to `_literal_integer`:

```python
def _literal_ceiling(expression):
    """The box count when the plan states it outright, else unknown.

    A tape's `value` is normally a field reference, so the count is only known
    once fixture params arrive -- `None` tells `_validate_target` to leave index
    bounds to the resolver, as it already does for a `bar` with a computed
    `maximum`.
    """
    if expression.node != "literal":
        return None
    return ceil(float(expression.value))
```

Add `from math import ceil` to the compiler's imports.

In `backend/app/meta/v3/beat_expander.py`, import `UnitTapeProgramVisual` and add to `_PROGRAM_VISUALS`:

```python
    "unit_tape": (UnitTapeProgramVisual, "structure"),
```

- [ ] **Step 5: Run the tests**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/meta/v3/compiler.py backend/app/meta/dsl/teaching_plan.py backend/app/meta/v3/beat_expander.py backend/tests/meta/v3/test_unit_tape.py
git commit -m "feat: compile a unit_substitution tape plan"
```

---

### Task 9: Stage the substitution

**Files:**
- Modify: `backend/app/meta/v3/visual_registry.py` (`DEFERRED_PARTS`)
- Modify: `backend/app/meta/v3/beat_expander.py:53-240`
- Test: `backend/tests/meta/v3/test_unit_tape.py`

**Interfaces:**
- Produces: `DEFERRED_PARTS: dict[str, tuple[str, ...]]` in `visual_registry`, consumed here and by `quality` in Task 10 and `renderer` in Task 11.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/meta/v3/test_unit_tape.py`:

```python
def _reveals(program):
    return [
        entry.action for entry in program.timeline if entry.action.kind == "reveal"
    ]


def test_the_compiler_reveals_every_target_label_at_the_derive_beat():
    program = _compile(_tape_plan())

    label_reveals = [
        action for action in _reveals(program)
        if any(target.part == "target_label" for target in action.targets)
    ]
    assert len(label_reveals) == 1
    target = label_reveals[0].targets[0]
    assert (target.visual_ref, target.part, target.index) == ("trail_tape", "target_label", None)
    assert label_reveals[0].mode == "stagger"


def test_the_label_reveal_is_not_suppressed_by_the_whole_visual_reveal():
    """`_reveal_unrevealed` treats a part as revealed once its visual is.

    That is right for every other kind -- the whole-visual reveal fades in a root
    group containing the parts -- and wrong for a deferred part, which the
    renderer deliberately leaves out of that group. Without the
    `DEFERRED_PARTS` exception the staged reveal is silently dropped and the
    metres never appear.
    """
    program = _compile(_tape_plan())

    order = [
        (target.part, target.index)
        for action in _reveals(program) for target in action.targets
        if target.visual_ref == "trail_tape"
    ]
    assert (None, None) in order
    assert ("target_label", None) in order
    assert order.index((None, None)) < order.index(("target_label", None))


def test_a_group_reveal_tape_gets_no_staged_substitution():
    program = _compile(_tape_plan(strategy="group_reveal"))

    assert not [
        action for action in _reveals(program)
        if any(target.part == "target_label" for target in action.targets)
    ]
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -k reveal -v
```

Expected: FAIL — no `target_label` reveal exists.

- [ ] **Step 3: Declare the deferred part**

In `backend/app/meta/v3/visual_registry.py`, next to `_CARDINALITY_FIELDS`:

```python
#: Per KIND, part classes that are NOT on screen when the whole visual is
#: revealed. The renderer keeps them out of the visual's root group, so they
#: arrive by their own reveal -- which means the "revealing a visual reveals its
#: parts" rule that `beat_expander._is_revealed` and `quality.check_repeated_reveal`
#: both apply has to make an exception for them.
DEFERRED_PARTS = {"unit_tape": ("target_label",)}
```

- [ ] **Step 4: Teach the expander about deferred parts and staging**

In `backend/app/meta/v3/beat_expander.py`:

Import the map:

```python
from app.meta.v3.visual_registry import DEFERRED_PARTS
```

In `expand`, before the beat loop, record the per-ref deferred classes and the staging beat:

```python
        self._deferred_parts = {
            spec.ref: DEFERRED_PARTS.get(spec.kind, ())
            for spec in self._visual_specs(plan)
        }
        unit_substitution_beat_id = self._unit_substitution_beat_id(plan)
```

Pass it into `_standard_actions` alongside `boundary_trace_beat_id`:

```python
            actions = self._standard_actions(
                plan, beat, relations, current_roles, revealed,
                boundary_trace_beat_id, unit_substitution_beat_id,
            )
```

Change `_is_revealed` from a `staticmethod` to an instance method with the exception:

```python
    def _is_revealed(self, target, revealed):
        # Revealing a whole visual reveals its parts with it -- except the parts
        # the visual declares deferred, which the renderer keeps out of the root
        # group precisely so they can arrive later.
        if (target.visual_ref, target.part, target.index) in revealed:
            return True
        if target.part in self._deferred_parts.get(target.visual_ref, ()):
            return False
        return (target.visual_ref, None, None) in revealed
```

Add the staging helper next to `_boundary_trace_beat_id`:

```python
    @staticmethod
    def _unit_substitution_beat_id(plan):
        """The beat where the target unit's labels arrive.

        `_boundary_trace_beat_id` takes the first beat of any of organize/derive/
        focus; a substitution belongs on the beat that derives, so `derive` is
        preferred here. `require_unit_substitution_shape` forbids the plan from
        staging this itself, so there is no author's version to defer to.
        """
        if plan.strategy != "unit_substitution":
            return None
        for kinds in ({"derive"}, {"organize"}, {"focus"}):
            for beat in plan.beats:
                if beat.kind in kinds:
                    return beat.id
        return None
```

Extend `_standard_actions`:

```python
    def _standard_actions(
        self, plan, beat, relations, current_roles, revealed,
        boundary_trace_beat_id, unit_substitution_beat_id=None,
    ):
        ...
        if plan.strategy == "boundary_trace" and beat.id == boundary_trace_beat_id:
            actions.append(TraceAction(path_ref=f"{plan.primary_visual.ref}.perimeter"))
        if beat.id == unit_substitution_beat_id:
            # Emitted directly rather than through `_reveal_unrevealed`: the group
            # part carries no index, which is the only way to name every box's
            # label when the box count depends on fixture params.
            actions.append(RevealAction(
                targets=[TargetRef(visual_ref=plan.primary_visual.ref, part="target_label")],
                mode="stagger",
            ))
        if not actions and not beat.custom_actions:
            actions.extend(self._attention_fallback(beat, current_roles))
        return actions
```

Keep the rest of the method body as it is.

- [ ] **Step 5: Run the expander tests**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -v
```

Expected: PASS.

- [ ] **Step 6: Run every compiler and expander suite**

```bash
cd backend && .venv/bin/pytest tests/meta/v3 -v
```

Expected: PASS. `_is_revealed` is now an instance method — if anything called it statically, fix the caller.

- [ ] **Step 7: Commit**

```bash
git add backend/app/meta/v3/visual_registry.py backend/app/meta/v3/beat_expander.py backend/tests/meta/v3/test_unit_tape.py
git commit -m "feat: stage the unit substitution at the derive beat"
```

---

### Task 10: Gate the affordance

**Files:**
- Modify: `backend/app/meta/v3/quality.py:223-232` and `:334-358`
- Test: `backend/tests/meta/v3/test_unit_tape.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/meta/v3/test_unit_tape.py`:

```python
def test_the_quality_gate_requires_the_substitution_reveal():
    from app.meta.v3.quality import check_strategy_affordance

    plan = _tape_plan()
    program = _compile(plan)
    stripped = program.model_copy(update={
        "timeline": [
            entry for entry in program.timeline
            if not (
                entry.action.kind == "reveal"
                and any(target.part == "target_label" for target in entry.action.targets)
            )
        ],
    })

    assert check_strategy_affordance(plan, program).passed
    assert not check_strategy_affordance(plan, stripped).passed


def test_revealing_a_deferred_part_after_its_visual_is_not_a_repeat():
    from app.meta.v3.quality import check_repeated_reveal

    assert check_repeated_reveal(_compile(_tape_plan())).passed


def test_revealing_a_deferred_part_twice_is_still_a_repeat():
    """The exception is for the FIRST reveal of a deferred part, not for every one."""
    from app.meta.v3.quality import check_repeated_reveal

    program = _compile(_tape_plan())
    label_entry = next(
        entry for entry in program.timeline
        if entry.action.kind == "reveal"
        and any(target.part == "target_label" for target in entry.action.targets)
    )
    doubled = program.model_copy(update={"timeline": [*program.timeline, label_entry]})

    assert not check_repeated_reveal(doubled).passed
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -k quality -v
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -k deferred -v
```

Expected: the affordance test fails (the stripped program still passes, since the check only knows `boundary_trace`), and `test_revealing_a_deferred_part_after_its_visual_is_not_a_repeat` fails with `repeated_reveal`.

- [ ] **Step 3: Extend both checks**

In `backend/app/meta/v3/quality.py`, import the map:

```python
from app.meta.v3.visual_registry import DEFERRED_PARTS
```

Replace `check_strategy_affordance`:

```python
def check_strategy_affordance(plan, program) -> QualityCheck:
    if plan.strategy == "unit_substitution":
        # The lesson's whole move is the exchange, so the target unit's labels
        # have to reach the screen. The compiler stages this reveal; the check
        # exists because a strategy whose affordance is optional is decorative.
        has_substitution = any(
            entry.action.kind == "reveal"
            and any(target.part == "target_label" for target in entry.action.targets)
            for entry in program.timeline
        )
        if not has_substitution:
            return _failed(
                "static_process_visual", "timeline",
                "unit-substitution instruction needs the target unit's labels revealed",
            )
        return _passed("static_process_visual", "timeline")
    if plan.strategy != "boundary_trace":
        return _passed("static_process_visual", "strategy")
    has_boundary_trace = any(
        entry.action.kind == "trace" and entry.action.path_ref.endswith(".perimeter")
        for entry in program.timeline
    )
    if not has_boundary_trace:
        return _failed("static_process_visual", "timeline", "boundary-trace instruction needs a visible perimeter trace")
    return _passed("static_process_visual", "timeline")
```

And in `check_repeated_reveal`, add the deferred exception:

```python
    revealed = set()
    revealed_wholes = set()
    deferred = {
        visual.ref: DEFERRED_PARTS.get(visual.kind, ()) for visual in program.visuals
    }
    for index, entry in enumerate(program.timeline):
        if entry.action.kind != "reveal":
            continue
        for target in entry.action.targets:
            key = (target.visual_ref, target.part, target.index)
            # A whole-visual reveal brings its children on screen with it, so a
            # later reveal of one of those parts is a repeat -- unless the visual
            # declares that part deferred, in which case the whole-visual reveal
            # never showed it and this is its first appearance.
            is_deferred = target.part in deferred.get(target.visual_ref, ())
            if key in revealed or (target.visual_ref in revealed_wholes and not is_deferred):
                return _failed(
                    "repeated_reveal", f"timeline[{index}].action.targets",
                    "a target may only be revealed once, and revealing a visual "
                    "reveals its parts with it",
                )
            revealed.add(key)
            if target.part is None:
                revealed_wholes.add(target.visual_ref)
    return _passed("repeated_reveal", "timeline")
```

- [ ] **Step 4: Run the quality suites**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py tests/meta/v3/test_quality.py -v
```

Expected: PASS. Watch for an import cycle: `quality` importing `visual_registry` is new. `compiler` already imports `_SUPPORTED_STRATEGIES` from it, so the direction is established; if a cycle appears, move `DEFERRED_PARTS` to `app/meta/v3/geometry.py` and import it from there in all three consumers.

- [ ] **Step 5: Commit**

```bash
git add backend/app/meta/v3/quality.py backend/tests/meta/v3/test_unit_tape.py
git commit -m "feat: gate the unit-substitution affordance and allow deferred reveals"
```

---

### Task 11: Render the tape

**Files:**
- Modify: `backend/app/meta/v3/renderer.py:131-223`
- Test: `backend/tests/meta/v3/test_render_probe.py`

**Interfaces:**
- Consumes: the Task 6 payload (`boxes`, each with `source_label`, `target_label`, `fill_fraction`).
- Produces: children keyed `("box", i)`, `("source_label", i)`, `("target_label", i)`, `("source_label", None)`, `("target_label", None)`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/meta/v3/test_render_probe.py`, reusing that module's existing probe-invocation shape:

```python
def test_a_unit_tape_lesson_renders_through_the_probe():
    """Compile and static gates pass on plans the renderer cannot draw.

    `vertex` targets and `object_set` both got through every static check and
    then raised inside `_build_visual` -- surfacing only as
    `render_probe_failed`. A real render is the only proof the payload keys and
    the renderer agree.
    """
    program = _compile(_tape_plan())

    manifest = run_probe_subprocess(ProbeRequest(
        program=program,
        known_fields={"distance_km": "decimal"},
        values={"distance_km": "2.75"},
    ))

    assert "trail_tape" in manifest["visual_bounds"]
```

Import `_compile` and `_tape_plan` from `tests.meta.v3.test_unit_tape`, or move both helpers into a shared `tests/meta/v3/conftest.py` fixture if that matches the repo's existing arrangement.

- [ ] **Step 2: Run to confirm it fails**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_render_probe.py -k unit_tape -v
```

Expected: FAIL — `_build_visual` raises `ValueError: unsupported resolved visual trail_tape`, surfacing as a non-zero probe exit.

- [ ] **Step 3: Add the renderer branch**

In `backend/app/meta/v3/renderer.py`, add a branch to `_build_visual` **before** the `{"value", "maximum"}` branch (payload keys are checked in order and `boxes` is unambiguous, but keeping tape ahead of bar documents that they are different things):

```python
    elif "boxes" in payload:
        root, children = _build_unit_tape(measured, placed, palette)
```

And add the builder after `_parts_as_rectangles`:

```python
def _build_unit_tape(measured, placed, palette: str):
    """Boxes and source labels on screen; target labels registered but held back.

    `visual_registry.DEFERRED_PARTS` declares `target_label` as arriving later, and
    the root group is what the whole-visual reveal fades in -- so a target label
    added to the root would be visible from the first beat, and the staged reveal
    would fade in something already on screen. They are still registered as
    children, which is what makes them addressable when their reveal plays.
    """
    payload = measured.payload
    children = {}
    root = VGroup()
    for index, box in enumerate(payload["boxes"]):
        box_bounds = _translated(measured.parts[("box", index)].bounds, placed.offset)
        outline = _rectangle_for_bounds(box_bounds)
        children[("box", index)] = outline
        root.add(outline)
        if box["fill_fraction"] < 1.0:
            root.add(_partial_fill(box_bounds, box["fill_fraction"], palette))
        for part in ("source_label", "target_label"):
            label_bounds = _translated(measured.parts[(part, index)].bounds, placed.offset)
            text = _text(box[part], "label", label_bounds.center, placed.scale)
            children[(part, index)] = text
            if part == "source_label":
                root.add(text)
    for part in ("source_label", "target_label"):
        children[(part, None)] = VGroup(*(
            children[(part, index)] for index in range(len(payload["boxes"]))
        ))
    return root, children


def _partial_fill(bounds: Bounds, fraction: float, palette: str):
    """The shaded portion of the remainder box, so 0.75 of a unit reads as 0.75."""
    width = (bounds.right - bounds.left) * fraction
    filled = Rectangle(width=max(width, 0.02), height=bounds.top - bounds.bottom)
    filled.move_to(_array(Point(bounds.left + width / 2, bounds.center.y)))
    style = resolve_semantic_style(palette, "focus")
    _apply_style(filled, style)
    filled.set_fill(style["color"], opacity=0.3)
    return filled
```

If `resolve_semantic_style` does not return a `"color"` key, read `app/meta/manim_primitives/style.py` and use whatever key it does return; do not guess.

- [ ] **Step 4: Run the probe test**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_render_probe.py -v
```

Expected: PASS. Two failures to expect and fix rather than work around:
- `KeyError` on a part key means measurement and renderer disagree about part names.
- The group `VGroup` appearing before its reveal means a target label was added to `root`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/meta/v3/renderer.py backend/tests/meta/v3/test_render_probe.py
git commit -m "feat: render a unit_tape with its target labels held back"
```

---

### Task 12: The demo lesson, end to end

**Files:**
- Test: `backend/tests/meta/v3/test_unit_tape.py`
- Modify: `docs/meta-template-demo.md` (slide 4 expectations)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/meta/v3/test_unit_tape.py`. This runs a **real** manim probe subprocess (`validate_candidate` calls `render_preview_and_probe`), so expect it to take tens of seconds — the same trade `tests/meta/test_demo_end_to_end.py` makes. Do not stub the probe here: the render is the point.

```python
def _observation():
    from datetime import datetime, timezone

    from app.meta import models

    return models.FallbackObservation(
        id="obs-trail",
        candidate_id="candidate-trail",
        source_excerpt="A hiking trail is 2.75 kilometers long. How many meters long is the trail?",
        grade_level=4,
        observation_kind="unsupported_shape",
        excluded=False,
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )


def _draft_proposal():
    from app.meta.draft_generation import DraftProposal, ProposedFixture
    from app.meta.dsl.expression import FieldRefNode
    from app.meta.dsl.guard import GuardDocument, PositivePredicate
    from app.meta.dsl.params import DecimalFieldSpec, ParamsDocument

    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[DecimalFieldSpec(
                name="distance_km", label="Distance in kilometres", description="",
                minimum=0.0, maximum=8.0,
            )],
        ),
        guard_document=GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=FieldRefNode(field="distance_km"))],
        ),
        answer_expression=_answer_expression(),
        teaching_plan_document=_tape_plan(),
        classifier_bullet="Use for converting a decimal quantity from one metric unit to a smaller one.",
        fixtures=[
            ProposedFixture(
                kind="positive", expected_outcome="accept",
                observation_id="obs-trail", params={"distance_km": 2.75},
            ),
            ProposedFixture(
                kind="negative", expected_outcome="reject", params={"distance_km": 0.0},
            ),
        ],
    )


def test_the_kilometre_conversion_lesson_passes_every_gate(tmp_path):
    """Demo slide 4, the lesson that dead-ended as needs_manual_authoring.

    Job 645f54b89af444fca04ea00a25d876cc, for the observation "A hiking trail is
    2.75 kilometers long. How many meters long is the trail?", exhausted its
    retries on `visual_extent_unrenderable` after proposing a bar with
    maximum=10000. This is the shape the generator should now be able to produce.
    """
    from app.meta.dsl.v3_common import CompileContext
    from app.meta.validation_pipeline import validate_candidate

    observation = _observation()

    candidate = validate_candidate(
        _draft_proposal(),
        observations_by_id={observation.id: observation},
        artifact_root=tmp_path,
        compile_context=CompileContext(concept_family="transform_other", grade_band="3-5"),
    )

    assert candidate.quality_report.passed
    assert candidate.scene_program.visuals[0].kind == "unit_tape"
```

Read `ValidatedCandidate` in `app/meta/validation_pipeline.py` and use its actual attribute names for those last two assertions — `quality_report` and `scene_program` are the expected names, but confirm before running rather than after.

- [ ] **Step 2: Run it**

```bash
cd backend && .venv/bin/pytest tests/meta/v3/test_unit_tape.py -k kilometre -v
```

Expected: FAIL first, then PASS once the proposal shape is right. Any `V3Failure` raised here is a real gap in Tasks 5-11 — read its `code` and `hint` and fix the source, not the test.

- [ ] **Step 3: Update the demo doc**

In `docs/meta-template-demo.md`, replace the "Optional slide 4" paragraph (around line 283) with an explicit expectation: a `unit_tape` lesson with `unit_substitution`, four beats (show the tape, name the rate, rename the boxes in metres, state the total), and answer `2750`.

- [ ] **Step 4: Full suite**

```bash
cd backend && .venv/bin/pytest
```

Expected: PASS.

- [ ] **Step 5: Commit and open PR2**

```bash
git add backend/tests/meta/v3/test_unit_tape.py docs/meta-template-demo.md
git commit -m "test: prove the kilometre conversion lesson passes every gate"
git push
gh pr create --title "Add a unit_tape visual and the unit_substitution strategy" --body "$(cat <<'EOF'
## Summary

Adds the teaching visual for conversion lessons: `unit_tape` draws one box per whole source unit, each box carrying the source unit's name, and the compiler-staged `unit_substitution` strategy reveals the target unit's labels at the derive beat so the exchange is performed rather than stated.

- `unit_tape` kind: plan schema, program schema, resolver evaluation, measurement, eight-box cap naming `value` as the field to change.
- `unit_substitution` strategy, staged by the compiler like `pair_elimination` and `boundary_trace`; a plan may not stage it itself.
- `DEFERRED_PARTS`: part classes not on screen when their visual is revealed, so `check_repeated_reveal` and `_is_revealed` stop treating the mid-lesson label reveal as a repeat.
- Renders through the probe, and the 2.75 km demo lesson passes every gate.

Design: `docs/unit-tape-visual-design-2026-08-04.md`. Follows the steering PR.

## Test plan

- `backend/.venv/bin/pytest`
- New `tests/meta/v3/test_unit_tape.py`: measurement and label formatting, the cap, compilation, staging, quality gates, end-to-end `validate_candidate`.
- New probe render in `tests/meta/v3/test_render_probe.py`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Verification checklist

Before claiming Phase 2 complete:

- [ ] `cd backend && .venv/bin/pytest` — full suite green, output pasted into the PR
- [ ] `tests/meta/v3/test_visual_registry.py::test_a_number_line_keeps_a_large_numeric_range` still passes (labels are payload, not parts)
- [ ] A `unit_tape` render exists in the probe suite, not only a compile test
- [ ] `docs/unit-tape-visual-design-2026-08-04.md` still describes what was built; if an implementation detail changed, update the design doc in the same PR
