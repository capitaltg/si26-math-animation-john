# Answer resolution in place

## Problem

The kilometers demo lesson ends by displaying its answer as a detached label at
the bottom of the frame, and shows an unresolved `? meters` placeholder that
nothing ever updates. Its `derive` beat performs no visible mathematics.

The stored draft (`template_drafts` row `f029b56c`) makes each fault concrete:

- `primary_visual`: a `bar` showing 2.75 against a maximum of 10
- `supporting_visuals`: a label `1 km = 1000 m`, and a label `? meters`
- the `derive_meters` beat targets the bar and the conversion label, so the
  compiler emits only a recolour to `focus` — no multiplication is shown
- the `conclude` beat targets `answer_label`, revealing the dead `? meters`
- separately, `beat_expander.expand` appends an `evaluated_answer` visual
  (`beat_expander.py:66`) which `layout.place_vertical_lesson` places in
  `CONCLUSION_BAND`, a reserved strip at y ∈ [-3.6, -2.4] (`layout.py:13`)

So the lesson shows two answer-like things: a placeholder that never resolves,
and a card that appears from nowhere in a strip detached from the visual it came
from. No mechanism in the DSL can rewrite a label's text, so the placeholder
could never have resolved.

## Goals

1. The final answer resolves **in place**, replacing the unknown it was posed
   as, rather than appearing as a separate label.
2. The answer is laid out as a member of the lesson's composition, not in a
   reserved bottom strip.
3. The answer is preceded by visible mathematical work, and that ordering is
   enforced by a quality gate rather than left to the model's discretion.
4. Future generated templates inherit all of the above without the model needing
   to author answer presentation at all.

## Non-goals

- New action kinds for arbitrary equation choreography, or a dedicated
  equation-row layout. The `answer_expression` already encodes the work, so
  printing it is sufficient; a richer equation DSL is not needed to meet the
  goals and is not specified here.
- Changing `pair_elimination`. That strategy declares no answer visual and
  identifies its answer through `SceneProgramDocument.answer_anchor`, which PR
  #74 introduced deliberately. It stays as it is.
- Retroactively restaging published templates. Their frozen
  `scene_program_json` replays unchanged; see Compatibility.

## Design

### The answer is a three-stage statement

One visual, three states, every one derived from the `answer_expression` already
present in the program:

| stage | beat | rendered text |
|---|---|---|
| `unknown` | first beat | `? meters` |
| `work` | last `derive` (else last `focus`) beat | `2.75 × 1000 = ? meters` |
| `value` | `conclude` | `2.75 × 1000 = 2750 meters` |

The `?` persists as the quantity being solved for and resolves in place at
conclude. The `work` stage gives the derive beat visible mathematics.

Width grows monotonically across the stages, so layout reserves the widest and
nothing reflows mid-scene.

**Suppression.** When `answer_expression` is a bare `field_ref` or `literal`
— no operation to show — the `work` stage is omitted and the visual has two
states. This follows the no-op suppression discipline already used by
`beat_expander._role_change` (`beat_expander.py:340`): an action that would
change nothing observable is not emitted.

### New action kind

```python
class ShowAnswerStageAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["show_answer_stage"] = "show_answer_stage"
    target: TargetRef
    stage: Literal["work", "value"]
```

Added to the `ProgramAction` union in `dsl/scene_program.py`.

The `unknown` stage needs no action of its own: it is what the visual is drawn
as, so the ordinary `reveal` in the first beat puts it on screen. Only the two
transitions away from it are actions.

It carries a `target` (the answer visual) rather than being target-free, so
every existing consumer keeps working without modification:
`resolver.action_targets`, `resolver._action_target_items`,
`quality._targets`, and `quality.check_unused_visual` all discover it through
the same path they use for `set_role`.

The renderer plays `Transform(current_stage, next_stage)`. Manim's `Transform`
mutates the source mobject, so the mobject
`dynamic_render_worker._answer_visible` looks up (`dynamic_render_worker.py:344`)
is the same one throughout and its final-frame persistence check is unaffected.

### Plan surface

`TeachingPlanDocument` gains exactly one field:

```python
answer_unit: ProseText = Field(default="", max_length=20)
```

`"meters"` for the kilometers lesson; empty when the result is unitless.
Optional with a default so the two stored plans deserialise unchanged.

Nothing else about answer presentation is authored by the model. Staging is
compiler-owned, mirroring how `pair_elimination` staging is compiler-owned
(`teaching_plan.require_pair_elimination_shape`).

### Compiler staging

`beat_expander` places all three stages:

- `unknown`: revealed in the first beat
- `work`: the last `derive` beat, or the last `focus` beat when the plan has no
  `derive` beat
- `value`, together with `set_role(conclusion)`: the `conclude` beat

`TeachingPlanDocument.require_focus_and_conclusion_order` already requires a
`focus` or `derive` beat before `conclude`, so a slot for `work` always exists.

`timeline.schedule_beats` already forces `slot_count = 1` for the conclusion
beat (`timeline.py:56`), so `show_answer_stage(value)` and
`set_role(conclusion)` co-start and the final state reads as one thing. No
scheduling change is required.

### Layout

`CONCLUSION_BAND` is deleted. `INSTRUCTIONAL_FRAME` becomes the whole
`SAFE_FRAME`, and `place_vertical_lesson` no longer partitions visuals by ref
name — the answer visual passes through `_arrange` like any other.

One arrangement rule is added: the answer visual is forced into `below` and
placed last, so it reads as the lesson's outcome. Without this,
`_balanced_pair` would width-sort a wide answer equation into `above` and put
the answer over the primary visual.

### Rendering and measurement

`resolver.evaluate_program_visual` currently collapses an `answer_expression`
visual into a plain label, discarding the expression tree
(`resolver.py:134-137`). It instead returns
`SimpleNamespace(kind="answer_expression", ...)` with a payload of
`{"stages": [...]}` — two entries when `work` is suppressed, three otherwise.

A new `_measure_answer` factory is registered on `visual_registry`. It measures
every stage and returns the union of their bounds, so layout reserves the widest.
`registry.measure` has exactly one call site (`resolver.py:78`) and always
passes `strategy=None`, so no `_SUPPORTED_STRATEGIES` entry is required.

`renderer._build_visual` gains a `"stages" in payload` branch, ordered ahead of
the existing `"text"` branch. It builds one `Text` per stage, centred on the
same point, and returns the first as root. The stage mobjects are held in a new
`RenderedScene.answer_stages` field rather than in `targets`, so a plan cannot
address an individual stage.

### Expression printing

New `expression_display(node, values) -> str`:

| node | output |
|---|---|
| `literal`, `field_ref` | terminating decimal (`2.75`), else `a/b` |
| `add` | `a + b` |
| `subtract` | `a - b` |
| `multiply` | `a × b` |
| `divide` | `a ÷ b` |
| `fraction` | `a/b` |

Parenthesisation is minimal and precedence-aware: parens appear only where
omitting them would make the string mean something the tree does not. The
expression tree is unambiguous; its flattening to one line is not.

Three precedence tiers:

| tier | nodes |
|---|---|
| atom | `literal`, `field_ref`, `fraction` — never parenthesised |
| tight | `multiply`, `divide` |
| loose | `add`, `subtract` |

An operand is parenthesised when either condition holds:

1. **Looser than its parent.** `multiply(add(2, 3), 4)` prints
   `(2 + 3) × 4`; without parens, `2 + 3 × 4` evaluates to 14 rather than 20.
   The converse needs nothing: `add(multiply(2, 3), 4)` prints `2 × 3 + 4`.
2. **The right operand of a non-associative parent at equal precedence.**
   `subtract` and `divide` do not associate, so
   `subtract(10, subtract(5, 2))` prints `10 - (5 - 2)`; without parens,
   `10 - 5 - 2` evaluates to 3 rather than 7. Precedence comparison alone does
   not catch this, because both nodes sit in the same tier.
   `MAX_EXPRESSION_DEPTH` is 6, so such nesting is legal and must be handled.

Number formatting is not the existing `resolver._format_value`, which renders a
`Fraction` and would print **`11/4`** for 2.75 (`resolver.py:294`). The new
formatter emits a decimal when the reduced denominator's only prime factors are
2 and 5, trimming trailing zeros, and falls back to `a/b` otherwise. Today's
answer, `2750`, hides this because its denominator is 1; the `work` stage
substitutes operand values and would expose it immediately.

`MAX_EXPRESSION_DEPTH` is 6 and `MAX_EXPRESSION_OPERATIONS` is 20
(`dsl/limits.py`), so no additional length bound is needed beyond the
`MIN_TEXT_SCALE` check layout already performs.

### Quality gates

**`check_conclusion_hold` must be scoped — the new staging breaks it.** It
collects every timeline entry naming `evaluated_answer` and takes
`min(duration_seconds)` across them against `MIN_CONCLUSION_HOLD_SECONDS`
(`quality.py:127-145`). Once the `unknown` stage is revealed in the first beat,
that reveal joins the set at roughly 0.75s and the check fails
`conclusion_hold_too_short` on a correct lesson. It is scoped to the final
acting beat's entries — which is what the check already means, and which is how
`timeline.schedule_beats` identifies its own conclusion (`timeline.py:44`).

**`check_answer_timing` inverts.** Today it rejects any reveal of
`evaluated_answer` outside `conclude` (`quality.py:116-123`). The new contract:

- `initial_role` remains `neutral` (unchanged)
- the `reveal` of `evaluated_answer` must be in the **first** beat
- `show_answer_stage` with `stage="value"` may appear only in the final
  `conclude` beat
- the reveal precedes any `work` stage, which precedes the `value` stage, and
  each `show_answer_stage` stage appears at most once

**New `check_answer_work_shown`.** When a program declares `evaluated_answer`
and its `answer_expression` contains at least one operation, the timeline must
contain a `work` stage. A separate check rather than a clause inside
`check_strategy_affordance`, so the failure reports its own code
(`answer_work_not_shown`) rather than borrowing `static_process_visual`, which
would name the wrong problem in the repair feedback the model reads.

**New `check_answer_stand_in`.** A `label` visual is rejected when its text
contains `?` anywhere other than as its final character. This is precisely the
kilometers fault — a model-authored `? meters` label competing with the
compiler's own answer — while leaving a legitimate question prompt
("What is the perimeter?") alone. The discriminator is objective: a stand-in
uses `?` as a value, so the mark sits mid-string; a question ends with it.

A failed check's `code`, `path` and `hint` are fed back to the model as repair
feedback (`draft_generation._reviewer_feedback_context`), so each new hint must
state what to do instead, not only what is wrong. `check_answer_stand_in`'s hint
says the system supplies the answer statement.

### Prompt

In `draft_generation._DRAFT_SYSTEM_PROMPT`, this sentence:

> All answer-related visuals start neutral, and the final evaluated answer is
> introduced only during conclude.

is replaced by:

> The system supplies the answer statement and stages it for you: it appears
> from the first beat as an unresolved "? unit", shows its arithmetic at the
> derive beat, and resolves to the value only at conclude. Name the unit of the
> result in answer_unit ("meters"; empty if unitless). Never author a label
> standing in for the answer, and never put "?" in a label.

## Compatibility

`ShowAnswerStageAction` and `answer_unit` are both additive, and `answer_unit`
has a default, so stored `scene_version: 3` programs and `plan_version: 3` plans
deserialise unchanged.

Two templates are published. The `median_of_seven` lesson declares no answer
visual and is unaffected. The `rectangle_perimeter` lesson's frozen program has
a single reveal at `conclude` and no `show_answer_stage` actions, so its staging
stays two-state — but because layout is recomputed per render, its answer moves
out of the deleted bottom strip into the lesson column on its next render. To
pick up the new staging it must be recompiled: reset the draft's status, run
`revalidate_draft`, then `approve_draft_service`, which republishes without a
Bedrock call.

## Verification

Written test-first.

- `expression_display`: every node kind; a looser child parenthesised
  (`(2 + 3) × 4`) and a tighter one left bare (`2 × 3 + 4`); the right operand
  of nested `subtract` and of nested `divide` parenthesised (`10 - (5 - 2)`);
  `2.75` rather than `11/4`; `1/3` falling back to `a/b`
- `beat_expander`: stage placement across first / last-derive-or-focus /
  conclude; `work` suppressed for a bare `field_ref` answer;
  `pair_elimination` still declares no answer visual
- `layout`: no reserved band; answer placed last in the column; the whole
  column centred as a unit
- each quality gate: one crafted program that fails it, one that passes
- `check_conclusion_hold` regression: the first-beat `unknown` reveal does not
  trip the 1.5s floor
- integration: recompile the stored kilometers plan with
  `answer_unit: "meters"` and assert three stages in the timeline, no label
  containing `?`, and a passing `validate_static_quality` report
- regression: the stored `median_of_seven` plan compiles unchanged

Success criterion: the kilometers lesson renders `? meters` →
`2.75 × 1000 = ? meters` → `2.75 × 1000 = 2750 meters`, laid out in the lesson
column, with `validate_static_quality` passing.
