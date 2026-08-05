# `unit_tape`: a visual for magnitude and unit conversion

**Date:** 2026-08-04
**Status:** approved design, not yet implemented

## Problem

Demo slide 4 — *"A hiking trail is 2.75 kilometers long. How many meters long is
the trail?"* — cannot produce a template. Generation job
`645f54b89af444fca04ea00a25d876cc` is parked in `needs_manual_authoring` with:

```
visual_extent_unrenderable at visuals.m_bar:
  m_bar would draw 10000 parts (maximum=10000)
```

The model proposed a `bar` visual with `maximum` = 10000, reading `bar` as a
chart with an axis maximum. It is not: `visual_registry._measure_bar` builds one
rectangle per unit (`for index in range(maximum)`), so `maximum` = 10000 means
10000 mobjects across 6500 scene units. `_require_renderable_cardinality`
refused it correctly — `tests/meta/v3/test_visual_registry.py:92` pins exactly
this case.

Three separate defects turn that correct refusal into a dead end:

1. **The model is never told what the field means.** `BarVisual.maximum` is a
   bare `ExpressionNode` with no `description`. Field descriptions reach Bedrock
   through `DraftProposal.model_json_schema()`, so they are the only channel that
   can prevent the mistake; `bar` has none, and the system prompt never mentions
   the kind.
2. **The retry loop cannot learn the cap.** `generation_pipeline` sends only
   `code`, `path` and `hint` (`_STABLE_REPAIR_FEEDBACK_FIELDS`). The cap of 128
   appears only in `expected`, which is dropped. Both logged retries repeated
   `maximum=10000` unchanged.
3. **No repair exists.** 2750-out-of-10000 cannot be a ≤29-segment strip at any
   value of `maximum`, so "reduce the value driving this visual's size" asks for
   something impossible. The correct repair is a different visual kind, and the
   hint never says so.

Nothing in the system teaches unit conversion today. `number_line` is the
nearest kind and renders a bare line with dots and **no numbers at all**
(`renderer._line_visual`), so steering the model there without further work
trades a hard failure for a lesson that teaches nothing.

## Solution overview

1. A new visual kind, `unit_tape`: one box per whole source unit, each box
   nameable in a second unit.
2. A new strategy, `unit_substitution`, that reveals the second unit's labels
   mid-lesson so the exchange is performed rather than stated.
3. Steering so the model reaches for the right kind in the first place, and a
   repair hint that names the cap and the alternative.
4. Tick labels on `number_line`, so it is a genuine fallback for magnitudes
   past the tape's cap.

Delivered as two PRs. PR1 (items 3 and 4) unblocks the demo on its own; PR2
(items 1 and 2) adds the teaching visual.

### Rejected alternatives

- **Double number line** (km scale over m scale, aligned ticks). O(1) parts and
  the CCSS-standard conversion tool, but the box-per-unit decomposition was
  preferred: the partial box makes the decimal concrete.
- **Place-value shift** (digits sliding three columns left). Explains the metric
  trick procedurally but shows no magnitude, and grade 4 has not formalised
  ×1000 as a digit shift.
- **Labelling `number_line` and stopping there.** Kept as the fallback, not as
  the answer: the kilometres never appear, so the conversion goes untaught.
- **Fill-and-count-up storyboard** (empty tape filling box by box, running total
  climbing). A running total is text that changes value mid-lesson, which the
  system reserves exclusively for the staged answer; it also spends two beats
  counting and never shows why 1 km is 1000 m.
- **Model-authored `transform` actions** for the label swap. Contradicts the
  established division of labour — *"the strategy names a choreography, so the
  plan supplies the collection and the beat structure and the compiler supplies
  the staging"* (`teaching_plan.require_pair_elimination_shape`) — and a model
  that omits the swap omits it on every retry.
- **Generalising the staged-answer machinery** (`answer_stages`,
  `ShowAnswerStageAction`) so a label can morph km → m in place. The most
  faithful rendering of "swap", but it touches `scene_program`, `resolver`,
  `renderer` and the frozen-program replay path, and puts a second kind of
  value-changing text on screen.
- **Both labels visible from the start** under plain `group_reveal`. Cheapest,
  but the exchange is presented as given rather than performed.

## Design

### Schema

```python
class UnitTapeVisual(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["unit_tape"] = "unit_tape"
    ref: GeneratedText = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value: ExpressionNode        # 2.75 -- how many source units
    per_unit: ExpressionNode     # 1000 -- target units in one source unit
    source_unit: ProseText = Field(min_length=1, max_length=20)   # "km"
    target_unit: ProseText = Field(min_length=1, max_length=20)   # "m"
```

Both numbers are expressions because they come from fixture params. `per_unit`
is a label number, not a count — it never affects how much is drawn, so it is
unbounded. `value` drives the box count and is capped. This is the same
distinction the codebase already documents between `bar.maximum` (a count) and
`number_line.maximum` (a scale); here it is stated in the field descriptions,
not only in the validator.

Semantic parts: `box[i]`, `source_label[i]`, `target_label[i]`, plus one group
part per label class (`source_label` and `target_label` with no index) so a
single action can name every label at once. Group parts have precedent:
`rectangle_measurement` registers `length_edge`/`width_edge` as aliases over the
same `edge` lines.

### Measurement

`_measure_unit_tape` derives:

- `box_count = ceil(value)`
- full boxes `floor(value)`, remainder `value - floor(value)`
- full box labels: `"1 {source_unit}"` / `"{per_unit} {target_unit}"`
- partial box labels: `"{remainder} {source_unit}"` /
  `"{remainder × per_unit} {target_unit}"`

Numbers are formatted with `expression_display.format_number`, **not**
`resolver._format_value`: the latter renders any non-integer as
`numerator/denominator`, which would put "11/4 km" on screen instead of
"2.75 km".

**As implemented:** every box reserves the same width — the widest label across
every box, source and target alike — rather than the wider of each box's own
label pair as originally specced here. A uniform width was chosen instead:
boxes standing for equal units should look equal, and reserving per-box widths
would make the partial box (whose labels are usually shorter) visibly
narrower than the others. Revealing the target label later still cannot
reflow the lesson either way — the reservation `_measure_answer` already makes
for the staged answer.

Each label is also inset from its box's vertical midline by
`_TAPE_LABEL_INSET = 0.04` units (added during implementation, not in this
design), so the source and target label bands don't read as one block of text
before the target label is revealed.

### Cardinality cap

The cap is **8 boxes**. Beyond that the dual labels stop being legible, and the
`_require_renderable_extent` width limit (13.2 / `MIN_TEXT_SCALE` 0.7 = 18.9
units) is the backstop.

`_CARDINALITY_FIELDS` maps a kind to *field names present in `values`*, but the
tape's count is `ceil(value)`, not a field. `_require_renderable_cardinality`
gains a per-kind derived count alongside the field list. Its failure names the
field a reviewer can change (`value=40`), not the derived number, and its `hint`
carries both the cap and the alternative kind:

```
unit_tape draws one box per whole unit, at most 8. For larger magnitudes use
number_line (its maximum is a scale, not a part count).
```

The same edit fixes the `bar` message that opened this spec: the cap moves into
`hint`, which the retry loop actually sends.

### Deferred parts

The meter labels must arrive mid-lesson. `quality.check_repeated_reveal` fails
any part reveal following a whole-visual reveal, on the premise that *"revealing
a visual reveals its parts with it"*. For the tape that premise is false by
construction, so the exception is declared once:

```python
# visual_registry.py
DEFERRED_PARTS = {"unit_tape": ("target_label",)}
```

Three readers:

- `beat_expander._is_revealed` — a whole-visual reveal no longer implies a
  deferred part is revealed, so the staged reveal is not silently suppressed.
- `quality.check_repeated_reveal` — a deferred part revealed after its visual is
  legitimate. Genuine repeats still fail. Program visuals carry `kind`, so the
  check consults the map with no new plumbing.
- `renderer._build_visual` — deferred parts are registered as children but kept
  out of the root `VGroup`, which is what actually holds them off screen.

### Strategy `unit_substitution`

Added to the `strategy` enum and to
`_SUPPORTED_STRATEGIES["unit_tape"] = {"group_reveal", "unit_substitution"}`;
`compiler.validate_strategy_compatibility` rejects every other pairing.

The compiler chooses the staging beat the way `_boundary_trace_beat_id` does,
with one difference: that helper takes the first beat of any of
`organize`/`derive`/`focus`, whereas the substitution belongs on the beat that
does the deriving. So the order of preference is the first `derive` beat, else
the first `organize`, else the first `focus`. It then appends

```python
RevealAction(targets=[TargetRef(visual_ref=ref, part="target_label")], mode="stagger")
```

directly, bypassing `_reveal_unrevealed` the way the boundary trace bypasses it.
`check_strategy_affordance` gains a `unit_substitution` branch that fails when
that reveal is absent, so the target unit can never go unshown.

The plan may not stage this reveal itself, and a new
`TeachingPlanDocument.require_unit_substitution_shape` validator rejects any
`unit_substitution` plan that names `target_label` in a beat target or a custom
action. Two reasons, both structural rather than stylistic:

- `compiler._validate_target` rejects a plan target that names a part without an
  index (`missing_semantic_index`), so a plan can only ever reveal
  `target_label[0]`, `target_label[1]`, … individually. A plan that reveals one
  index leaves the other boxes' labels invisible while still satisfying an
  affordance check that merely looks for a reveal.
- Only the compiler-emitted action can use the group part
  (`target_label` with no index), because the box count depends on fixture params
  and is unknown when the plan is written.

This mirrors `require_pair_elimination_shape`: the strategy names a choreography,
and the compiler owns its staging exclusively.

### Storyboard

| Beat | Kind | What happens |
|---|---|---|
| 1 | `orient` | Tape appears: two full boxes labelled `1 km`, a partial box labelled `0.75 km`, filled to 75%. The staged answer shows `? meters`. |
| 2 | `focus` | A callout on the first box names the rate: `1 km = 1000 m`. |
| 3 | `derive` | Compiler-staged: `target_label` reveals left to right — `1000 m`, `1000 m`, `750 m`. |
| 4 | `conclude` | The staged answer resolves to `2750 meters`. |

### Renderer

A new `_build_visual` branch dispatching on payload key `boxes`, which collides
with no existing key set (`values`, `length/width/unit`, `text`, `markers`,
`rows/columns`, `whole/parts`, `value/maximum`, `count`, `stages`). The root
group holds box outlines, the partial box's fill, and the source labels; target
labels are children only.

The partial box is a `Rectangle` outline plus an inner fill rectangle at
`remainder × box_width`. `DashedVMobject` is not currently imported by
`renderer.py`; whether to add it or distinguish the partial box by fill alone is
a cosmetic call made during implementation.

`scene_program.py` gains `UnitTapeProgramVisual(UnitTapeVisual)` with
`initial_role`, and `beat_expander._PROGRAM_VISUALS` gains
`"unit_tape": (UnitTapeProgramVisual, "structure")`.

### Generation steering

The part that prevents recurrence, applied to every count-driven kind:

- `Field(description=...)` on `bar.maximum`, `grid.rows`, `grid.columns`,
  `object_set.count`, `partition.parts` and `unit_tape.value`, each stating that
  the field is a part count, giving its cap, and naming what to use instead for
  large magnitudes.
- One sentence in `_DRAFT_SYSTEM_PROMPT`: a magnitude beyond a couple of dozen
  units belongs on a `number_line` (whose `maximum` is a scale) or a `unit_tape`
  (for conversions), never on a `bar`.
- The repair `hint` carries the cap and the alternative kind, so a retry is a
  redirection rather than a blind shrink.
- `number_line` gains tick labels — `format_number` under each marker — so a
  lesson steered there teaches magnitude instead of showing a bare line.
  `_measure_number_line` reserves a label strip below the line and carries the
  strings in its payload; the renderer's `markers` branch draws them.

  Markers only, not the endpoints: `renderer._line_visual` draws the line from
  `bounds.left` to `bounds.right`, so widening the bounds to fit an endpoint
  label would stretch the line itself. Labelling markers alone keeps the
  horizontal bounds and the existing `len(parts) == 2` invariant
  (`test_a_number_line_keeps_a_large_numeric_range`) untouched — the labels are
  drawn from the payload rather than registered as parts, since nothing needs to
  address them. A plan wanting the ends labelled adds markers at `minimum` and
  `maximum`, which the `markers` field description will say.

## Testing

Test-first, per the project's TDD guidance.

| # | Area | Assertion |
|---|---|---|
| 1 | measurement | `value=2.75, per_unit=1000` → 3 boxes; labels `1 km`/`1000 m`, `1 km`/`1000 m`, `0.75 km`/`750 m`; partial fill at `0.75 × box_width` |
| 2 | measurement | non-integer values format as decimals (`0.75 km`), never `3/4 km` |
| 3a | cardinality | `bar` with `maximum=10000` rejected with the 128 cap and `number_line` both in the `hint`, not only in `expected` |
| 3b | cardinality | `unit_tape` with `value=9` rejected, failure names `value` and the 8-box cap, hint names `number_line` |
| 4 | compiler | `unit_substitution` accepted on `unit_tape`, rejected on every other kind; `group_reveal` accepted |
| 5 | beat expander | staged `target_label` reveal lands on the derive beat, and is suppressed when the plan reveals the labels itself |
| 6 | beat expander | a whole-visual reveal does not mark a deferred part revealed |
| 7 | quality | `check_strategy_affordance` fails without the reveal; `check_repeated_reveal` accepts the deferred reveal and still rejects a genuine repeat |
| 8 | render probe | a `unit_tape` scene renders end to end — the failure class that bit `vertex` and `object_set`, where compile and static gates pass and the renderer raises `KeyError` |
| 9 | end to end | the 2.75 km → 2750 lesson passes `validate_candidate` |

Plus: existing `number_line` tests keep passing with tick labels added.

Run with `backend/.venv/bin/pytest` from `backend/`.

## Sequencing

**PR1 — steering, hint, `number_line` labels.** Slide 4 stops dead-ending; the
model produces a valid, plainer number-line lesson. Tests 3a and
`number_line` label coverage.

**PR2 — `unit_tape` and `unit_substitution`.** The teaching visual. Tests 1, 2,
3b, 4, 5, 6, 7, 8 and 9.

## Out of scope

- Issue #66: `regroup` and `magnitude_comparison` are in the strategy enum but
  compile and render as an undifferentiated group reveal. This spec adds a
  strategy that is genuinely implemented; it does not fix those two.
- Raising `MAX_PART_CARDINALITY` (128) or changing `bar`'s semantics.
- Re-running the parked job. Once PR1 lands, the fingerprint needs a fresh job
  (per the demo doc's rehearsal-reset note) to exercise the new path.
