# User-Selectable Visualizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a teacher request ranked, structurally-compatible visualization choices for selected problems, choose one visualization per problem, and render only those validated choices.

**Architecture:** Change classification from one template to ranked `TemplateOption` values, normalize every non-rendering structural result to include a final `text_card` safety choice, and cache those results per session. Add `/options` between `/upload` and `/render`; `/render` accepts explicit picks, validates each pick against the cached offer, and calls `process_scene` without reclassifying. Extend the React state machine from upload → candidates → results to upload → candidates → options → results.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, pytest/httpx `TestClient`, boto3/Bedrock tool-use, React 18, Vite 5, Manim CE.

**Spec:** `docs/superpowers/specs/2026-07-21-user-selectable-visualizations-design.md`.

## Global Constraints

- Preserve the current uncommitted structural-contract prompt and `ValidationError` → `text_card` reroute work in `classification.py`, `process_scene.py`, and their tests; evolve those edits rather than discarding them.
- The LLM returns compatible representations and an inferred grade only; it must never compute arithmetic or provide an answer.
- `number_line` accepts 1–3 steps after this change. Its running-total, negative-value, and 20-unit-span guards remain enforced for a single step as well as multiple steps.
- `text_card` is the final API-visible option for every candidate. If Bedrock returns `ambiguous=true` with no structural options, normalize the public result to `ambiguous=true` plus only the `text_card` option.
- Ranked option order is significant: `process_scene(..., template=None)` uses `options[0]`, and the frontend initializes each radio group to `templates[0]`.
- `/options` classifies only candidate ids selected by the user and stores the exact normalized `ClassificationResult` in the active session.
- `/render` must reject any template name that was not present in the cached options with HTTP 400 (including unknown/injected names); it must return HTTP 404 for an unknown candidate id.
- An explicit user pick skips classification, but extraction still validates the chosen template and retries once. A persistent Pydantic `ValidationError` still renders the honest `text_card` mismatch fallback.
- State remains in memory only. Do not add a database, preview renders, new template types, or pick persistence across sessions.
- Keep the frontend dependency-free beyond its existing React/Vite packages; frontend verification is `npm run build` plus the manual three-screen smoke test.
- Run the focused test named in each task before committing. Run the complete backend suite and frontend production build before declaring the feature complete.

## File Structure

**Backend pipeline:**

- Modify `backend/app/pipeline/classification.py` — define ranked option models, update the structural prompt, validate Bedrock output, and append the final `text_card` option.
- Modify `backend/app/templates/number_line/params.py` — relax `steps` from 2–3 to 1–3.
- Modify `backend/app/pipeline/process_scene.py` — accept an explicit template/grade and otherwise select the first classified option.

**Backend session and API:**

- Modify `backend/app/session.py` — cache `ClassificationResult` by candidate id.
- Modify `backend/app/routes.py` — add `/options`, change `/render` to validated picks, and retain the existing clip response.

**Frontend and documentation:**

- Modify `frontend/src/App.jsx` — add options/picks state and the visualization-selection screen.
- Modify `frontend/vite.config.js` — proxy `/options` in development.
- Modify `README.md` — document the three-stage flow and revised API contracts.

**Tests:**

- Modify `backend/tests/pipeline/test_classification.py` — ranked result, fallback normalization, ambiguity, and prompt contract coverage.
- Modify `backend/tests/templates/test_number_line_guard.py` — 1–3 step contract and single-step guard coverage.
- Modify `backend/tests/pipeline/test_process_scene.py` — new classification shape and explicit-template behavior.
- Modify `backend/tests/test_session.py` — empty, per-session option caches.
- Modify `backend/tests/test_routes.py` — `/options`, cached-offer enforcement, and new `/render` body.

---

### Task 1: Return normalized ranked visualization options

**Files:**

- Modify: `backend/app/pipeline/classification.py`
- Modify: `backend/tests/pipeline/test_classification.py`

**Interfaces:**

- Produces: `TemplateOption(template: TemplateName, rationale: str)`.
- Produces: `ClassificationResult(options: list[TemplateOption], grade_level: int, ambiguous: bool)`.
- Produces: `classify_candidate(source_text: str) -> ClassificationResult`, whose return always ends in `TemplateName.TEXT_CARD`; when `ambiguous` is true, it returns only that fallback option.
- Consumed by: `process_scene` in Task 3, `Session.options` in Task 4, and `/options` in Task 5.

- [ ] **Step 1: Replace the classification tests with the ranked-options contract**

Replace `backend/tests/pipeline/test_classification.py` with:

```python
from unittest.mock import patch

import pytest
from pydantic import ValidationError


@patch("app.pipeline.classification.call_with_tool")
def test_classify_preserves_ranked_options_and_appends_text_card(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [
            {"template": "balance_scale", "rationale": "shows the equation as a balance"},
            {"template": "number_line", "rationale": "shows one forward jump"},
        ],
        "grade_level": 1,
        "ambiguous": False,
    }

    result = classify_candidate("6 + 3 = ?")

    assert [option.template for option in result.options] == [
        TemplateName.BALANCE_SCALE,
        TemplateName.NUMBER_LINE,
        TemplateName.TEXT_CARD,
    ]
    assert result.options[1].rationale == "shows one forward jump"
    assert result.options[-1].rationale == "always-compatible fallback"
    assert result.grade_level == 1
    assert result.ambiguous is False


@patch("app.pipeline.classification.call_with_tool")
def test_classify_does_not_duplicate_an_existing_text_card(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [
            {"template": "text_card", "rationale": "shows the original wording"},
            {"template": "number_line", "rationale": "shows one forward jump"},
        ],
        "grade_level": 1,
        "ambiguous": False,
    }

    result = classify_candidate("6 + 3 = ?")

    assert [option.template for option in result.options] == [
        TemplateName.NUMBER_LINE,
        TemplateName.TEXT_CARD,
    ]
    assert result.options[-1].rationale == "shows the original wording"


@patch("app.pipeline.classification.call_with_tool")
def test_ambiguous_result_exposes_only_text_card_fallback(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [],
        "grade_level": 3,
        "ambiguous": True,
    }

    result = classify_candidate("There are some red and some green apples.")

    assert result.ambiguous is True
    assert [option.template for option in result.options] == [TemplateName.TEXT_CARD]


def test_model_accepts_ambiguous_empty_structural_options_payload():
    from app.pipeline.classification import ClassificationResult

    result = ClassificationResult(options=[], grade_level=3, ambiguous=True)

    assert result.options == []
    assert result.ambiguous is True


@patch("app.pipeline.classification.call_with_tool")
def test_classify_rejects_an_unknown_template(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [{"template": "hologram", "rationale": "looks impressive"}],
        "grade_level": 2,
        "ambiguous": False,
    }

    with pytest.raises(ValidationError):
        classify_candidate("anything")


@patch("app.pipeline.classification.call_with_tool")
def test_classification_prompt_requests_every_compatible_template_ranked(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {
        "options": [
            {"template": "balance_scale", "rationale": "shows the equation"},
            {"template": "number_line", "rationale": "shows one jump"},
        ],
        "grade_level": 1,
        "ambiguous": False,
    }

    classify_candidate("6 + 3 = ?")

    system_prompt = mock_call.call_args.kwargs["system_prompt"]
    for template in (
        "number_line",
        "array_grid",
        "balance_scale",
        "fraction_bar",
        "text_card",
    ):
        assert template in system_prompt
    assert "every template" in system_prompt.lower()
    assert "ranked best-first" in system_prompt.lower()
    assert "one-phrase rationale" in system_prompt.lower()
    assert "1 to 3" in system_prompt
    assert "single operation" in system_prompt.lower()
```

- [ ] **Step 2: Run the focused test and confirm the old single-template contract fails**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/pipeline/test_classification.py -v
```

Expected: FAIL because `ClassificationResult` still expects `template`, has no `options`, and the prompt still describes one category with a 2–3 step number line.

- [ ] **Step 3: Implement ranked models, prompt instructions, and fallback normalization**

In `backend/app/pipeline/classification.py`:

1. Replace the stale structural-contract comment and update the number-line contract:

```python
# Each template is a structural contract, not a free-form illustration. The classifier
# must return only options whose parameter guards can accept the problem downstream.
_TEMPLATE_CONTRACTS = (
    "- number_line: a journey of 1 to 3 sequential add/subtract jumps from a start value "
    "(e.g. 6 + 3 or 4 + 3 - 1). A single operation is one valid jump.\n"
    "- balance_scale: a single equation with exactly two addends on one side equalling a "
    "total (e.g. 6 + 3 = ?, 10 + 2 = 12). Useful for single-operation sums.\n"
    "- array_grid: equal groups / repeated addition / multiplication shown as rows x columns.\n"
    "- fraction_bar: 2 to 3 sequential add/subtract steps on fractions sharing one denominator.\n"
    "- text_card: worksheets, lists of many problems, or any problem that does not fit the "
    "structural templates above. Use this rather than forcing an ill-fitting template."
)
```

2. Replace `_CLASSIFICATION_SYSTEM_PROMPT` with:

```python
_CLASSIFICATION_SYSTEM_PROMPT = (
    "You classify a single K-8 math example problem into compatible visual template "
    "categories and infer its grade level. Each template accepts only problems that "
    "match its structural contract:\n"
    f"{_TEMPLATE_CONTRACTS}\n"
    "Return every template whose structural contract this problem satisfies, ranked "
    "best-first, each with a one-phrase rationale. Never include a template the problem "
    "cannot structurally satisfy. Do not compute or state any answer. Set ambiguous=true "
    "when the operands or operation cannot be confidently determined, or when no "
    "structural template fits the problem; in that case return an empty options list."
)
```

3. Replace `ClassificationResult` and `classify_candidate` with:

```python
class TemplateOption(BaseModel):
    template: TemplateName
    rationale: str = Field(min_length=1)


class ClassificationResult(BaseModel):
    options: list[TemplateOption] = Field(default_factory=list)
    grade_level: int = Field(ge=0, le=8)
    ambiguous: bool = False


_TEXT_CARD_OPTION = TemplateOption(
    template=TemplateName.TEXT_CARD,
    rationale="always-compatible fallback",
)


def classify_candidate(source_text: str) -> ClassificationResult:
    schema = ClassificationResult.model_json_schema()
    result = call_with_tool(
        system_prompt=_CLASSIFICATION_SYSTEM_PROMPT,
        user_message=source_text,
        tool_name="classify_problem",
        tool_schema=schema,
    )
    classification = ClassificationResult.model_validate(result)
    text_card = next(
        (
            option
            for option in classification.options
            if option.template == TemplateName.TEXT_CARD
        ),
        _TEXT_CARD_OPTION,
    )
    structural_options = [] if classification.ambiguous else [
        option
        for option in classification.options
        if option.template != TemplateName.TEXT_CARD
    ]
    return classification.model_copy(
        update={"options": [*structural_options, text_card]},
    )
```

This treats Bedrock's empty list as the “no structural fit” signal while ensuring callers and the UI receive a renderable fallback choice.

- [ ] **Step 4: Run the focused test and verify all ranked-option cases pass**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/pipeline/test_classification.py -v
```

Expected: PASS (6 tests).

- [ ] **Step 5: Commit the ranked classification contract**

```bash
git add backend/app/pipeline/classification.py backend/tests/pipeline/test_classification.py
git commit -m "feat: return ranked visualization options"
```

---

### Task 2: Permit and guard single-jump number lines

**Files:**

- Modify: `backend/app/templates/number_line/params.py:13-15`
- Modify: `backend/tests/templates/test_number_line_guard.py:71-98`

**Interfaces:**

- Produces: `NumberLineParams.steps` constrained to `min_length=1, max_length=3` in both Pydantic validation and the Bedrock JSON schema.
- Preserves: `check_number_line_compatibility(params) -> None`, including nonnegative running totals and a maximum span of 20.
- Consumed by: number-line extraction/rendering and the explicit-pick mismatch test in Task 3.

- [ ] **Step 1: Add single-step acceptance and single-step guard regression tests**

In `backend/tests/templates/test_number_line_guard.py`, replace the step-count parametrized test and schema assertion with:

```python
def test_single_step_is_allowed():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    params = NumberLineParams(
        start=6,
        steps=[NumberLineStep(operation="add", amount=3)],
    )

    assert len(params.steps) == 1


@pytest.mark.parametrize("step_count", [0, 4])
def test_step_count_outside_one_to_three_is_rejected(step_count):
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    steps = [NumberLineStep(operation="add", amount=1) for _ in range(step_count)]
    with pytest.raises(ValidationError):
        NumberLineParams(start=2, steps=steps)


def test_single_step_running_total_going_negative_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=2,
            steps=[NumberLineStep(operation="subtract", amount=3)],
        )


def test_single_step_span_over_twenty_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=0,
            steps=[NumberLineStep(operation="add", amount=21)],
        )
```

Keep `test_non_positive_step_amount_is_rejected`, then update `test_schema_exposes_step_constraints_to_bedrock` to assert:

```python
    assert schema["properties"]["steps"]["minItems"] == 1
    assert schema["properties"]["steps"]["maxItems"] == 3
```

- [ ] **Step 2: Run the guard tests and confirm a single step is rejected by the current model**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/templates/test_number_line_guard.py -v
```

Expected: FAIL in `test_single_step_is_allowed` and the `minItems == 1` assertion.

- [ ] **Step 3: Relax only the Pydantic list-length constraint**

In `backend/app/templates/number_line/params.py`, change `NumberLineParams.steps` to:

```python
class NumberLineParams(BaseModel):
    start: int
    steps: list[NumberLineStep] = Field(min_length=1, max_length=3)
```

Do not change `backend/app/templates/number_line/guard.py` or `scene.py`; both already iterate safely over one step.

- [ ] **Step 4: Run the focused guard tests**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/templates/test_number_line_guard.py -v
```

Expected: PASS, including the existing multi-step cases and the new one-step validation cases.

- [ ] **Step 5: Commit the number-line contract change**

```bash
git add backend/app/templates/number_line/params.py backend/tests/templates/test_number_line_guard.py
git commit -m "feat: allow single-jump number lines"
```

---

### Task 3: Honor explicit template picks without reclassification

**Files:**

- Modify: `backend/app/pipeline/process_scene.py`
- Modify: `backend/tests/pipeline/test_process_scene.py`

**Interfaces:**

- Produces: `process_scene(candidate: Candidate, output_dir: Path, *, template: TemplateName | None = None, grade: int | None = None) -> Scene`.
- When `template` is provided: skips `classify_candidate`, uses the provided grade (or `DEFAULT_FALLBACK_GRADE` only for a direct caller that omits grade), and keeps extraction/retry/reroute behavior.
- When `template` is `None`: calls classification and uses `classification.options[0]`; ambiguity still produces `CLASSIFICATION_AMBIGUOUS_REASON`.
- Consumed by: `/render` in Task 5.

- [ ] **Step 1: Migrate every classification fixture in `test_process_scene.py` to options**

Change non-ambiguous constructions from:

```python
ClassificationResult(
    template=TemplateName.NUMBER_LINE,
    grade_level=2,
    ambiguous=False,
)
```

to:

```python
ClassificationResult(
    options=[
        TemplateOption(
            template=TemplateName.NUMBER_LINE,
            rationale="shows the operations as jumps",
        )
    ],
    grade_level=2,
    ambiguous=False,
)
```

Import `TemplateOption` beside `ClassificationResult` in each affected test. Change ambiguous constructions to:

```python
ClassificationResult(options=[], grade_level=3, ambiguous=True)
```

- [ ] **Step 2: Add a failing explicit-pick test**

Add to `backend/tests/pipeline/test_process_scene.py`:

```python
@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_explicit_template_and_grade_skip_classification(
    mock_classify,
    mock_extract,
    mock_render,
    tmp_path,
):
    from app.pipeline.process_scene import process_scene

    mock_extract.return_value = _number_line_params()
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(
        _candidate(),
        tmp_path,
        template=TemplateName.NUMBER_LINE,
        grade=4,
    )

    assert scene.status == "approved"
    assert scene.template == TemplateName.NUMBER_LINE
    assert scene.grade_level == 4
    mock_classify.assert_not_called()
```

- [ ] **Step 3: Update the persistent-contract-mismatch setup now that one step is valid**

In `test_persistent_contract_mismatch_reroutes_to_text_card`, create a real single-step guard error with a negative running total:

```python
    try:
        NumberLineParams(
            start=1,
            steps=[NumberLineStep(operation="subtract", amount=2)],
        )
        raise AssertionError("expected a ValidationError for a negative running total")
    except ValidationError as exc:
        contract_error = exc
```

Call the explicit path so the test also proves a user-selected template retains the mismatch safety net:

```python
    scene = process_scene(
        _candidate(),
        tmp_path,
        template=TemplateName.NUMBER_LINE,
        grade=1,
    )
```

Keep the assertions that extraction runs twice, the resulting scene is a rendered `text_card` fallback, and the reason is `TEMPLATE_MISMATCH_REASON` rather than `TECHNICAL_FAILURE_REASON`. Add `mock_classify.assert_not_called()`.

- [ ] **Step 4: Run the process-scene tests and confirm the signature/old result shape fail**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/pipeline/test_process_scene.py -v
```

Expected: FAIL because `process_scene` does not accept `template`/`grade` and still reads `classification.template`.

- [ ] **Step 5: Replace `process_scene` with explicit-or-classified choice resolution**

Replace the complete `process_scene` function in `backend/app/pipeline/process_scene.py` with:

```python
def process_scene(
    candidate: Candidate,
    output_dir: Path,
    *,
    template: TemplateName | None = None,
    grade: int | None = None,
) -> Scene:
    if template is None:
        try:
            classification = classify_candidate(candidate.source_excerpt)
        except Exception:
            logger.exception("Classification failed for candidate %s", candidate.candidate_id)
            return _fallback_scene(
                candidate,
                DEFAULT_FALLBACK_GRADE,
                TECHNICAL_FAILURE_REASON,
                output_dir,
            )

        resolved_grade = classification.grade_level
        if classification.ambiguous or not classification.options:
            return _fallback_scene(
                candidate,
                resolved_grade,
                CLASSIFICATION_AMBIGUOUS_REASON,
                output_dir,
            )
        resolved_template = classification.options[0].template
    else:
        resolved_template = template
        resolved_grade = grade if grade is not None else DEFAULT_FALLBACK_GRADE

    _, params_cls = get_template(resolved_template)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            params = extract_params(candidate.source_excerpt, params_cls)
            output_path = output_dir / f"{candidate.candidate_id}.mp4"
            render_scene_to_mp4(resolved_template, params, output_path)
            return Scene(
                scene_id=str(uuid4()),
                candidate_id=candidate.candidate_id,
                template=resolved_template,
                grade_level=resolved_grade,
                params=params.model_dump(mode="json"),
                status="approved",
                render_path=output_path,
            )
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(BACKOFF_SECONDS)

    # A ValidationError means extraction could not satisfy the chosen template's
    # structural contract. Preserve the user's content as an honest text-card fallback.
    if isinstance(last_error, ValidationError):
        logger.info(
            "Candidate %s did not fit template %s; re-routing to text card",
            candidate.candidate_id,
            resolved_template,
        )
        return _fallback_scene(
            candidate,
            resolved_grade,
            TEMPLATE_MISMATCH_REASON,
            output_dir,
        )

    logger.exception(
        "Extraction/render failed after retries for candidate %s",
        candidate.candidate_id,
        exc_info=last_error,
    )
    return _fallback_scene(
        candidate,
        resolved_grade,
        TECHNICAL_FAILURE_REASON,
        output_dir,
    )
```

- [ ] **Step 6: Run the focused process-scene tests**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/pipeline/test_process_scene.py -v
```

Expected: PASS; the auto path selects its first option, the explicit path never classifies, and both paths retain retry/fallback behavior.

- [ ] **Step 7: Commit explicit-pick orchestration**

```bash
git add backend/app/pipeline/process_scene.py backend/tests/pipeline/test_process_scene.py
git commit -m "feat: render explicit visualization picks"
```

---

### Task 4: Cache normalized options in each session

**Files:**

- Modify: `backend/app/session.py`
- Modify: `backend/tests/test_session.py`

**Interfaces:**

- Produces: `Session.options: dict[str, ClassificationResult]`, keyed by candidate id.
- New sessions receive independent empty dictionaries.
- Consumed by: `/options` writes and `/render` reads in Task 5.

- [ ] **Step 1: Add a failing session-cache isolation test**

Append to `backend/tests/test_session.py`:

```python
def test_new_sessions_have_independent_empty_option_caches(tmp_path):
    from app.models.scene import TemplateName
    from app.pipeline.classification import ClassificationResult, TemplateOption
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    first = store.create([_candidate("a")])
    second = store.create([_candidate("b")])

    assert first.options == {}
    assert second.options == {}

    first.options["a"] = ClassificationResult(
        options=[
            TemplateOption(
                template=TemplateName.NUMBER_LINE,
                rationale="shows one jump",
            )
        ],
        grade_level=1,
    )

    assert "a" in first.options
    assert second.options == {}
```

- [ ] **Step 2: Run the focused session tests and confirm `Session.options` is absent**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_session.py -v
```

Expected: FAIL with `AttributeError: 'Session' object has no attribute 'options'`.

- [ ] **Step 3: Add the per-session default dictionary**

In `backend/app/session.py`, update imports:

```python
from dataclasses import dataclass, field

from app.models.candidate import Candidate
from app.pipeline.classification import ClassificationResult
```

Update `Session`:

```python
@dataclass
class Session:
    session_id: str
    candidates: dict[str, Candidate]
    output_dir: Path
    options: dict[str, ClassificationResult] = field(default_factory=dict)
```

`SessionStore.create` needs no explicit `options={}` argument because `default_factory` creates an isolated cache for every session.

- [ ] **Step 4: Run the focused session tests**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_session.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit session option caching**

```bash
git add backend/app/session.py backend/tests/test_session.py
git commit -m "feat: cache visualization options per session"
```

---

### Task 5: Add `/options` and validate `/render` picks

**Files:**

- Modify: `backend/app/routes.py`
- Modify: `backend/tests/test_routes.py`

**Interfaces:**

- Produces: `POST /options` request `{ "candidate_ids": [str, ...] }` and response `{ "options": [{ "candidate_id", "grade_level", "ambiguous", "templates": [{ "template", "rationale" }] }] }`.
- Produces: `POST /render` request `{ "picks": [{ "candidate_id", "template" }] }`; response remains `{ "clips": [...] }`.
- Enforces: unknown candidates → 404; missing session → 400; missing cached options, unknown template names, or unoffered template names → 400.
- Calls: `process_scene(candidate, output_dir, template=pick.template, grade=cached.grade_level)`.

- [ ] **Step 1: Add reusable route-test fixtures for offered options**

In `backend/tests/test_routes.py`, add:

```python
def _classification():
    from app.models.scene import TemplateName
    from app.pipeline.classification import ClassificationResult, TemplateOption

    return ClassificationResult(
        options=[
            TemplateOption(
                template=TemplateName.BALANCE_SCALE,
                rationale="shows the equation as a balance",
            ),
            TemplateOption(
                template=TemplateName.NUMBER_LINE,
                rationale="shows one forward jump",
            ),
            TemplateOption(
                template=TemplateName.TEXT_CARD,
                rationale="always-compatible fallback",
            ),
        ],
        grade_level=1,
        ambiguous=False,
    )


def _upload_candidate(client):
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
        return client.post(
            "/upload",
            files={
                "file": (
                    "deck.pptx",
                    _pptx_bytes(),
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        )
```

Use `_upload_candidate(client)` in the render-related tests instead of repeating the upload patch block.

- [ ] **Step 2: Add `/options` response and cache tests**

Append:

```python
def test_options_returns_ranked_templates_and_caches_result():
    from app.routes import store

    client = _client()
    upload = _upload_candidate(client)

    with patch("app.routes.classify_candidate", return_value=_classification()) as classify:
        resp = client.post("/options", json={"candidate_ids": ["c1"]})

    assert resp.status_code == 200
    item = resp.json()["options"][0]
    assert item == {
        "candidate_id": "c1",
        "grade_level": 1,
        "ambiguous": False,
        "templates": [
            {
                "template": "balance_scale",
                "rationale": "shows the equation as a balance",
            },
            {"template": "number_line", "rationale": "shows one forward jump"},
            {"template": "text_card", "rationale": "always-compatible fallback"},
        ],
    }
    session = store.get(upload.json()["session_id"])
    assert session.options["c1"] == _classification()
    classify.assert_called_once_with(_candidate().source_excerpt)


def test_options_unknown_candidate_is_404():
    client = _client()
    _upload_candidate(client)

    resp = client.post("/options", json={"candidate_ids": ["does-not-exist"]})

    assert resp.status_code == 404


def test_options_without_session_is_400():
    client = _client()

    resp = client.post("/options", json={"candidate_ids": ["c1"]})

    assert resp.status_code == 400
```

- [ ] **Step 3: Migrate the successful render test to picks and assert explicit arguments**

In `test_render_returns_clip_url_for_a_rendered_scene`, change the fake and request to:

```python
    def fake_process_scene(candidate, output_dir, *, template, grade):
        assert template == TemplateName.NUMBER_LINE
        assert grade == 1
        return Scene(
            scene_id="s1",
            candidate_id=candidate.candidate_id,
            template=template,
            grade_level=grade,
            status="approved",
            render_path=clip_file,
        )

    client = _client()
    _upload_candidate(client)
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})
    with patch("app.routes.process_scene", side_effect=fake_process_scene):
        resp = client.post(
            "/render",
            json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
        )
```

Keep the existing response and clip-download assertions.

- [ ] **Step 4: Add cached-offer validation tests and migrate existing render requests**

Append:

```python
def test_render_rejects_template_that_was_not_offered():
    client = _client()
    _upload_candidate(client)
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})

    resp = client.post(
        "/render",
        json={"picks": [{"candidate_id": "c1", "template": "array_grid"}]},
    )

    assert resp.status_code == 400
    assert "not offered" in resp.json()["detail"]


def test_render_rejects_pick_before_options_are_cached():
    client = _client()
    _upload_candidate(client)

    resp = client.post(
        "/render",
        json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
    )

    assert resp.status_code == 400
    assert "options" in resp.json()["detail"].lower()


def test_render_rejects_unknown_template_name_as_bad_request():
    client = _client()
    _upload_candidate(client)
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})

    resp = client.post(
        "/render",
        json={"picks": [{"candidate_id": "c1", "template": "hologram"}]},
    )

    assert resp.status_code == 400
    assert "not offered" in resp.json()["detail"]
```

Update all remaining render requests from `{"candidate_ids": [...]}` to:

```python
{"picks": [{"candidate_id": "c1", "template": "text_card"}]}
```

Use the actual candidate id required by each test. For `test_render_unknown_candidate_is_404`, use:

```python
{"picks": [{"candidate_id": "does-not-exist", "template": "text_card"}]}
```

For `test_render_without_session_is_400`, use:

```python
{"picks": [{"candidate_id": "c1", "template": "text_card"}]}
```

Before the fallback-response render request, call `/options` with `_classification()` and update its fake to accept keyword-only `template` and `grade` like the successful fake.

- [ ] **Step 5: Run the route tests and confirm `/options` and `picks` are not implemented**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_routes.py -v
```

Expected: FAIL with `/options` returning 404 and `/render` rejecting the new `picks` body.

- [ ] **Step 6: Add route request/response models and classification import**

In `backend/app/routes.py`, add imports:

```python
from app.models.scene import TemplateName
from app.pipeline.classification import classify_candidate
```

Replace the old `RenderRequest` definition with:

```python
class OptionsRequest(BaseModel):
    candidate_ids: list[str]


class TemplateOptionOut(BaseModel):
    template: TemplateName
    rationale: str


class CandidateOptionsOut(BaseModel):
    candidate_id: str
    grade_level: int
    ambiguous: bool
    templates: list[TemplateOptionOut]


class OptionsResponse(BaseModel):
    options: list[CandidateOptionsOut]


class RenderPick(BaseModel):
    candidate_id: str
    template: str


class RenderRequest(BaseModel):
    picks: list[RenderPick]
```

- [ ] **Step 7: Implement `/options` immediately before `/render`**

Add:

```python
@router.post("/options", response_model=OptionsResponse)
def get_options(
    request: OptionsRequest,
    session_id: str | None = Cookie(default=None),
):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    results: list[CandidateOptionsOut] = []
    for candidate_id in request.candidate_ids:
        candidate = session.candidates.get(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"Unknown candidate {candidate_id}")

        classification = classify_candidate(candidate.source_excerpt)
        session.options[candidate_id] = classification
        results.append(
            CandidateOptionsOut(
                candidate_id=candidate_id,
                grade_level=classification.grade_level,
                ambiguous=classification.ambiguous,
                templates=[
                    TemplateOptionOut(
                        template=option.template,
                        rationale=option.rationale,
                    )
                    for option in classification.options
                ],
            )
        )
    return OptionsResponse(options=results)
```

- [ ] **Step 8: Replace the `/render` loop with cached-pick validation**

Keep the session lookup, then replace the result loop with:

```python
    results: list[ClipResult] = []
    for pick in request.picks:
        candidate = session.candidates.get(pick.candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown candidate {pick.candidate_id}",
            )

        classification = session.options.get(pick.candidate_id)
        if classification is None:
            raise HTTPException(
                status_code=400,
                detail=f"No options cached for candidate {pick.candidate_id}",
            )
        offered = {option.template.value for option in classification.options}
        if pick.template not in offered:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Template {pick.template} was not offered for "
                    f"candidate {pick.candidate_id}"
                ),
            )
        selected_template = TemplateName(pick.template)

        scene = process_scene(
            candidate,
            session.output_dir,
            template=selected_template,
            grade=classification.grade_level,
        )
        clip_url = None
        if scene.render_path is not None:
            clip_id = store.register_clip(scene.render_path)
            clip_url = f"/clips/{clip_id}"
        results.append(
            ClipResult(
                candidate_id=pick.candidate_id,
                status=scene.status,
                clip_url=clip_url,
                fallback_reason=scene.fallback_reason,
            )
        )
    return RenderResponse(clips=results)
```

- [ ] **Step 9: Run focused route tests**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_routes.py -v
```

Expected: PASS; `/options` caches the ranked result, `/render` accepts only an offered choice, and clip responses/downloads retain their existing shape.

- [ ] **Step 10: Commit the API flow**

```bash
git add backend/app/routes.py backend/tests/test_routes.py
git commit -m "feat: add visualization options API"
```

---

### Task 6: Add the visualization-choice screen to React

**Files:**

- Modify: `frontend/src/App.jsx`
- Modify: `frontend/vite.config.js`

**Interfaces:**

- Adds state: `options` (API rows or `null`) and `picks` (`candidate_id -> template`).
- Candidates screen sends `{candidate_ids}` to `/options` via **Get options.**
- Options screen renders one radio group per candidate and sends `{picks}` to `/render` via **Render.**
- Result screen preserves download links and fallback reasons; its back button returns to the current option choices.

- [ ] **Step 1: Replace `frontend/src/App.jsx` with the three-screen state flow**

```jsx
import { useState } from 'react'

export default function App() {
  const [candidates, setCandidates] = useState(null)
  const [selected, setSelected] = useState({})
  const [options, setOptions] = useState(null)
  const [picks, setPicks] = useState({})
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleUpload(event) {
    event.preventDefault()
    const file = event.target.file.files[0]
    if (!file) return
    setError(null)
    setLoading(true)
    setOptions(null)
    setPicks({})
    setResults(null)
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/upload', {
        method: 'POST',
        body: form,
        credentials: 'include',
      })
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Upload failed')
      const data = await resp.json()
      setCandidates(data.candidates)
      setSelected({})
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function toggle(id) {
    setSelected((previous) => ({ ...previous, [id]: !previous[id] }))
  }

  async function handleGetOptions() {
    const candidateIds = Object.keys(selected).filter((id) => selected[id])
    if (candidateIds.length === 0) return
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch('/options', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_ids: candidateIds }),
      })
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Could not get options')
      const data = await resp.json()
      const initialPicks = Object.fromEntries(
        data.options
          .filter((item) => item.templates.length > 0)
          .map((item) => [item.candidate_id, item.templates[0].template]),
      )
      setOptions(data.options)
      setPicks(initialPicks)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleRender() {
    if (!options || options.some((item) => !picks[item.candidate_id])) return
    setError(null)
    setLoading(true)
    try {
      const renderPicks = options.map((item) => ({
        candidate_id: item.candidate_id,
        template: picks[item.candidate_id],
      }))
      const resp = await fetch('/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ picks: renderPicks }),
      })
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Render failed')
      const data = await resp.json()
      setResults(data.clips)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main style={{ maxWidth: 720, margin: '2rem auto', fontFamily: 'sans-serif' }}>
      <h1>Math Animation Generator</h1>

      <form onSubmit={handleUpload}>
        <input type="file" name="file" accept=".pptx" />
        <button type="submit" disabled={loading}>Upload</button>
      </form>

      {error && <p style={{ color: 'crimson' }}>{error}</p>}
      {loading && <p>Working…</p>}

      {candidates && candidates.length === 0 && <p>No problems found in this document.</p>}

      {candidates && candidates.length > 0 && !options && !results && (
        <section>
          <h2>Candidates</h2>
          {candidates.map((candidate) => (
            <label
              key={candidate.candidate_id}
              style={{ display: 'block', margin: '0.5rem 0' }}
            >
              <input
                type="checkbox"
                checked={!!selected[candidate.candidate_id]}
                onChange={() => toggle(candidate.candidate_id)}
              />
              <strong> {candidate.one_line_summary}</strong>
              <div style={{ color: '#666', fontSize: '0.85rem' }}>
                slide {candidate.slide_index}: {candidate.source_excerpt}
              </div>
            </label>
          ))}
          <button onClick={handleGetOptions} disabled={loading}>Get options.</button>
        </section>
      )}

      {options && !results && (
        <section>
          <h2>Choose visualizations</h2>
          {options.map((item) => {
            const candidate = candidates.find(
              (entry) => entry.candidate_id === item.candidate_id,
            )
            return (
              <fieldset key={item.candidate_id} style={{ margin: '1rem 0' }}>
                <legend>{candidate?.one_line_summary || item.candidate_id}</legend>
                {item.templates.map((option) => (
                  <label key={option.template} style={{ display: 'block', margin: '0.4rem 0' }}>
                    <input
                      type="radio"
                      name={`visualization-${item.candidate_id}`}
                      value={option.template}
                      checked={picks[item.candidate_id] === option.template}
                      onChange={() => setPicks((previous) => ({
                        ...previous,
                        [item.candidate_id]: option.template,
                      }))}
                    />
                    {' '}{option.template} — {option.rationale}
                  </label>
                ))}
              </fieldset>
            )
          })}
          <button onClick={handleRender} disabled={loading}>Render.</button>{' '}
          <button
            onClick={() => {
              setOptions(null)
              setPicks({})
              setError(null)
            }}
            disabled={loading}
          >
            Back to candidates
          </button>
        </section>
      )}

      {results && (
        <section>
          <h2>Results</h2>
          {results.map((result) => (
            <div key={result.candidate_id} style={{ margin: '0.75rem 0' }}>
              {result.clip_url ? (
                <a href={result.clip_url} download>
                  Download clip ({result.candidate_id})
                </a>
              ) : (
                <span>Clip {result.candidate_id}</span>
              )}
              {result.status === 'fallback' && (
                <div style={{ color: '#b45309', fontSize: '0.85rem' }}>
                  Fallback: {result.fallback_reason}
                </div>
              )}
            </div>
          ))}
          <button onClick={() => setResults(null)}>Back to options</button>
        </section>
      )}
    </main>
  )
}
```

- [ ] **Step 2: Add the `/options` Vite proxy**

In `frontend/vite.config.js`, add the route beside `/upload` and `/render`:

```javascript
      '/options': 'http://localhost:8000',
```

- [ ] **Step 3: Build the frontend**

Run:

```bash
cd frontend && npm run build
```

Expected: Vite exits 0 and emits `frontend/dist/` without JSX or bundling errors.

- [ ] **Step 4: Commit the three-screen UI**

```bash
git add frontend/src/App.jsx frontend/vite.config.js
git commit -m "feat: add visualization picker UI"
```

---

### Task 7: Document and verify the complete flow

**Files:**

- Modify: `README.md`

**Interfaces:**

- Documents: Bedrock is used by `/upload`, `/options`, and `/render` extraction; `/render` no longer performs classification.
- Documents: API request/response shapes and the upload → candidates → options → render flow.

- [ ] **Step 1: Update the README product flow and Bedrock description**

Replace the opening paragraph with:

```markdown
Upload a PPTX of K–8 math example problems, pick the problems you want, choose a visualization for each from ranked compatible options, and download short Manim-rendered MP4 clips. A FastAPI backend discovers candidate problems, classifies each selected problem into compatible visual templates (number line, array grid, fraction bar, balance scale, or text card), validates the teacher's choice, and renders it — falling back to an honest, labeled text card when extraction or rendering cannot satisfy the chosen template. A React + Vite frontend drives the upload → select problems → choose visualizations → render flow.
```

Update the prerequisite sentence to:

```markdown
- **AWS credentials with Amazon Bedrock access** — required for `/upload` (problem discovery), `/options` (ranked classification), and `/render` (parameter extraction)
```

Update the Vite proxy paragraph to name `/options`, and replace the manual-start sentence with:

```markdown
**Start the backend first**, then the frontend. Open `http://localhost:5173`, upload a small PPTX with a math problem, select one or more candidates, click **Get options.**, choose a visualization for each problem, and click **Render.** — a downloadable clip (or a labeled fallback reason) appears.
```

- [ ] **Step 2: Replace the API table with the new contracts**

Use:

```markdown
| Method | Path           | Purpose                                                                 |
|--------|----------------|-------------------------------------------------------------------------|
| POST   | `/upload`      | Multipart PPTX (`.pptx` only, ≤50 slides, ≤50 MB) → discovered candidates + httponly session cookie |
| POST   | `/options`     | JSON `{ "candidate_ids": [...] }` → ranked compatible templates + rationale per selected candidate |
| POST   | `/render`      | JSON `{ "picks": [{ "candidate_id": "...", "template": "number_line" }] }` → rendered clips with status / clip URL / fallback reason |
| GET    | `/clips/{id}`  | Download a rendered MP4 by server-issued clip id                        |
```

- [ ] **Step 3: Run the focused non-render backend tests together**

Run:

```bash
cd backend && ../.venv/bin/python -m pytest \
  tests/pipeline/test_classification.py \
  tests/templates/test_number_line_guard.py \
  tests/pipeline/test_process_scene.py \
  tests/test_session.py \
  tests/test_routes.py -v
```

Expected: PASS with no AWS or real Manim calls because these tests mock external classification/extraction/rendering boundaries.

- [ ] **Step 4: Run the complete backend regression suite**

Run:

```bash
cd backend && PATH="/Library/TeX/texbin:/opt/homebrew/bin:$PATH" ../.venv/bin/python -m pytest
```

Expected: PASS for all backend tests, including real Manim/ffmpeg render smoke tests.

- [ ] **Step 5: Re-run the production frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: Vite exits 0 and reports a successful production bundle.

- [ ] **Step 6: Perform the browser smoke test against the running stack**

Start the services in separate terminals:

```bash
./scripts/run-backend.sh
```

```bash
./scripts/run-frontend.sh
```

Then verify in `http://localhost:5173` with a PPTX containing a single-operation problem such as `6 + 3 = ?`:

1. Upload shows the candidate without making a classification choice visible yet.
2. Selecting the candidate and clicking **Get options.** opens the options screen.
3. The first-ranked option is selected by default, `number_line` is available when Bedrock identifies it as structurally compatible, and `text_card` is last.
4. Changing the radio choice and clicking **Render.** produces one clip for the chosen template.
5. **Back to options** preserves the radio choices for the active browser session.
6. A fallback result, if extraction violates the chosen template guard, displays `fallback_reason` and still offers the rendered text-card download when fallback rendering succeeds.

- [ ] **Step 7: Commit documentation after all verification passes**

```bash
git add README.md
git commit -m "docs: describe visualization selection flow"
```

---

## Completion Criteria

- Classification returns ranked `TemplateOption` values and the API-visible result always ends with `text_card`.
- A one-step number line validates and renders; zero or four steps and all existing guard violations remain rejected.
- Explicit `process_scene` calls skip classification and preserve retry plus honest mismatch fallback.
- `/options` classifies only selected candidate ids and caches normalized results.
- `/render` accepts picks, rejects unoffered choices, reuses cached grade levels, and does not call classification.
- The browser exposes candidates, options, and results as distinct screens with the top option selected by default.
- Focused tests, the complete backend suite, the frontend build, and the manual three-screen smoke test all pass.
