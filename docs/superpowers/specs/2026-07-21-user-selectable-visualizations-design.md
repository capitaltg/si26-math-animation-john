# User-Selectable Visualizations — Design

**Date:** 2026-07-21
**Branch:** week2-pipeline-and-ui
**Status:** Approved for planning

## Problem

Today the pipeline auto-picks exactly one template per problem. A single-operation
problem like `6 + 3` is forced onto whatever the classifier deems "best" (currently
`balance_scale`), even though it could equally well be shown on a number line
(`6` →+3→ `9`) or as an array. Users have no say in the representation.

Two limitations cause this:

1. **Classification returns one template**, not a set of valid options.
2. **The `number_line` guard requires 2–3 steps** (`min_length=2`), so single-operation
   problems can never be offered as a number line at all.

## Goal

Let the user choose the visualization for each problem from a ranked set of
structurally-compatible options. Single-operation problems must be offerable as a
number line among other options.

## Flow

```
upload → candidates → [user selects problems] → /options (classify each)
       → [user picks a visualization per problem] → /render picks → clips
```

The `/options` step is separate from `/upload` so we only classify the problems the
user actually selected (avoids Bedrock calls for unused candidates).

## Backend changes

### 1. Classification returns ranked options (`app/pipeline/classification.py`)

`ClassificationResult` gains an `options` field replacing the single `template`:

```python
class TemplateOption(BaseModel):
    template: TemplateName
    rationale: str  # one short phrase, e.g. "single jump on a number line"

class ClassificationResult(BaseModel):
    options: list[TemplateOption] = Field(default_factory=list)  # ranked best-first
    grade_level: int = Field(ge=0, le=8)
    ambiguous: bool = False
```

- The prompt (already contract-aware from the prior fix) is extended: *"Return every
  template whose structural contract this problem satisfies, ranked best-first, each
  with a one-phrase rationale."*
- `text_card` is **always appended** as the last option if not already present — any
  problem can be shown as a text card, so the user always has a safe choice.
- `ambiguous=true` with an empty `options` list still means "no structural template
  fits"; the UI shows only the text-card fallback.

### 2. Relax the number_line guard (`app/templates/number_line/params.py`)

`steps` min length `2 → 1` (`Field(min_length=1, max_length=3)`). A single-jump number
line is valid. `0` steps and `>3` steps still rejected. The running-total, negative,
and span guards in `guard.py` are unchanged — they already work for one step.

`NumberLineScene.construct` already loops over `steps`, so a single step renders one
arrow with no code change.

### 3. Explicit template in `process_scene` (`app/pipeline/process_scene.py`)

`process_scene` gains optional `template` and `grade` params:

```python
def process_scene(candidate, output_dir, *, template=None, grade=None) -> Scene: ...
```

- When `template` is provided (user pick), **skip classification** and use it directly
  with the supplied `grade`.
- When `template` is `None`, behavior is unchanged (classify → first option / ambiguous).
- Extract-with-retry-once and the reroute-to-`text_card`-on-`ValidationError` safety net
  (`TEMPLATE_MISMATCH_REASON`) are preserved. If a user picks a template whose extraction
  still fails the guard, they get the honest text-card reroute rather than a technical
  failure.

### 4. Session caches options (`app/session.py`)

`Session` gains `options: dict[str, ClassificationResult]` (candidate_id → result),
populated by `/options`. This lets `/render`:
- **Validate** that a picked template was actually offered for that candidate (reject
  arbitrary/injected templates with 400).
- **Reuse the grade** from classification without re-calling Bedrock.

### 5. Routes (`app/routes.py`)

- **`POST /options`** — body `{candidate_ids: [...]}`. For each id, calls
  `classify_candidate`, caches the result on the session, and returns:
  ```json
  {"options": [{"candidate_id": "...",
                "grade_level": 1,
                "ambiguous": false,
                "templates": [{"template": "balance_scale", "rationale": "..."},
                              {"template": "number_line", "rationale": "..."}]}]}
  ```
- **`POST /render`** — body changes from `{candidate_ids}` to
  `{picks: [{candidate_id, template}]}`. For each pick: validate the candidate exists and
  the template was offered (else 400), then `process_scene(candidate, out,
  template=pick.template, grade=cached_grade)`. Response shape (`clips`) is unchanged.

## Frontend changes (`frontend/src/App.jsx`)

Three screens instead of two:

1. **Candidates** — checkboxes as today; button becomes **"Get options."** → `POST /options`.
2. **Options** (new) — per selected problem, a radio group of proposed visualizations,
   each labeled `template — rationale`; default selection = top-ranked. Button
   **"Render."** → `POST /render` with the picks.
3. **Results** — unchanged (download links + fallback reason).

State: add `options` (from `/options`) and `picks` (candidate_id → chosen template,
initialized to each problem's top option).

## Testing

- **classification:** ranked `options` returned; `text_card` always present as last
  option; single-operation problem yields both `balance_scale` and `number_line`;
  ambiguous → empty options.
- **number_line guard:** 1 step now passes; 0 and 4 still rejected (update the existing
  `test_step_count_outside_two_to_three_is_rejected`, rename to reflect 1–3); single-step
  running-total/span guards still fire.
- **process_scene:** honors explicit `template`+`grade` and skips classification;
  still reroutes to text_card on persistent `ValidationError`; `None` template path
  unchanged.
- **routes:** `/options` returns per-candidate ranked templates and caches them;
  `/render` rejects a template that was not offered (400); `/render` renders a valid pick;
  unknown candidate → 404.
- **regression:** existing suite stays green. Contracts that changed require test updates:
  (a) the number_line step-count test (1 now allowed); (b) `/render` request shape
  (`candidate_ids` → `picks`); (c) every `ClassificationResult(template=...)` construction
  — in `test_classification.py` and `test_process_scene.py` — migrates to the new
  `options=[...]` shape. `process_scene`'s `None`-template path selects `options[0]`.

## Out of scope (YAGNI)

- Eager rendering of all options for preview (chosen approach renders only the pick).
- Persisting picks across sessions.
- New template types.
