# Week 2 Pipeline and Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Week 1 backend primitives into a working vertical slice — upload a PPTX in a browser, select discovered candidate problems, and download rendered MP4 clips — with three new templates and honest, clearly-labeled fallback for anything that doesn't classify or render.

**Architecture:** Add two pipeline modules (`classification`, `process_scene`) where `process_scene` is the single owner of the per-candidate classify → extract → validate → render flow and all fallback/retry policy. Add three templates (`text_card`, `fraction_bar`, `balance_scale`) following the Week 1 per-template file layout. Stand up FastAPI routes (`/upload`, `/render`, `/clips/{id}`) with in-memory session state, and a React + Vite frontend covering upload → candidate selection → trigger render.

**Tech Stack:** Python 3.11+, Pydantic v2, Manim (CE), boto3/Bedrock (`converse` tool-use), FastAPI + uvicorn, python-multipart, pytest + httpx `TestClient`; React 18 + Vite for the frontend.

**Spec:** `docs/superpowers/specs/2026-07-21-week2-pipeline-and-ui-design.md`.

## Global Constraints

- Python 3.11+; all Pydantic models use Pydantic v2 syntax (`model_validate`, `model_dump`, `@model_validator(mode="after")`).
- The LLM never computes arithmetic — every running total/equality is computed in Python, never trusted from a Bedrock response. Classification only selects a representation and infers a grade; it computes no answer.
- Bedrock output is untrusted: classification `template` is validated against the `TemplateName` enum; extracted params validated by Pydantic + a per-template compatibility guard.
- Every template has a Pydantic params model (`params.py`) and a separate compatibility guard function (`guard.py`) the params model's validator calls; guards apply to any params instance regardless of origin.
- Every Manim render runs in its own OS subprocess (Week 1 `render_scene_to_mp4`) to avoid Manim's global `config` singleton bleeding state.
- Classification ambiguity (or no template fit) routes to the `text_card` fallback with **no retry**. Extraction/validation or render failure retries **once with backoff**, then falls back. The two fallback-reason strings are distinct so the teacher sees an accurate cause.
- Input is PPTX only; enforce the 50-slide cap and reject non-PPTX uploads before the pipeline runs.
- Session ids and clip ids are server-generated (`uuid4`), never trusted from the client for anything but lookup; the download route never joins client input into a filesystem path.
- State is in-memory only (no database, no cross-restart persistence) — matches the demo scope.
- Dependencies stay pinned in `backend/pyproject.toml`. Generated binary fixtures and rendered videos stay untracked.
- Every task's tests must pass before the next; commit after each task.

## File Structure

**Backend (new):**
- `backend/app/pipeline/classification.py` — Bedrock classification/grade-inference call.
- `backend/app/pipeline/process_scene.py` — per-candidate orchestrator; owns fallback/retry policy.
- `backend/app/templates/text_card/{__init__,params,guard,scene}.py` — fallback card template.
- `backend/app/templates/fraction_bar/{__init__,params,guard,scene}.py` — partitioned-shape (fractions) template.
- `backend/app/templates/balance_scale/{__init__,params,guard,scene}.py` — equality-balance template.
- `backend/app/session.py` — in-memory `SessionStore` + `Session`.
- `backend/app/routes.py` — FastAPI router (`/upload`, `/render`, `/clips/{id}`).
- `backend/app/main.py` — FastAPI app factory + CORS.

**Backend (modified):**
- `backend/app/models/scene.py` — add three `TemplateName` members.
- `backend/app/templates/registry.py` — register the three new templates.
- `backend/pyproject.toml` — add `python-multipart`; add dev `httpx`.

**Frontend (new):**
- `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`, `frontend/src/main.jsx`, `frontend/src/App.jsx`.

**Tests (new):** one guard test + one real-render smoke test per template; `test_classification.py`; `test_process_scene.py`; `test_session.py`; `test_routes.py`.

---

### Task 1: `text_card` fallback template

**Files:**
- Create: `backend/app/templates/text_card/__init__.py`
- Create: `backend/app/templates/text_card/guard.py`
- Create: `backend/app/templates/text_card/params.py`
- Create: `backend/app/templates/text_card/scene.py`
- Modify: `backend/app/models/scene.py` (add `TEXT_CARD` to `TemplateName`)
- Modify: `backend/app/templates/registry.py` (register `text_card`)
- Test: `backend/tests/templates/test_text_card_guard.py`
- Test: `backend/tests/templates/test_text_card_scene.py`

**Interfaces:**
- Produces: `TextCardParams` with fields `headline: str`, `lines: list[str]` (module `app.templates.text_card.params`); `TextCardScene` (Manim `Scene`, settable `.params`); `TemplateName.TEXT_CARD == "text_card"` — consumed by `app.pipeline.process_scene` (Task 5) and `app.templates.registry`.

- [ ] **Step 1: Add the `TEXT_CARD` enum member**

In `backend/app/models/scene.py`, add to `class TemplateName(str, Enum)`:

```python
    TEXT_CARD = "text_card"
```

- [ ] **Step 2: Create empty `backend/app/templates/text_card/__init__.py`**

- [ ] **Step 3: Write the failing guard test**

```python
# backend/tests/templates/test_text_card_guard.py
import pytest
from pydantic import ValidationError


def test_valid_text_card_passes():
    from app.templates.text_card.params import TextCardParams

    params = TextCardParams(headline="Detected: 3 + 4", lines=["3 + 4 on slide 2"])
    assert params.headline == "Detected: 3 + 4"


def test_blank_headline_is_rejected():
    from app.templates.text_card.params import TextCardParams

    with pytest.raises(ValidationError):
        TextCardParams(headline="   ", lines=["something"])


def test_empty_lines_list_is_rejected():
    from app.templates.text_card.params import TextCardParams

    with pytest.raises(ValidationError):
        TextCardParams(headline="Heading", lines=[])
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd backend && ../.venv/bin/python -m pytest tests/templates/test_text_card_guard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.templates.text_card.params'`

- [ ] **Step 5: Write `backend/app/templates/text_card/guard.py`**

```python
def check_text_card_compatibility(params) -> None:
    if not params.headline or not params.headline.strip():
        raise ValueError("Text card headline must be nonblank")
    if not params.lines:
        raise ValueError("Text card requires at least one line")
    if any(not line or not line.strip() for line in params.lines):
        raise ValueError("Text card lines must all be nonblank")
```

- [ ] **Step 6: Write `backend/app/templates/text_card/params.py`**

```python
from pydantic import BaseModel, Field, model_validator

from app.templates.text_card.guard import check_text_card_compatibility


class TextCardParams(BaseModel):
    headline: str
    lines: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_guard(self):
        check_text_card_compatibility(self)
        return self
```

- [ ] **Step 7: Write `backend/app/templates/text_card/scene.py`**

```python
from manim import *


class TextCardScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("TextCardScene.params must be set before construct() runs")

        headline = Text(self.params.headline, weight=BOLD).scale(0.7).to_edge(UP)
        lines = VGroup(*[Text(line).scale(0.5) for line in self.params.lines])
        lines.arrange(DOWN, aligned_edge=LEFT, buff=0.3).next_to(headline, DOWN, buff=0.6)

        self.play(Write(headline))
        self.play(LaggedStart(*[FadeIn(line) for line in lines], lag_ratio=0.2))
        self.wait(1)
```

- [ ] **Step 8: Register the template in `backend/app/templates/registry.py`**

Add the imports at the top with the existing ones:

```python
from app.templates.text_card.params import TextCardParams
from app.templates.text_card.scene import TextCardScene
```

Add the registry entry inside `_REGISTRY`:

```python
    TemplateName.TEXT_CARD: (TextCardScene, TextCardParams),
```

- [ ] **Step 9: Run the guard test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/templates/test_text_card_guard.py -v`
Expected: PASS (3 tests)

- [ ] **Step 10: Write the real-render smoke test (invokes Manim + ffmpeg)**

```python
# backend/tests/templates/test_text_card_scene.py
from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.text_card.params import TextCardParams


def test_text_card_renders_to_mp4(tmp_path):
    params = TextCardParams(
        headline="Detected: 3 + 4",
        lines=["Slide 2: 3 + 4", "Fell back to a text card."],
    )
    output_path = tmp_path / "text_card.mp4"

    result_path = render_scene_to_mp4(TemplateName.TEXT_CARD, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
```

- [ ] **Step 11: Run the smoke test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/templates/test_text_card_scene.py -v -s`
Expected: PASS (1 test; several seconds of Manim/ffmpeg output is normal)

- [ ] **Step 12: Commit**

```bash
git add backend/app/templates/text_card backend/app/models/scene.py backend/app/templates/registry.py backend/tests/templates/test_text_card_guard.py backend/tests/templates/test_text_card_scene.py
git commit -m "feat: add text_card fallback template"
```

---

### Task 2: `fraction_bar` template (same-denominator partitioned shape)

**Files:**
- Create: `backend/app/templates/fraction_bar/__init__.py`
- Create: `backend/app/templates/fraction_bar/guard.py`
- Create: `backend/app/templates/fraction_bar/params.py`
- Create: `backend/app/templates/fraction_bar/scene.py`
- Modify: `backend/app/models/scene.py` (add `FRACTION_BAR`)
- Modify: `backend/app/templates/registry.py` (register `fraction_bar`)
- Test: `backend/tests/templates/test_fraction_bar_guard.py`
- Test: `backend/tests/templates/test_fraction_bar_scene.py`

**Interfaces:**
- Produces: `FractionBarParams` (fields `denominator: int`, `start_numerator: int`, `steps: list[FractionStep]`), `FractionStep` (fields `operation: "add"|"subtract"`, `numerator: int`) (module `app.templates.fraction_bar.params`); `FractionBarScene`; `TemplateName.FRACTION_BAR == "fraction_bar"` — consumed by `process_scene` (Task 5) and `registry`.
- **Design note (refinement of the spec):** fractions are modeled as a single shared integer `denominator` plus integer numerators, not `fractions.Fraction`. This is deliberate — `Fraction` auto-reduces (`2/4 → 1/2`), which would break the same-denominator guard for the exact pedagogical case (`1/4 + 2/4`) it must accept. A fixed `denominator` also matches how the bar renders (a fixed partition count). Arithmetic stays integer numerator math in Python.

- [ ] **Step 1: Add the `FRACTION_BAR` enum member**

In `backend/app/models/scene.py`, add to `TemplateName`:

```python
    FRACTION_BAR = "fraction_bar"
```

- [ ] **Step 2: Create empty `backend/app/templates/fraction_bar/__init__.py`**

- [ ] **Step 3: Write the failing guard test**

```python
# backend/tests/templates/test_fraction_bar_guard.py
import pytest
from pydantic import ValidationError


def test_same_denominator_addition_passes():
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    params = FractionBarParams(
        denominator=4,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=2),
            FractionStep(operation="add", numerator=1),
        ],
    )
    assert params.denominator == 4


def test_running_total_going_negative_is_rejected():
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    with pytest.raises(ValidationError):
        FractionBarParams(
            denominator=4,
            start_numerator=1,
            steps=[
                FractionStep(operation="subtract", numerator=3),
                FractionStep(operation="add", numerator=1),
            ],
        )


def test_total_over_renderable_bound_is_rejected():
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    with pytest.raises(ValidationError):
        FractionBarParams(
            denominator=4,
            start_numerator=4,
            steps=[
                FractionStep(operation="add", numerator=8),
                FractionStep(operation="add", numerator=8),
            ],
        )


def test_denominator_of_one_is_rejected():
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    with pytest.raises(ValidationError):
        FractionBarParams(
            denominator=1,
            start_numerator=0,
            steps=[
                FractionStep(operation="add", numerator=1),
                FractionStep(operation="add", numerator=1),
            ],
        )


@pytest.mark.parametrize("step_count", [0, 1, 4])
def test_step_count_outside_two_to_three_is_rejected(step_count):
    from app.templates.fraction_bar.params import FractionBarParams, FractionStep

    steps = [FractionStep(operation="add", numerator=1) for _ in range(step_count)]
    with pytest.raises(ValidationError):
        FractionBarParams(denominator=4, start_numerator=0, steps=steps)
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd backend && ../.venv/bin/python -m pytest tests/templates/test_fraction_bar_guard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.templates.fraction_bar.params'`

- [ ] **Step 5: Write `backend/app/templates/fraction_bar/guard.py`**

```python
MAX_FRACTION_UNITS = 4  # renderable upper bound, in whole units


def check_fraction_bar_compatibility(params) -> None:
    limit = params.denominator * MAX_FRACTION_UNITS

    total = params.start_numerator
    values = [total]
    for step in params.steps:
        total = total + step.numerator if step.operation == "add" else total - step.numerator
        values.append(total)

    for value in values:
        if value < 0:
            raise ValueError(
                f"Fraction running total went negative ({value}/{params.denominator})"
            )
        if value > limit:
            raise ValueError(
                f"Fraction total {value}/{params.denominator} exceeds renderable bound "
                f"of {MAX_FRACTION_UNITS} whole units"
            )
```

- [ ] **Step 6: Write `backend/app/templates/fraction_bar/params.py`**

```python
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.templates.fraction_bar.guard import check_fraction_bar_compatibility


class FractionStep(BaseModel):
    operation: Literal["add", "subtract"]
    numerator: int = Field(gt=0)


class FractionBarParams(BaseModel):
    denominator: int = Field(gt=1)
    start_numerator: int = Field(ge=0)
    steps: list[FractionStep] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def _check_guard(self):
        check_fraction_bar_compatibility(self)
        return self
```

- [ ] **Step 7: Write `backend/app/templates/fraction_bar/scene.py`**

```python
from manim import *


class FractionBarScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("FractionBarScene.params must be set before construct() runs")

        denominator = self.params.denominator
        total = self.params.start_numerator
        values = [total]
        for step in self.params.steps:
            total = total + step.numerator if step.operation == "add" else total - step.numerator
            values.append(total)

        n_cells = max(max(values), denominator)
        cell_width = min(0.6, 12.0 / n_cells)

        cells = VGroup()
        for _ in range(n_cells):
            cells.add(Rectangle(width=cell_width, height=0.8, stroke_color=WHITE))
        cells.arrange(RIGHT, buff=0).move_to(ORIGIN)
        self.play(Create(cells))

        label = Text(f"{values[0]}/{denominator}").scale(0.6).next_to(cells, UP)
        self.play(Write(label))

        current = values[0]
        self.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(current)])

        for value in values[1:]:
            new_label = Text(f"{value}/{denominator}").scale(0.6).next_to(cells, UP)
            if value > current:
                self.play(
                    *[cells[i].animate.set_fill(GREEN, opacity=0.8) for i in range(current, value)],
                    Transform(label, new_label),
                )
                self.play(*[cells[i].animate.set_fill(BLUE, opacity=0.8) for i in range(current, value)])
            elif value < current:
                self.play(
                    *[cells[i].animate.set_fill(BLUE, opacity=0.0) for i in range(value, current)],
                    Transform(label, new_label),
                )
            current = value

        self.wait(1)
```

- [ ] **Step 8: Register the template in `backend/app/templates/registry.py`**

Add imports:

```python
from app.templates.fraction_bar.params import FractionBarParams
from app.templates.fraction_bar.scene import FractionBarScene
```

Add the registry entry inside `_REGISTRY`:

```python
    TemplateName.FRACTION_BAR: (FractionBarScene, FractionBarParams),
```

- [ ] **Step 9: Run the guard test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/templates/test_fraction_bar_guard.py -v`
Expected: PASS (7 tests)

- [ ] **Step 10: Write the real-render smoke test**

```python
# backend/tests/templates/test_fraction_bar_scene.py
from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.fraction_bar.params import FractionBarParams, FractionStep


def test_fraction_bar_renders_to_mp4(tmp_path):
    params = FractionBarParams(
        denominator=4,
        start_numerator=1,
        steps=[
            FractionStep(operation="add", numerator=2),
            FractionStep(operation="subtract", numerator=1),
        ],
    )
    output_path = tmp_path / "fraction_bar.mp4"

    result_path = render_scene_to_mp4(TemplateName.FRACTION_BAR, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
```

- [ ] **Step 11: Run the smoke test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/templates/test_fraction_bar_scene.py -v -s`
Expected: PASS (1 test)

- [ ] **Step 12: Commit**

```bash
git add backend/app/templates/fraction_bar backend/app/models/scene.py backend/app/templates/registry.py backend/tests/templates/test_fraction_bar_guard.py backend/tests/templates/test_fraction_bar_scene.py
git commit -m "feat: add fraction_bar template with same-denominator guard"
```

---

### Task 3: `balance_scale` template (a + b = c equality)

**Files:**
- Create: `backend/app/templates/balance_scale/__init__.py`
- Create: `backend/app/templates/balance_scale/guard.py`
- Create: `backend/app/templates/balance_scale/params.py`
- Create: `backend/app/templates/balance_scale/scene.py`
- Modify: `backend/app/models/scene.py` (add `BALANCE_SCALE`)
- Modify: `backend/app/templates/registry.py` (register `balance_scale`)
- Test: `backend/tests/templates/test_balance_scale_guard.py`
- Test: `backend/tests/templates/test_balance_scale_scene.py`

**Interfaces:**
- Produces: `BalanceScaleParams` (fields `left_terms: list[int]` of length 2, `right_total: int`), `BalanceScaleScene`, `TemplateName.BALANCE_SCALE == "balance_scale"` — consumed by `process_scene` (Task 5) and `registry`.
- v1 scope: a simple `a + b = c` equality visualization; the guard requires `sum(left_terms) == right_total`.

- [ ] **Step 1: Add the `BALANCE_SCALE` enum member**

In `backend/app/models/scene.py`, add to `TemplateName`:

```python
    BALANCE_SCALE = "balance_scale"
```

- [ ] **Step 2: Create empty `backend/app/templates/balance_scale/__init__.py`**

- [ ] **Step 3: Write the failing guard test**

```python
# backend/tests/templates/test_balance_scale_guard.py
import pytest
from pydantic import ValidationError


def test_balanced_equation_passes():
    from app.templates.balance_scale.params import BalanceScaleParams

    params = BalanceScaleParams(left_terms=[3, 4], right_total=7)
    assert params.right_total == 7


def test_unbalanced_equation_is_rejected():
    from app.templates.balance_scale.params import BalanceScaleParams

    with pytest.raises(ValidationError):
        BalanceScaleParams(left_terms=[3, 4], right_total=8)


def test_non_positive_term_is_rejected():
    from app.templates.balance_scale.params import BalanceScaleParams

    with pytest.raises(ValidationError):
        BalanceScaleParams(left_terms=[0, 4], right_total=4)


def test_total_over_renderable_bound_is_rejected():
    from app.templates.balance_scale.params import BalanceScaleParams

    with pytest.raises(ValidationError):
        BalanceScaleParams(left_terms=[15, 15], right_total=30)


@pytest.mark.parametrize("term_count", [1, 3])
def test_left_terms_must_be_exactly_two(term_count):
    from app.templates.balance_scale.params import BalanceScaleParams

    with pytest.raises(ValidationError):
        BalanceScaleParams(left_terms=[1] * term_count, right_total=term_count)
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd backend && ../.venv/bin/python -m pytest tests/templates/test_balance_scale_guard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.templates.balance_scale.params'`

- [ ] **Step 5: Write `backend/app/templates/balance_scale/guard.py`**

```python
MAX_BALANCE_VALUE = 20


def check_balance_scale_compatibility(params) -> None:
    if any(term <= 0 for term in params.left_terms):
        raise ValueError("Balance scale terms must be positive")
    if sum(params.left_terms) != params.right_total:
        left = " + ".join(str(term) for term in params.left_terms)
        raise ValueError(
            f"Balance scale does not balance: {left} != {params.right_total}"
        )
    if params.right_total > MAX_BALANCE_VALUE:
        raise ValueError(
            f"Balance scale total {params.right_total} exceeds renderable bound "
            f"{MAX_BALANCE_VALUE}"
        )
```

- [ ] **Step 6: Write `backend/app/templates/balance_scale/params.py`**

```python
from pydantic import BaseModel, Field, model_validator

from app.templates.balance_scale.guard import check_balance_scale_compatibility


class BalanceScaleParams(BaseModel):
    left_terms: list[int] = Field(min_length=2, max_length=2)
    right_total: int

    @model_validator(mode="after")
    def _check_guard(self):
        check_balance_scale_compatibility(self)
        return self
```

- [ ] **Step 7: Write `backend/app/templates/balance_scale/scene.py`**

```python
from manim import *


class BalanceScaleScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("BalanceScaleScene.params must be set before construct() runs")

        left_a, left_b = self.params.left_terms
        right = self.params.right_total

        beam = Rectangle(width=6, height=0.2, fill_opacity=1.0, color=GRAY).move_to(UP * 0.5)
        fulcrum = Triangle(color=GRAY).scale(0.5).next_to(beam, DOWN, buff=0)
        left_pan = Circle(radius=0.5, color=BLUE).move_to(beam.get_left() + DOWN * 1.2)
        right_pan = Circle(radius=0.5, color=BLUE).move_to(beam.get_right() + DOWN * 1.2)

        left_label = Text(f"{left_a} + {left_b}").scale(0.6).move_to(left_pan)
        right_label = Text(f"{right}").scale(0.6).move_to(right_pan)

        self.play(Create(beam), Create(fulcrum))
        self.play(Create(left_pan), Create(right_pan))
        self.play(Write(left_label), Write(right_label))

        equation = Text(f"{left_a} + {left_b} = {right}").scale(0.8).to_edge(DOWN)
        self.play(Write(equation))
        self.wait(1)
```

- [ ] **Step 8: Register the template in `backend/app/templates/registry.py`**

Add imports:

```python
from app.templates.balance_scale.params import BalanceScaleParams
from app.templates.balance_scale.scene import BalanceScaleScene
```

Add the registry entry inside `_REGISTRY`:

```python
    TemplateName.BALANCE_SCALE: (BalanceScaleScene, BalanceScaleParams),
```

- [ ] **Step 9: Run the guard test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/templates/test_balance_scale_guard.py -v`
Expected: PASS (6 tests)

- [ ] **Step 10: Write the real-render smoke test**

```python
# backend/tests/templates/test_balance_scale_scene.py
from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.balance_scale.params import BalanceScaleParams


def test_balance_scale_renders_to_mp4(tmp_path):
    params = BalanceScaleParams(left_terms=[3, 4], right_total=7)
    output_path = tmp_path / "balance_scale.mp4"

    result_path = render_scene_to_mp4(TemplateName.BALANCE_SCALE, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
```

- [ ] **Step 11: Run the smoke test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/templates/test_balance_scale_scene.py -v -s`
Expected: PASS (1 test)

- [ ] **Step 12: Commit**

```bash
git add backend/app/templates/balance_scale backend/app/models/scene.py backend/app/templates/registry.py backend/tests/templates/test_balance_scale_guard.py backend/tests/templates/test_balance_scale_scene.py
git commit -m "feat: add balance_scale equality template"
```

---

### Task 4: Classification / grade-inference call (Bedrock)

**Files:**
- Create: `backend/app/pipeline/classification.py`
- Test: `backend/tests/pipeline/test_classification.py`

**Interfaces:**
- Consumes: `call_with_tool` (Week 1, `app.pipeline.bedrock_client`), `TemplateName` (`app.models.scene`).
- Produces: `ClassificationResult` (fields `template: TemplateName | None`, `grade_level: int`, `ambiguous: bool`), `classify_candidate(source_text: str) -> ClassificationResult` (module `app.pipeline.classification`) — consumed by `process_scene` (Task 5).

- [ ] **Step 1: Write the failing test (Bedrock mocked)**

```python
# backend/tests/pipeline/test_classification.py
from unittest.mock import patch

import pytest
from pydantic import ValidationError


@patch("app.pipeline.classification.call_with_tool")
def test_classify_returns_template_and_grade(mock_call):
    from app.models.scene import TemplateName
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {"template": "number_line", "grade_level": 2, "ambiguous": False}

    result = classify_candidate("Sarah has 4 apples and buys 3 more.")

    assert result.template == TemplateName.NUMBER_LINE
    assert result.grade_level == 2
    assert result.ambiguous is False


@patch("app.pipeline.classification.call_with_tool")
def test_classify_can_report_ambiguous_with_no_template(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {"template": None, "grade_level": 3, "ambiguous": True}

    result = classify_candidate("There are some red and some green apples.")

    assert result.template is None
    assert result.ambiguous is True


@patch("app.pipeline.classification.call_with_tool")
def test_classify_rejects_an_unknown_template(mock_call):
    from app.pipeline.classification import classify_candidate

    mock_call.return_value = {"template": "hologram", "grade_level": 2, "ambiguous": False}

    with pytest.raises(ValidationError):
        classify_candidate("anything")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && ../.venv/bin/python -m pytest tests/pipeline/test_classification.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.classification'`

- [ ] **Step 3: Write `backend/app/pipeline/classification.py`**

```python
from pydantic import BaseModel, Field

from app.models.scene import TemplateName
from app.pipeline.bedrock_client import call_with_tool

_CLASSIFICATION_SYSTEM_PROMPT = (
    "You classify a single K-8 math example problem into one visual template category, "
    "or flag it as unsupported/ambiguous. Choose the template whose representation best "
    "fits the problem and the inferred grade level. Do not compute or state any answer. "
    "Set ambiguous=true when the operands or operation cannot be confidently determined, "
    "or when no template fits the problem."
)


class ClassificationResult(BaseModel):
    template: TemplateName | None = None
    grade_level: int = Field(ge=0, le=8)
    ambiguous: bool = False


def classify_candidate(source_text: str) -> ClassificationResult:
    schema = ClassificationResult.model_json_schema()
    result = call_with_tool(
        system_prompt=_CLASSIFICATION_SYSTEM_PROMPT,
        user_message=source_text,
        tool_name="classify_problem",
        tool_schema=schema,
    )
    return ClassificationResult.model_validate(result)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/pipeline/test_classification.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/classification.py backend/tests/pipeline/test_classification.py
git commit -m "feat: add Bedrock classification and grade-inference call"
```

---

### Task 5: `process_scene` orchestrator (fallback + retry policy)

**Files:**
- Create: `backend/app/pipeline/process_scene.py`
- Test: `backend/tests/pipeline/test_process_scene.py`

**Interfaces:**
- Consumes: `classify_candidate`/`ClassificationResult` (Task 4), `extract_params` (Week 1, `app.pipeline.extraction`), `get_template` (Week 1, `app.templates.registry`), `render_scene_to_mp4` (Week 1, `app.render.full_render`), `Candidate` (Week 1, `app.models.candidate`), `Scene`/`TemplateName` (Week 1, `app.models.scene`), `TextCardParams` (Task 1).
- Produces: `process_scene(candidate: Candidate, output_dir: Path) -> Scene` (module `app.pipeline.process_scene`); module-level constants `CLASSIFICATION_AMBIGUOUS_REASON: str`, `TECHNICAL_FAILURE_REASON: str` — consumed by `app.routes` (Task 7).

- [ ] **Step 1: Write the failing tests (all downstream calls mocked)**

```python
# backend/tests/pipeline/test_process_scene.py
from unittest.mock import patch

from app.models.candidate import Candidate
from app.models.scene import TemplateName


def _candidate():
    return Candidate(
        candidate_id="c1",
        source_excerpt="Sarah has 4 apples and buys 3 more, then gives 1 away.",
        slide_index=0,
        one_line_summary="Detected: 4 + 3 - 1",
    )


def _number_line_params():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    return NumberLineParams(
        start=4,
        steps=[NumberLineStep(operation="add", amount=3), NumberLineStep(operation="subtract", amount=1)],
    )


@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_clean_success_returns_approved_scene(mock_classify, mock_extract, mock_render, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import process_scene

    mock_classify.return_value = ClassificationResult(
        template=TemplateName.NUMBER_LINE, grade_level=2, ambiguous=False
    )
    mock_extract.return_value = _number_line_params()
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "approved"
    assert scene.template == TemplateName.NUMBER_LINE
    assert scene.render_path == tmp_path / "c1.mp4"
    assert scene.fallback_reason is None
    assert mock_extract.call_count == 1
    assert mock_render.call_count == 1


@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_ambiguous_classification_falls_back_without_extracting(mock_classify, mock_extract, mock_render, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import CLASSIFICATION_AMBIGUOUS_REASON, process_scene

    mock_classify.return_value = ClassificationResult(template=None, grade_level=3, ambiguous=True)
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "fallback"
    assert scene.template == TemplateName.TEXT_CARD
    assert scene.fallback_reason == CLASSIFICATION_AMBIGUOUS_REASON
    assert mock_extract.call_count == 0  # no blind retry against the same input


@patch("app.pipeline.process_scene.time.sleep")
@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_validation_failure_retries_once_then_succeeds(mock_classify, mock_extract, mock_render, mock_sleep, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import process_scene

    mock_classify.return_value = ClassificationResult(
        template=TemplateName.NUMBER_LINE, grade_level=2, ambiguous=False
    )
    mock_extract.side_effect = [ValueError("bad extraction"), _number_line_params()]
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "approved"
    assert mock_extract.call_count == 2
    assert mock_sleep.call_count == 1


@patch("app.pipeline.process_scene.time.sleep")
@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_repeated_render_failure_falls_back_with_technical_reason(mock_classify, mock_extract, mock_render, mock_sleep, tmp_path):
    from app.pipeline.classification import ClassificationResult
    from app.pipeline.process_scene import TECHNICAL_FAILURE_REASON, process_scene

    mock_classify.return_value = ClassificationResult(
        template=TemplateName.NUMBER_LINE, grade_level=2, ambiguous=False
    )
    mock_extract.return_value = _number_line_params()
    mock_render.side_effect = RuntimeError("manim boom")

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "fallback"
    assert scene.template == TemplateName.TEXT_CARD
    assert scene.fallback_reason.startswith(TECHNICAL_FAILURE_REASON)
    assert mock_extract.call_count == 2  # retried once before falling back
    assert scene.render_path is None  # even the fallback render failed


@patch("app.pipeline.process_scene.render_scene_to_mp4")
@patch("app.pipeline.process_scene.extract_params")
@patch("app.pipeline.process_scene.classify_candidate")
def test_classification_exception_falls_back_technically(mock_classify, mock_extract, mock_render, tmp_path):
    from app.pipeline.process_scene import TECHNICAL_FAILURE_REASON, process_scene

    mock_classify.side_effect = RuntimeError("bedrock down")
    mock_render.return_value = tmp_path / "c1.mp4"

    scene = process_scene(_candidate(), tmp_path)

    assert scene.status == "fallback"
    assert scene.fallback_reason.startswith(TECHNICAL_FAILURE_REASON)
    assert mock_extract.call_count == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ../.venv/bin/python -m pytest tests/pipeline/test_process_scene.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.process_scene'`

- [ ] **Step 3: Write `backend/app/pipeline/process_scene.py`**

```python
import time
from pathlib import Path
from uuid import uuid4

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName
from app.pipeline.classification import classify_candidate
from app.pipeline.extraction import extract_params
from app.render.full_render import render_scene_to_mp4
from app.templates.registry import get_template
from app.templates.text_card.params import TextCardParams

BACKOFF_SECONDS = 0.5
DEFAULT_FALLBACK_GRADE = 0
CLASSIFICATION_AMBIGUOUS_REASON = (
    "Classification ambiguous or unsupported: no template confidently fits this problem."
)
TECHNICAL_FAILURE_REASON = "Technical failure during extraction or render"


def _fallback_scene(candidate: Candidate, grade: int, reason: str, output_dir: Path) -> Scene:
    params = TextCardParams(
        headline=candidate.one_line_summary or "Unable to animate this problem",
        lines=[candidate.source_excerpt, reason],
    )
    render_path = None
    try:
        output_path = output_dir / f"{candidate.candidate_id}.mp4"
        render_scene_to_mp4(TemplateName.TEXT_CARD, params, output_path)
        render_path = output_path
    except Exception:
        render_path = None

    return Scene(
        scene_id=str(uuid4()),
        candidate_id=candidate.candidate_id,
        template=TemplateName.TEXT_CARD,
        grade_level=grade,
        params=params.model_dump(mode="json"),
        status="fallback",
        fallback_reason=reason,
        render_path=render_path,
    )


def process_scene(candidate: Candidate, output_dir: Path) -> Scene:
    try:
        classification = classify_candidate(candidate.source_excerpt)
    except Exception as exc:
        return _fallback_scene(
            candidate, DEFAULT_FALLBACK_GRADE, f"{TECHNICAL_FAILURE_REASON}: {exc}", output_dir
        )

    grade = classification.grade_level
    if classification.ambiguous or classification.template is None:
        return _fallback_scene(candidate, grade, CLASSIFICATION_AMBIGUOUS_REASON, output_dir)

    template = classification.template
    _, params_cls = get_template(template)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            params = extract_params(candidate.source_excerpt, params_cls)
            output_path = output_dir / f"{candidate.candidate_id}.mp4"
            render_scene_to_mp4(template, params, output_path)
            return Scene(
                scene_id=str(uuid4()),
                candidate_id=candidate.candidate_id,
                template=template,
                grade_level=grade,
                params=params.model_dump(mode="json"),
                status="approved",
                render_path=output_path,
            )
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(BACKOFF_SECONDS)

    return _fallback_scene(candidate, grade, f"{TECHNICAL_FAILURE_REASON}: {last_error}", output_dir)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && ../.venv/bin/python -m pytest tests/pipeline/test_process_scene.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/process_scene.py backend/tests/pipeline/test_process_scene.py
git commit -m "feat: add process_scene orchestrator with fallback and retry policy"
```

---

### Task 6: In-memory session store

**Files:**
- Create: `backend/app/session.py`
- Test: `backend/tests/test_session.py`

**Interfaces:**
- Consumes: `Candidate` (Week 1, `app.models.candidate`).
- Produces: `Session` (attrs `session_id: str`, `candidates: dict[str, Candidate]`, `output_dir: Path`), `SessionStore(root_dir: Path)` with `create(candidates: list[Candidate]) -> Session`, `get(session_id: str) -> Session | None`, `register_clip(path: Path) -> str`, `get_clip(clip_id: str) -> Path | None` (module `app.session`) — consumed by `app.routes` (Task 7).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_session.py
from app.models.candidate import Candidate


def _candidate(cid):
    return Candidate(candidate_id=cid, source_excerpt="4 + 3", slide_index=0, one_line_summary="Detected: 4 + 3")


def test_create_stores_candidates_and_makes_output_dir(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([_candidate("a"), _candidate("b")])

    assert session.session_id
    assert set(session.candidates) == {"a", "b"}
    assert session.output_dir.is_dir()
    assert store.get(session.session_id) is session


def test_get_unknown_session_returns_none(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    assert store.get("nope") is None


def test_clip_registration_round_trips(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"x")

    clip_id = store.register_clip(clip_path)

    assert store.get_clip(clip_id) == clip_path
    assert store.get_clip("unknown") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.session'`

- [ ] **Step 3: Write `backend/app/session.py`**

```python
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from app.models.candidate import Candidate


@dataclass
class Session:
    session_id: str
    candidates: dict[str, Candidate]
    output_dir: Path


class SessionStore:
    def __init__(self, root_dir: Path):
        self._root = Path(root_dir)
        self._sessions: dict[str, Session] = {}
        self._clips: dict[str, Path] = {}

    def create(self, candidates: list[Candidate]) -> Session:
        session_id = str(uuid4())
        output_dir = self._root / session_id
        output_dir.mkdir(parents=True, exist_ok=True)
        session = Session(
            session_id=session_id,
            candidates={c.candidate_id: c for c in candidates},
            output_dir=output_dir,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def register_clip(self, path: Path) -> str:
        clip_id = str(uuid4())
        self._clips[clip_id] = Path(path)
        return clip_id

    def get_clip(self, clip_id: str) -> Path | None:
        return self._clips.get(clip_id)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_session.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/session.py backend/tests/test_session.py
git commit -m "feat: add in-memory session store"
```

---

### Task 7: FastAPI routes (`/upload`, `/render`, `/clips/{id}`)

**Files:**
- Create: `backend/app/routes.py`
- Create: `backend/app/main.py`
- Modify: `backend/pyproject.toml` (add `python-multipart`; add dev `httpx`)
- Test: `backend/tests/test_routes.py`

**Interfaces:**
- Consumes: `extract_slide_texts` (Week 1), `discover_candidates_for_document` (Week 1), `process_scene`/`CLASSIFICATION_AMBIGUOUS_REASON` (Task 5), `SessionStore` (Task 6).
- Produces: `router` (APIRouter) and module-level `store` (`SessionStore`) in `app.routes`; `app` (FastAPI) and `create_app()` in `app.main`.

- [ ] **Step 1: Add `python-multipart` and dev `httpx` to `backend/pyproject.toml`**

In `[project].dependencies`, add:

```toml
    "python-multipart>=0.0.9",
```

In `[project.optional-dependencies].dev`, extend the list to:

```toml
dev = ["pytest>=8.0", "httpx>=0.27"]
```

- [ ] **Step 2: Install the new dependencies**

Run: `cd backend && ../.venv/bin/pip install -e ".[dev]"`
Expected: installs `python-multipart` and `httpx` without error.

- [ ] **Step 3: Write `backend/app/routes.py`**

```python
import tempfile
from pathlib import Path

from fastapi import APIRouter, Cookie, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.pipeline.discovery import discover_candidates_for_document
from app.pipeline.parsing import extract_slide_texts
from app.pipeline.process_scene import process_scene
from app.session import SessionStore

MAX_SLIDES = 50

router = APIRouter()
store = SessionStore(Path(tempfile.gettempdir()) / "math_anim_sessions")


class CandidateOut(BaseModel):
    candidate_id: str
    source_excerpt: str
    slide_index: int
    one_line_summary: str


class UploadResponse(BaseModel):
    session_id: str
    candidates: list[CandidateOut]


class RenderRequest(BaseModel):
    candidate_ids: list[str]


class ClipResult(BaseModel):
    candidate_id: str
    status: str
    clip_url: str | None = None
    fallback_reason: str | None = None


class RenderResponse(BaseModel):
    clips: list[ClipResult]


@router.post("/upload", response_model=UploadResponse)
async def upload(response: Response, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Only .pptx uploads are supported")

    contents = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        slide_texts = extract_slide_texts(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if len(slide_texts) > MAX_SLIDES:
        raise HTTPException(status_code=400, detail=f"Document exceeds the {MAX_SLIDES}-slide cap")

    candidates = discover_candidates_for_document(slide_texts)
    session = store.create(candidates)
    response.set_cookie("session_id", session.session_id, httponly=True, samesite="lax")
    return UploadResponse(
        session_id=session.session_id,
        candidates=[CandidateOut(**c.model_dump()) for c in candidates],
    )


@router.post("/render", response_model=RenderResponse)
def render(request: RenderRequest, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    results: list[ClipResult] = []
    for candidate_id in request.candidate_ids:
        candidate = session.candidates.get(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"Unknown candidate {candidate_id}")

        scene = process_scene(candidate, session.output_dir)
        clip_url = None
        if scene.render_path is not None:
            clip_id = store.register_clip(scene.render_path)
            clip_url = f"/clips/{clip_id}"
        results.append(
            ClipResult(
                candidate_id=candidate_id,
                status=scene.status,
                clip_url=clip_url,
                fallback_reason=scene.fallback_reason,
            )
        )
    return RenderResponse(clips=results)


@router.get("/clips/{clip_id}")
def get_clip(clip_id: str):
    path = store.get_clip(clip_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)
```

- [ ] **Step 4: Write `backend/app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Math Animation Generator")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 5: Write the failing route tests**

```python
# backend/tests/test_routes.py
import io
from unittest.mock import patch

from fastapi.testclient import TestClient
from pptx import Presentation


def _pptx_bytes(slide_count: int = 1) -> bytes:
    presentation = Presentation()
    layout = presentation.slide_layouts[1]
    for i in range(slide_count):
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = f"Slide {i}"
        slide.placeholders[1].text = "Sarah has 4 apples and buys 3 more."
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _client():
    from app.main import create_app

    return TestClient(create_app())


def _candidate(cid="c1"):
    from app.models.candidate import Candidate

    return Candidate(
        candidate_id=cid,
        source_excerpt="Sarah has 4 apples and buys 3 more.",
        slide_index=0,
        one_line_summary="Detected: 4 + 3",
    )


def test_upload_rejects_non_pptx():
    client = _client()
    resp = client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert resp.status_code == 400


def test_upload_rejects_document_over_slide_cap():
    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[]):
        resp = client.post(
            "/upload",
            files={"file": ("big.pptx", _pptx_bytes(slide_count=51), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert resp.status_code == 400


def test_upload_returns_candidates_and_sets_cookie():
    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
        resp = client.post(
            "/upload",
            files={"file": ("deck.pptx", _pptx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["candidate_id"] == "c1"
    assert "session_id" in resp.cookies


def test_render_returns_clip_url_for_a_rendered_scene(tmp_path):
    from app.models.scene import Scene, TemplateName

    clip_file = tmp_path / "c1.mp4"
    clip_file.write_bytes(b"fake mp4")

    def fake_process_scene(candidate, output_dir):
        return Scene(
            scene_id="s1",
            candidate_id=candidate.candidate_id,
            template=TemplateName.NUMBER_LINE,
            grade_level=2,
            status="approved",
            render_path=clip_file,
        )

    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
        client.post(
            "/upload",
            files={"file": ("deck.pptx", _pptx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    with patch("app.routes.process_scene", side_effect=fake_process_scene):
        resp = client.post("/render", json={"candidate_ids": ["c1"]})

    assert resp.status_code == 200
    clip = resp.json()["clips"][0]
    assert clip["status"] == "approved"
    assert clip["clip_url"].startswith("/clips/")

    download = client.get(clip["clip_url"])
    assert download.status_code == 200
    assert download.content == b"fake mp4"


def test_render_reports_fallback_reason_without_clip():
    from app.models.scene import Scene, TemplateName

    def fake_process_scene(candidate, output_dir):
        return Scene(
            scene_id="s1",
            candidate_id=candidate.candidate_id,
            template=TemplateName.TEXT_CARD,
            grade_level=0,
            status="fallback",
            fallback_reason="Classification ambiguous or unsupported: no template confidently fits this problem.",
            render_path=None,
        )

    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
        client.post(
            "/upload",
            files={"file": ("deck.pptx", _pptx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    with patch("app.routes.process_scene", side_effect=fake_process_scene):
        resp = client.post("/render", json={"candidate_ids": ["c1"]})

    clip = resp.json()["clips"][0]
    assert clip["status"] == "fallback"
    assert clip["clip_url"] is None
    assert "ambiguous" in clip["fallback_reason"]


def test_render_unknown_candidate_is_404():
    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
        client.post(
            "/upload",
            files={"file": ("deck.pptx", _pptx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    resp = client.post("/render", json={"candidate_ids": ["does-not-exist"]})
    assert resp.status_code == 404


def test_render_without_session_is_400():
    client = _client()
    resp = client.post("/render", json={"candidate_ids": ["c1"]})
    assert resp.status_code == 400


def test_unknown_clip_id_is_404():
    client = _client()
    resp = client.get("/clips/nope")
    assert resp.status_code == 404
```

Note: `store` is a module-level singleton in `app.routes`, so `TestClient` requests within one test share session state (the upload's cookie is reused on the following `/render` call by the same client).

- [ ] **Step 6: Run the tests to verify they fail**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_routes.py -v`
Expected: FAIL — collection error / `ModuleNotFoundError: No module named 'app.main'` (or `app.routes`) before the files exist. (If Step 3/4 are already written, they pass instead.)

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && ../.venv/bin/python -m pytest tests/test_routes.py -v`
Expected: PASS (8 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/app/routes.py backend/app/main.py backend/pyproject.toml backend/tests/test_routes.py
git commit -m "feat: add FastAPI upload, render, and clip-download routes"
```

---

### Task 8: React + Vite frontend (upload → select → render → results)

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.jsx`
- Create: `frontend/src/App.jsx`
- Modify: `.gitignore` (ignore `node_modules/` and `frontend/dist/`)

**Interfaces:**
- Consumes (over HTTP, via the Vite dev proxy): `POST /upload`, `POST /render`, `GET /clips/{id}` (Task 7).
- Produces: a static SPA build (`frontend/dist/`) and a dev server on `http://localhost:5173`.

**Note on verification:** this task has no unit-test framework (adding Vitest is out of scope for Week 2). Its deliverable is a clean production build (`npm run build`) plus a documented manual smoke run. This is the one intentional deviation from the TDD cycle in this plan.

- [ ] **Step 1: Ignore Node artifacts in `.gitignore`**

Append to the root `.gitignore`:

```gitignore
# Node / frontend build artifacts
node_modules/
frontend/dist/
```

- [ ] **Step 2: Write `frontend/package.json`**

```json
{
  "name": "math-animation-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 3: Write `frontend/vite.config.js`**

The dev server proxies API paths to the FastAPI backend, so the browser talks to a single origin and the `session_id` cookie flows without cross-origin friction.

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/upload': 'http://localhost:8000',
      '/render': 'http://localhost:8000',
      '/clips': 'http://localhost:8000',
    },
  },
})
```

- [ ] **Step 4: Write `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Math Animation Generator</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Write `frontend/src/main.jsx`**

```jsx
import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(<App />)
```

- [ ] **Step 6: Write `frontend/src/App.jsx`**

```jsx
import { useState } from 'react'

export default function App() {
  const [candidates, setCandidates] = useState(null)
  const [selected, setSelected] = useState({})
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleUpload(event) {
    event.preventDefault()
    const file = event.target.file.files[0]
    if (!file) return
    setError(null)
    setLoading(true)
    setResults(null)
    const form = new FormData()
    form.append('file', file)
    try {
      const resp = await fetch('/upload', { method: 'POST', body: form, credentials: 'include' })
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
    setSelected((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  async function handleRender() {
    const ids = Object.keys(selected).filter((id) => selected[id])
    if (ids.length === 0) return
    setError(null)
    setLoading(true)
    try {
      const resp = await fetch('/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ candidate_ids: ids }),
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

      {candidates && candidates.length > 0 && !results && (
        <section>
          <h2>Candidates</h2>
          {candidates.map((c) => (
            <label key={c.candidate_id} style={{ display: 'block', margin: '0.5rem 0' }}>
              <input
                type="checkbox"
                checked={!!selected[c.candidate_id]}
                onChange={() => toggle(c.candidate_id)}
              />
              <strong> {c.one_line_summary}</strong>
              <div style={{ color: '#666', fontSize: '0.85rem' }}>
                slide {c.slide_index}: {c.source_excerpt}
              </div>
            </label>
          ))}
          <button onClick={handleRender} disabled={loading}>Render selected</button>
        </section>
      )}

      {results && (
        <section>
          <h2>Results</h2>
          {results.map((r) => (
            <div key={r.candidate_id} style={{ margin: '0.75rem 0' }}>
              {r.clip_url ? (
                <a href={r.clip_url} download>Download clip ({r.candidate_id})</a>
              ) : (
                <span>Clip {r.candidate_id}</span>
              )}
              {r.status === 'fallback' && (
                <div style={{ color: '#b45309', fontSize: '0.85rem' }}>
                  Fallback: {r.fallback_reason}
                </div>
              )}
            </div>
          ))}
          <button onClick={() => setResults(null)}>Back to candidates</button>
        </section>
      )}
    </main>
  )
}
```

- [ ] **Step 7: Install dependencies and verify the production build**

Run: `cd frontend && npm install && npm run build`
Expected: `npm install` completes, then `vite build` writes `frontend/dist/` with no errors.

- [ ] **Step 8: Manual end-to-end smoke run**

In one terminal: `cd backend && ../.venv/bin/uvicorn app.main:app --port 8000` (requires configured AWS/Bedrock credentials, since `/upload` runs real discovery). In another: `cd frontend && npm run dev`. Open `http://localhost:5173`, upload a small PPTX with a math problem, confirm candidates appear, select one, click "Render selected", and confirm a downloadable clip (or a labeled fallback reason) appears. This is a manual check — nothing to assert automatically.

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/vite.config.js frontend/index.html frontend/src/main.jsx frontend/src/App.jsx .gitignore
git commit -m "feat: add React upload, candidate-selection, and render UI"
```

---

## Self-Review Notes

- **Spec coverage:** every Week 2 in-scope item maps to a task — classification/grade-inference (Task 4), `process_scene` orchestrator owning classify→extract→validate→render (Task 5), retry/fallback policy distinguishing ambiguity from technical failure (Task 5 tests cover both, plus the classify-exception path), three new templates (Tasks 1-3, each with guard tests + a real-render smoke test), FastAPI `/upload`/`/render`/`/clips` with 50-slide cap and non-PPTX rejection (Task 7), in-memory session state keyed by cookie (Tasks 6-7), and the React upload→select→render UI (Task 8). Synchronous render is inherent in the blocking `/render` route (latency justified by the Week 1 benchmark).
- **Deliberate spec refinement:** `fraction_bar` uses an explicit shared integer `denominator` + integer numerators rather than `fractions.Fraction`, because `Fraction` auto-reduces and would break the same-denominator guard for the exact `1/4 + 2/4` case the spec requires it to accept. Documented in Task 2's interface block.
- **Placeholder scan:** no TBD/TODO markers; every code step shows complete code and every command has expected output. Task 8's build-only verification is called out explicitly as the one intentional non-TDD deliverable (no frontend test framework in Week 2 scope).
- **Type consistency:** `TemplateName` members (`TEXT_CARD`, `FRACTION_BAR`, `BALANCE_SCALE`) are added once per template task and referenced identically in registry, `process_scene`, and tests. `ClassificationResult`/`classify_candidate`, `process_scene`, `SessionStore` methods (`create`/`get`/`register_clip`/`get_clip`), and the route request/response models (`RenderRequest`, `ClipResult`, `clip_url`) use the same names across their producing and consuming tasks.
- **Out of scope (Week 3+, not gaps):** thumbnail preview, storyboard review/edit UI, grade override, approve/reject/retry controls, per-step captioning UI, Galeo auth, output-format customization, icon theming, parallel multi-clip render.
