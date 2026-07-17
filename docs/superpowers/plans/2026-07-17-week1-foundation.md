# Week 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the backend foundation for the K-8 Math Animation Generator: PPTX parsing/chunking, the storyboard data model, a chunked Bedrock candidate-discovery call, two hardcoded-param Manim templates, a full subprocess-isolated render producing a real MP4, a schema-scoped extraction call, and a wall-clock latency benchmark across 3 real scenes — plus the first eval fixtures. This is Week 1 of the 4-week MVP per `project description.md` Section 11 and the technical spec at `docs/superpowers/specs/2026-07-17-math-animation-generator-design.md`.

**Architecture:** Backend-only this week — no FastAPI routes or frontend yet (those are Week 2, once candidate selection UI and the classification/extraction pipeline wiring exist). Each pipeline stage (parsing, discovery, extraction, render) is a standalone, independently-testable Python module under `backend/app/`, composed later into routes. Templates are Manim `Scene` subclasses paired with a Pydantic params model and a separate guard function, matching the spec's per-template file layout.

**Tech Stack:** Python 3.11+, Pydantic v2, `python-pptx`, `manim` (Community Edition), `boto3` (Bedrock `converse` API with tool-use), `pytest`. No FastAPI/React work this week.

## Global Constraints

- Python 3.11+ throughout; all Pydantic models use Pydantic v2 syntax (`model_validate`, `model_dump`, `@model_validator(mode="after")`).
- The LLM never computes arithmetic — every computed value (running totals, comparisons) is computed in Python, never trusted from a Bedrock response.
- Every template has a Pydantic params model (`params.py`) and a separate compatibility guard function (`guard.py`) that the params model's validator calls — guards apply to any params instance regardless of where it came from (hardcoded, extracted, or later teacher-edited).
- Every Manim render runs in its own OS subprocess (never in-process) to avoid Manim's global `config` singleton bleeding state across renders.
- Input is PPTX only; parsing reads slide bodies and speaker notes (no OCR, no other formats).
- Bedrock calls use a single model tier (Claude Sonnet) via `boto3`'s `bedrock-runtime` `converse` API with schema-constrained tool calls (JSON Schema generated from the relevant Pydantic model via `model_json_schema()`).
- No hand-authored binary fixture files — PPTX test/eval fixtures are generated programmatically via `python-pptx`, never committed as opaque binaries edited by hand.
- Dependencies pinned with minimum versions in `backend/pyproject.toml`: `fastapi>=0.110`, `uvicorn[standard]>=0.29`, `pydantic>=2.6`, `pydantic-settings>=2.2`, `python-pptx>=0.6.23`, `manim>=0.18.1`, `boto3>=1.34`, dev-only `pytest>=8.0`.
- Every task's tests must pass before moving to the next task; commit after each task.

---

### Task 1: Backend Project Scaffolding

**Files:**
- Create: `.gitignore`
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/tests/__init__.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `get_settings() -> Settings` (module `app.config`), consumed by `app.pipeline.bedrock_client` in Task 5.

- [ ] **Step 1: Ignore local credential files before any are created**

```gitignore
# Local credentials and developer-specific configuration
.env
**/.env
```

This root `.gitignore` must be committed before a developer creates `backend/.env`; `.env.example` remains tracked because these rules match only files named exactly `.env`.

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "math-animation-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "python-pptx>=0.6.23",
    "manim>=0.18.1",
    "boto3>=1.34",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 3: Write `.env.example`**

```
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5-20250929-v1:0
```

- [ ] **Step 4: Create empty `app/__init__.py` and `tests/__init__.py`**

Both files are empty — they mark the directories as packages.

- [ ] **Step 5: Write the failing test for settings**

```python
# backend/tests/test_config.py
from app.config import get_settings


def test_settings_load_defaults():
    settings = get_settings()
    assert settings.aws_region == "us-east-1"
    assert "claude" in settings.bedrock_model_id.lower()
```

- [ ] **Step 6: Install deps and run test to verify it fails**

Run: `cd backend && pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 7: Write `app/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-sonnet-4-5-20250929-v1:0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests... actually 1 test, `test_settings_load_defaults`)

- [ ] **Step 9: Commit**

```bash
git add .gitignore backend/pyproject.toml backend/.env.example backend/app/__init__.py backend/app/config.py backend/tests/__init__.py backend/tests/test_config.py
git commit -m "chore: scaffold backend project with settings module"
```

---

### Task 2: Storyboard Data Model (Candidate, Scene, TemplateName)

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/candidate.py`
- Create: `backend/app/models/scene.py`
- Test: `backend/tests/models/__init__.py`
- Test: `backend/tests/models/test_models.py`

**Interfaces:**
- Produces: `Candidate` (module `app.models.candidate`), `Scene`, `TemplateName` (module `app.models.scene`) — consumed by `app.pipeline.discovery` (Task 5), `app.templates.registry` (Task 6/7), and `app.render.full_render` (Task 8).

- [ ] **Step 1: Create empty `app/models/__init__.py` and `tests/models/__init__.py`**

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/models/test_models.py
from fractions import Fraction

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName


def test_candidate_round_trips_through_json():
    candidate = Candidate(
        candidate_id="c1", source_excerpt="3 + 4", slide_index=2,
        one_line_summary="Detected: 3 + 4",
    )
    restored = Candidate.model_validate_json(candidate.model_dump_json())
    assert restored == candidate


def test_scene_defaults_to_pending_review():
    scene = Scene(scene_id="s1", grade_level=2)
    assert scene.status == "pending_review"
    assert scene.template is None
    assert scene.fallback_reason is None


def test_scene_accepts_a_template_name():
    scene = Scene(scene_id="s2", grade_level=3, template=TemplateName.NUMBER_LINE)
    assert scene.template == TemplateName.NUMBER_LINE


def test_scene_round_trip_retains_manual_source_and_stated_answer():
    scene = Scene(
        scene_id="s3",
        grade_level=4,
        manual_source_text="Three halves plus two halves equals five halves.",
        stated_answer=Fraction(5, 2),
    )

    restored = Scene.model_validate_json(scene.model_dump_json())

    assert restored.manual_source_text == scene.manual_source_text
    assert restored.stated_answer == Fraction(5, 2)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/models/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.candidate'`

- [ ] **Step 4: Write `app/models/candidate.py`**

```python
from pydantic import BaseModel


class Candidate(BaseModel):
    candidate_id: str
    source_excerpt: str
    slide_index: int
    one_line_summary: str
```

- [ ] **Step 5: Write `app/models/scene.py`**

```python
from fractions import Fraction
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class TemplateName(str, Enum):
    NUMBER_LINE = "number_line"
    ARRAY_GRID = "array_grid"


class Scene(BaseModel):
    scene_id: str
    candidate_id: str | None = None
    manual_source_text: str | None = None
    template: TemplateName | None = None
    grade_level: int
    grade_overridden: bool = False
    params: dict = Field(default_factory=dict)
    stated_answer: Fraction | None = None
    status: Literal["pending_review", "approved", "rejected", "fallback"] = "pending_review"
    fallback_reason: str | None = None
    thumbnail_path: Path | None = None
    render_path: Path | None = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/models/test_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/models backend/tests/models
git commit -m "feat: add Candidate, Scene, and TemplateName storyboard models"
```

---

### Task 3: PPTX Parsing and Chunking

**Files:**
- Create: `backend/app/pipeline/__init__.py`
- Create: `backend/app/pipeline/parsing.py`
- Test: `backend/tests/pipeline/__init__.py`
- Test: `backend/tests/pipeline/test_parsing.py`

**Interfaces:**
- Produces: `extract_slide_texts(pptx_path: Path) -> list[str]`, `chunk_slide_texts(slide_texts: list[str], chunk_size: int = 25) -> list[list[str]]` (module `app.pipeline.parsing`) — consumed by `app.pipeline.discovery` (Task 5).

- [ ] **Step 1: Create empty `app/pipeline/__init__.py` and `tests/pipeline/__init__.py`**

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/pipeline/test_parsing.py
from pptx import Presentation
from pptx.util import Inches


def _build_sample_pptx(path):
    presentation = Presentation()
    layout = presentation.slide_layouts[1]

    slide1 = presentation.slides.add_slide(layout)
    slide1.shapes.title.text = "Warm Up"
    slide1.placeholders[1].text = "Sarah has 4 apples and buys 3 more. How many now?"
    slide1.notes_slide.notes_text_frame.text = "Remind students this is simple addition."

    table = slide1.shapes.add_table(
        1, 1, Inches(1), Inches(4), Inches(4), Inches(1)
    ).table
    table.cell(0, 0).text = "Table problem: 6 groups of 4"

    group = slide1.shapes.add_group_shape()
    grouped_text = group.shapes.add_textbox(
        Inches(1), Inches(5), Inches(4), Inches(1)
    )
    grouped_text.text_frame.text = "Grouped problem: 9 minus 2"

    slide2 = presentation.slides.add_slide(layout)
    slide2.shapes.title.text = "Agenda"
    slide2.placeholders[1].text = "Standards: 3.OA.A.1"

    presentation.save(path)


def test_extract_slide_texts_includes_body_and_notes(tmp_path):
    from app.pipeline.parsing import extract_slide_texts

    pptx_path = tmp_path / "sample.pptx"
    _build_sample_pptx(pptx_path)

    texts = extract_slide_texts(pptx_path)

    assert len(texts) == 2
    assert "Sarah has 4 apples" in texts[0]
    assert "simple addition" in texts[0]
    assert "Table problem: 6 groups of 4" in texts[0]
    assert "Grouped problem: 9 minus 2" in texts[0]
    assert "3.OA.A.1" in texts[1]


def test_chunk_slide_texts_splits_at_chunk_size():
    from app.pipeline.parsing import chunk_slide_texts

    slide_texts = [f"slide {i}" for i in range(50)]

    chunks = chunk_slide_texts(slide_texts, chunk_size=25)

    assert len(chunks) == 2
    assert len(chunks[0]) == 25
    assert len(chunks[1]) == 25
    assert chunks[0][0] == "slide 0"
    assert chunks[1][0] == "slide 25"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/pipeline/test_parsing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.parsing'`

- [ ] **Step 4: Write `app/pipeline/parsing.py`**

```python
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


def _extract_shape_text(shape) -> list[str]:
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        return [
            text
            for child in shape.shapes
            for text in _extract_shape_text(child)
        ]
    if shape.has_table:
        return [cell.text for row in shape.table.rows for cell in row.cells]
    if shape.has_text_frame:
        return [shape.text_frame.text]
    return []


def extract_slide_texts(pptx_path: Path) -> list[str]:
    presentation = Presentation(pptx_path)
    texts = []
    for slide in presentation.slides:
        parts = []
        for shape in slide.shapes:
            parts.extend(_extract_shape_text(shape))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            parts.append(slide.notes_slide.notes_text_frame.text)
        texts.append("\n".join(p for p in parts if p.strip()))
    return texts


def chunk_slide_texts(slide_texts: list[str], chunk_size: int = 25) -> list[list[str]]:
    return [slide_texts[i:i + chunk_size] for i in range(0, len(slide_texts), chunk_size)]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/pipeline/test_parsing.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline backend/tests/pipeline
git commit -m "feat: add PPTX slide text extraction and chunking"
```

---

### Task 4: Two Template Params + Guards (Number Line, Array Grid)

**Files:**
- Create: `backend/app/templates/__init__.py`
- Create: `backend/app/templates/number_line/__init__.py`
- Create: `backend/app/templates/number_line/guard.py`
- Create: `backend/app/templates/number_line/params.py`
- Create: `backend/app/templates/array_grid/__init__.py`
- Create: `backend/app/templates/array_grid/guard.py`
- Create: `backend/app/templates/array_grid/params.py`
- Test: `backend/tests/templates/__init__.py`
- Test: `backend/tests/templates/test_number_line_guard.py`
- Test: `backend/tests/templates/test_array_grid_guard.py`

**Interfaces:**
- Produces: `NumberLineParams`, `NumberLineStep` (module `app.templates.number_line.params`); `ArrayGridParams` (module `app.templates.array_grid.params`) — consumed by `app.templates.registry` (Task 6), `app.pipeline.extraction` and `scripts/benchmark_latency.py` (Task 8/9).
- Number line params use plain `int` for `start`/`amount` this week (no fraction support yet — fractions are scoped to a later, dedicated fraction template per the product doc's component table, not this one).

- [ ] **Step 1: Create empty `__init__.py` files** for `app/templates`, `app/templates/number_line`, `app/templates/array_grid`, `tests/templates`

- [ ] **Step 2: Write the failing guard tests**

```python
# backend/tests/templates/test_number_line_guard.py
import pytest
from pydantic import ValidationError


def test_valid_steps_pass_the_guard():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    params = NumberLineParams(
        start=4,
        steps=[
            NumberLineStep(operation="add", amount=3),
            NumberLineStep(operation="subtract", amount=2),
        ],
    )
    assert params.start == 4


def test_running_total_going_negative_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=2,
            steps=[
                NumberLineStep(operation="subtract", amount=5),
                NumberLineStep(operation="add", amount=1),
            ],
        )


@pytest.mark.parametrize("step_count", [0, 1, 4])
def test_step_count_outside_two_to_three_is_rejected(step_count):
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    steps = [NumberLineStep(operation="add", amount=1) for _ in range(step_count)]
    with pytest.raises(ValidationError):
        NumberLineParams(start=2, steps=steps)


def test_non_positive_step_amount_is_rejected():
    from app.templates.number_line.params import NumberLineParams, NumberLineStep

    with pytest.raises(ValidationError):
        NumberLineParams(
            start=2,
            steps=[
                NumberLineStep(operation="add", amount=-3),
                NumberLineStep(operation="subtract", amount=1),
            ],
        )
```

```python
# backend/tests/templates/test_array_grid_guard.py
import pytest
from pydantic import ValidationError


def test_valid_grid_passes():
    from app.templates.array_grid.params import ArrayGridParams

    params = ArrayGridParams(rows=3, cols=4)
    assert params.rows == 3


def test_oversized_grid_is_rejected():
    from app.templates.array_grid.params import ArrayGridParams

    with pytest.raises(ValidationError):
        ArrayGridParams(rows=20, cols=20)


def test_non_positive_dimensions_are_rejected():
    from app.templates.array_grid.params import ArrayGridParams

    with pytest.raises(ValidationError):
        ArrayGridParams(rows=0, cols=4)


@pytest.mark.parametrize(("rows", "cols"), [(1, 13), (13, 1)])
def test_overlong_single_axis_is_rejected(rows, cols):
    from app.templates.array_grid.params import ArrayGridParams

    with pytest.raises(ValidationError):
        ArrayGridParams(rows=rows, cols=cols)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/templates -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write `app/templates/number_line/guard.py`**

```python
def check_number_line_compatibility(params) -> None:
    total = params.start
    for step in params.steps:
        total = total + step.amount if step.operation == "add" else total - step.amount
        if total < 0:
            raise ValueError(
                f"Number line running total went negative ({total}) — not valid for this template"
            )
```

- [ ] **Step 5: Write `app/templates/number_line/params.py`**

```python
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.templates.number_line.guard import check_number_line_compatibility


class NumberLineStep(BaseModel):
    operation: Literal["add", "subtract"]
    amount: int = Field(gt=0)


class NumberLineParams(BaseModel):
    start: int
    steps: list[NumberLineStep] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def _check_guard(self):
        check_number_line_compatibility(self)
        return self
```

- [ ] **Step 6: Write `app/templates/array_grid/guard.py`**

```python
def check_array_grid_compatibility(params) -> None:
    if params.rows <= 0 or params.cols <= 0:
        raise ValueError("Array grid rows and cols must be positive")
    if params.rows > 12 or params.cols > 12:
        raise ValueError(
            f"Array grid axis too long to fit the frame ({params.rows}x{params.cols}; max 12 per axis)"
        )
    if params.rows * params.cols > 144:
        raise ValueError(
            f"Array grid too large to render clearly ({params.rows}x{params.cols} > 144 cells)"
        )
```

- [ ] **Step 7: Write `app/templates/array_grid/params.py`**

```python
from pydantic import BaseModel, model_validator

from app.templates.array_grid.guard import check_array_grid_compatibility


class ArrayGridParams(BaseModel):
    rows: int
    cols: int

    @model_validator(mode="after")
    def _check_guard(self):
        check_array_grid_compatibility(self)
        return self
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/templates -v`
Expected: PASS (11 tests)

- [ ] **Step 9: Commit**

```bash
git add backend/app/templates backend/tests/templates
git commit -m "feat: add number_line and array_grid params with compatibility guards"
```

---

### Task 5: Manim Scenes + Template Registry

**Files:**
- Create: `backend/app/templates/number_line/scene.py`
- Create: `backend/app/templates/array_grid/scene.py`
- Create: `backend/app/templates/registry.py`
- Test: `backend/tests/templates/test_registry.py`

**Interfaces:**
- Consumes: `NumberLineParams` (Task 4), `ArrayGridParams` (Task 4), `TemplateName` (Task 2)
- Produces: `NumberLineScene`, `ArrayGridScene` (Manim `Scene` subclasses with a settable `.params` attribute); `get_template(name: TemplateName | str) -> tuple[type, type]` (module `app.templates.registry`) — consumed by `app.render.render_worker` (Task 6).

- [ ] **Step 1: Write `app/templates/number_line/scene.py`**

```python
from manim import *


class NumberLineScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("NumberLineScene.params must be set before construct() runs")

        total = self.params.start
        values = [total]
        for step in self.params.steps:
            total = total + step.amount if step.operation == "add" else total - step.amount
            values.append(total)

        low, high = min(values) - 2, max(values) + 2
        line = NumberLine(x_range=[low, high, 1], include_numbers=True)
        self.play(Create(line))

        marker = Dot(line.number_to_point(self.params.start), color=RED)
        label = Text(str(self.params.start)).next_to(marker, UP)
        self.play(FadeIn(marker), Write(label))

        running = self.params.start
        for step in self.params.steps:
            new_value = running + step.amount if step.operation == "add" else running - step.amount
            arrow = Arrow(
                line.number_to_point(running),
                line.number_to_point(new_value),
                buff=0,
                color=GREEN if step.operation == "add" else ORANGE,
            )
            self.play(Create(arrow))
            new_marker = Dot(line.number_to_point(new_value), color=RED)
            new_label = Text(str(new_value)).next_to(new_marker, UP)
            self.play(Transform(marker, new_marker), Transform(label, new_label))
            running = new_value

        self.wait(1)
```

- [ ] **Step 2: Write `app/templates/array_grid/scene.py`**

```python
from manim import *


class ArrayGridScene(Scene):
    params = None

    def construct(self):
        if self.params is None:
            raise ValueError("ArrayGridScene.params must be set before construct() runs")

        dots = VGroup()
        for r in range(self.params.rows):
            for c in range(self.params.cols):
                dot = Dot(radius=0.15, color=BLUE)
                dot.move_to([c * 0.6, -r * 0.6, 0])
                dots.add(dot)
        dots.move_to(ORIGIN)

        label = Text(f"{self.params.rows} x {self.params.cols}").to_edge(UP)

        self.play(Write(label))
        self.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.02))
        self.wait(1)
```

- [ ] **Step 3: Write the failing registry test**

```python
# backend/tests/templates/test_registry.py
def test_get_template_returns_scene_and_params_classes():
    from app.models.scene import TemplateName
    from app.templates.registry import get_template
    from app.templates.number_line.scene import NumberLineScene
    from app.templates.number_line.params import NumberLineParams

    scene_cls, params_cls = get_template(TemplateName.NUMBER_LINE)

    assert scene_cls is NumberLineScene
    assert params_cls is NumberLineParams


def test_get_template_accepts_a_plain_string():
    from app.templates.registry import get_template

    scene_cls, params_cls = get_template("array_grid")

    assert scene_cls.__name__ == "ArrayGridScene"
    assert params_cls.__name__ == "ArrayGridParams"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/templates/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.templates.registry'`

- [ ] **Step 5: Write `app/templates/registry.py`**

```python
from app.models.scene import TemplateName
from app.templates.array_grid.params import ArrayGridParams
from app.templates.array_grid.scene import ArrayGridScene
from app.templates.number_line.params import NumberLineParams
from app.templates.number_line.scene import NumberLineScene

_REGISTRY = {
    TemplateName.NUMBER_LINE: (NumberLineScene, NumberLineParams),
    TemplateName.ARRAY_GRID: (ArrayGridScene, ArrayGridParams),
}


def get_template(name: TemplateName | str) -> tuple[type, type]:
    key = TemplateName(name)
    return _REGISTRY[key]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/templates/test_registry.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/templates/number_line/scene.py backend/app/templates/array_grid/scene.py backend/app/templates/registry.py backend/tests/templates/test_registry.py
git commit -m "feat: add Manim scenes for number_line and array_grid, plus template registry"
```

---

### Task 6: Subprocess-Isolated Render (Full MP4 + Thumbnail)

**Files:**
- Create: `backend/app/render/__init__.py`
- Create: `backend/app/render/render_worker.py`
- Create: `backend/app/render/full_render.py`
- Test: `backend/tests/render/__init__.py`
- Test: `backend/tests/render/test_full_render.py`

**Interfaces:**
- Consumes: `get_template` (Task 5)
- Produces: `render_scene_to_mp4(template: TemplateName, params: BaseModel, output_path: Path) -> Path`, `render_scene_thumbnail(template: TemplateName, params: BaseModel, output_path: Path) -> Path` (module `app.render.full_render`) — consumed by `scripts/benchmark_latency.py` (Task 8) and, later, FastAPI render routes (Week 2).

**Prerequisite:** ffmpeg must be installed and on `PATH` (Manim shells out to it internally). Verify with `ffmpeg -version` before running this task's tests.

- [ ] **Step 1: Create empty `app/render/__init__.py` and `tests/render/__init__.py`**

- [ ] **Step 2: Write `app/render/render_worker.py`**

This is the subprocess entry point — each invocation gets its own fresh Python process, so Manim's global `config` singleton never bleeds between renders.

```python
import json
import sys
from pathlib import Path

from app.templates.registry import get_template


def main() -> None:
    template_name, params_json_path, output_path_str, mode = sys.argv[1:5]
    params_data = json.loads(Path(params_json_path).read_text())
    scene_cls, params_cls = get_template(template_name)
    params = params_cls.model_validate(params_data)

    from manim import tempconfig

    output_path = Path(output_path_str)
    output_path.unlink(missing_ok=True)
    overrides = {
        "media_dir": str(output_path.parent),
        "output_file": output_path.stem,
        "disable_caching": True,
    }
    if mode == "thumbnail":
        overrides["save_last_frame"] = True
        overrides["quality"] = "low_quality"
    else:
        overrides["quality"] = "medium_quality"

    with tempconfig(overrides):
        scene = scene_cls()
        scene.params = params
        scene.render()

    ext = "png" if mode == "thumbnail" else "mp4"
    matches = [
        path
        for path in output_path.parent.rglob(f"{output_path.stem}.{ext}")
        if path != output_path
    ]
    if not matches:
        raise RuntimeError(f"Manim did not produce the expected {ext} file for {output_path.stem}")
    matches[0].replace(output_path)


if __name__ == "__main__":
    main()
```

*Why the unlink and filtered `rglob` lookup:* Manim nests output under its own `videos/<scene>/<quality>/` (or `images/...`) folder structure inside `media_dir`, and the exact nesting has varied across Manim versions — searching for the expected filename and moving it to the caller's exact `output_path` avoids hardcoding a folder structure that could shift. Removing the old destination before rendering and excluding it from discovery guarantees a thumbnail re-render or benchmark rerun cannot select stale output instead of Manim's newly generated artifact.

- [ ] **Step 3: Write `app/render/full_render.py`**

```python
import json
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

from app.models.scene import TemplateName


def render_scene_to_mp4(template: TemplateName, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="full")


def render_scene_thumbnail(template: TemplateName, params: BaseModel, output_path: Path) -> Path:
    return _run_render_worker(template, params, output_path, mode="thumbnail")


def _run_render_worker(template: TemplateName, params: BaseModel, output_path: Path, mode: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    params_json_path = output_path.with_suffix(".params.json")
    params_json_path.write_text(json.dumps(params.model_dump(mode="json")))

    result = subprocess.run(
        [
            sys.executable, "-m", "app.render.render_worker",
            template.value, str(params_json_path), str(output_path), mode,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Render subprocess failed:\n{result.stdout}\n{result.stderr}")
    return output_path
```

- [ ] **Step 4: Write the test (this test actually invokes Manim + ffmpeg — expect it to take several seconds)**

```python
# backend/tests/render/test_full_render.py
from app.models.scene import TemplateName
from app.render.full_render import render_scene_to_mp4
from app.templates.number_line.params import NumberLineParams, NumberLineStep


def test_render_number_line_scene_produces_mp4(tmp_path):
    params = NumberLineParams(
        start=2,
        steps=[
            NumberLineStep(operation="add", amount=3),
            NumberLineStep(operation="subtract", amount=1),
        ],
    )
    output_path = tmp_path / "scene.mp4"
    output_path.write_bytes(b"stale destination")

    result_path = render_scene_to_mp4(TemplateName.NUMBER_LINE, params, output_path)

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
    assert output_path.read_bytes() != b"stale destination"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/render/test_full_render.py -v -s`
Expected: PASS (1 test; several seconds of Manim/ffmpeg output printed to stdout is normal)

- [ ] **Step 6: Commit**

```bash
git add backend/app/render backend/tests/render
git commit -m "feat: add subprocess-isolated Manim render producing MP4 and thumbnail output"
```

---

### Task 7: Schema-Scoped Extraction Call (Bedrock)

**Files:**
- Create: `backend/app/pipeline/bedrock_client.py`
- Create: `backend/app/pipeline/extraction.py`
- Test: `backend/tests/pipeline/test_extraction.py`

**Interfaces:**
- Consumes: `get_settings` (Task 1), `NumberLineParams` (Task 4)
- Produces: `call_with_tool(system_prompt: str, user_message: str, tool_name: str, tool_schema: dict) -> dict` (module `app.pipeline.bedrock_client`); `extract_params(source_text: str, params_cls: Type[T]) -> T` (module `app.pipeline.extraction`) — consumed by `app.pipeline.discovery` (Task 8) and `scripts/benchmark_latency.py` (Task 9).

- [ ] **Step 1: Write `app/pipeline/bedrock_client.py`**

```python
from functools import lru_cache

import boto3

from app.config import get_settings


@lru_cache
def get_bedrock_client():
    settings = get_settings()
    return boto3.client("bedrock-runtime", region_name=settings.aws_region)


def call_with_tool(system_prompt: str, user_message: str, tool_name: str, tool_schema: dict) -> dict:
    settings = get_settings()
    client = get_bedrock_client()
    response = client.converse(
        modelId=settings.bedrock_model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        toolConfig={
            "tools": [{"toolSpec": {"name": tool_name, "inputSchema": {"json": tool_schema}}}],
            "toolChoice": {"tool": {"name": tool_name}},
        },
    )
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise RuntimeError("Bedrock response did not include a tool call")
```

- [ ] **Step 2: Write the failing extraction test (Bedrock mocked)**

```python
# backend/tests/pipeline/test_extraction.py
from unittest.mock import patch


@patch("app.pipeline.extraction.call_with_tool")
def test_extract_params_validates_against_the_template_schema(mock_call):
    from app.pipeline.extraction import extract_params
    from app.templates.number_line.params import NumberLineParams

    mock_call.return_value = {
        "start": 4,
        "steps": [
            {"operation": "add", "amount": 3},
            {"operation": "subtract", "amount": 2},
        ],
    }

    params = extract_params(
        "Sarah has 4 apples, buys 3 more, then gives 2 away.", NumberLineParams
    )

    assert isinstance(params, NumberLineParams)
    assert params.start == 4
    assert params.steps[0].amount == 3
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/pipeline/test_extraction.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.extraction'`

- [ ] **Step 4: Write `app/pipeline/extraction.py`**

```python
from typing import Type, TypeVar

from pydantic import BaseModel

from app.pipeline.bedrock_client import call_with_tool

T = TypeVar("T", bound=BaseModel)

_EXTRACTION_SYSTEM_PROMPT = (
    "Extract only the numbers and operations needed to fill in the given schema. "
    "Never compute or state a final answer — only report the operation type and "
    "operands exactly as they appear in the text."
)


def extract_params(source_text: str, params_cls: Type[T]) -> T:
    schema = params_cls.model_json_schema()
    result = call_with_tool(
        system_prompt=_EXTRACTION_SYSTEM_PROMPT,
        user_message=source_text,
        tool_name="report_params",
        tool_schema=schema,
    )
    return params_cls.model_validate(result)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/pipeline/test_extraction.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/bedrock_client.py backend/app/pipeline/extraction.py backend/tests/pipeline/test_extraction.py
git commit -m "feat: add schema-scoped Bedrock extraction call"
```

---

### Task 8: Chunked Candidate Discovery (Bedrock)

**Files:**
- Create: `backend/app/pipeline/discovery.py`
- Test: `backend/tests/pipeline/test_discovery.py`

**Interfaces:**
- Consumes: `call_with_tool` (Task 7), `Candidate` (Task 2), `chunk_slide_texts` (Task 3)
- Produces: `discover_candidates(slide_texts: list[str], slide_offset: int = 0) -> list[Candidate]`, `discover_candidates_for_document(slide_texts: list[str], chunk_size: int = 25) -> list[Candidate]` (module `app.pipeline.discovery`) — consumed by `eval/run_eval.py` (Task 10) and, later, the `/upload` route (Week 2).

- [ ] **Step 1: Write the failing discovery tests**

```python
# backend/tests/pipeline/test_discovery.py
from unittest.mock import call, patch


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_wraps_bedrock_response_into_candidates(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = {
        "candidates": [
            {"source_excerpt": "4 + 3", "slide_index": 25, "one_line_summary": "Detected: 4 + 3"},
        ]
    }

    candidates = discover_candidates(["slide 25 text"], slide_offset=25)

    assert len(candidates) == 1
    assert candidates[0].source_excerpt == "4 + 3"
    assert candidates[0].slide_index == 25
    assert candidates[0].candidate_id
    assert "[slide 25] slide 25 text" in mock_call.call_args.kwargs["user_message"]


@patch("app.pipeline.discovery.discover_candidates")
def test_discover_candidates_for_document_merges_across_chunks(mock_discover):
    from app.models.candidate import Candidate
    from app.pipeline.discovery import discover_candidates_for_document

    mock_discover.side_effect = [
        [Candidate(candidate_id="a", source_excerpt="x", slide_index=0, one_line_summary="x")],
        [Candidate(candidate_id="b", source_excerpt="y", slide_index=25, one_line_summary="y")],
    ]
    slide_texts = [f"slide {i}" for i in range(50)]

    candidates = discover_candidates_for_document(slide_texts, chunk_size=25)

    assert mock_discover.call_count == 2
    assert mock_discover.call_args_list == [
        call(slide_texts[:25], slide_offset=0),
        call(slide_texts[25:], slide_offset=25),
    ]
    assert [c.candidate_id for c in candidates] == ["a", "b"]
    assert [c.slide_index for c in candidates] == [0, 25]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/pipeline/test_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.discovery'`

- [ ] **Step 3: Write `app/pipeline/discovery.py`**

```python
from uuid import uuid4

from pydantic import BaseModel

from app.models.candidate import Candidate
from app.pipeline.bedrock_client import call_with_tool
from app.pipeline.parsing import chunk_slide_texts

_DISCOVERY_SYSTEM_PROMPT = (
    "You find candidate K-8 math example problems in slide text. Only flag text that "
    "states a concrete solvable math problem with numbers — ignore dates, page numbers, "
    "standards codes (e.g. 3.OA.A.1), and student counts that are not part of a math problem."
)


class _DiscoveredItem(BaseModel):
    source_excerpt: str
    slide_index: int
    one_line_summary: str


class _DiscoveryResult(BaseModel):
    candidates: list[_DiscoveredItem]


def discover_candidates(slide_texts: list[str], slide_offset: int = 0) -> list[Candidate]:
    numbered = "\n".join(
        f"[slide {i}] {text}"
        for i, text in enumerate(slide_texts, start=slide_offset)
    )
    schema = _DiscoveryResult.model_json_schema()
    result = call_with_tool(
        system_prompt=_DISCOVERY_SYSTEM_PROMPT,
        user_message=numbered,
        tool_name="report_candidates",
        tool_schema=schema,
    )
    parsed = _DiscoveryResult.model_validate(result)
    return [
        Candidate(
            candidate_id=str(uuid4()),
            source_excerpt=item.source_excerpt,
            slide_index=item.slide_index,
            one_line_summary=item.one_line_summary,
        )
        for item in parsed.candidates
    ]


def discover_candidates_for_document(slide_texts: list[str], chunk_size: int = 25) -> list[Candidate]:
    all_candidates: list[Candidate] = []
    for chunk_index, chunk in enumerate(chunk_slide_texts(slide_texts, chunk_size=chunk_size)):
        slide_offset = chunk_index * chunk_size
        all_candidates.extend(discover_candidates(chunk, slide_offset=slide_offset))
    return all_candidates
```

*Note on `candidate_id`:* generated locally with `uuid4()`, never trusted from the Bedrock response — the model isn't asked for an ID at all, only `source_excerpt`/`slide_index`/`one_line_summary`, keeping it out of the business of inventing identifiers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/pipeline/test_discovery.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/discovery.py backend/tests/pipeline/test_discovery.py
git commit -m "feat: add chunked candidate discovery with cross-chunk merge"
```

---

### Task 9: Latency Benchmark (Real Bedrock + Manim, 3 Scenes)

**Files:**
- Create: `backend/scripts/benchmark_latency.py`
- Create: `docs/latency-benchmark-week1.md` (results, filled in by hand after running the script)

**Interfaces:**
- Consumes: `extract_params` (Task 7), `render_scene_to_mp4` (Task 6), `NumberLineParams` (Task 4)

This task has no automated test — it's a manual measurement run against real Bedrock and real Manim, per the product doc's Week 1 requirement to "measure and record wall-clock duration for the full pipeline... on three real Manim scenes" before more templates are built on top.

- [ ] **Step 1: Write `backend/scripts/benchmark_latency.py`**

```python
import time
from pathlib import Path

from app.models.scene import TemplateName
from app.pipeline.extraction import extract_params
from app.render.full_render import render_scene_to_mp4
from app.templates.number_line.params import NumberLineParams

SCENES = [
    "Start at 4 apples, add 3 more apples, then give away 1 apple.",
    "Start at 10 stickers, give away 4 stickers, then receive 2 stickers.",
    "Start at 7 points, add 5 points, then subtract 2 points.",
]


def main():
    output_dir = Path(__file__).parent / "_benchmark_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, source_text in enumerate(SCENES):
        t0 = time.perf_counter()
        params = extract_params(source_text, NumberLineParams)
        t1 = time.perf_counter()
        render_scene_to_mp4(TemplateName.NUMBER_LINE, params, output_dir / f"scene_{i}.mp4")
        t2 = time.perf_counter()

        results.append({
            "scene": source_text,
            "extraction_seconds": round(t1 - t0, 2),
            "render_seconds": round(t2 - t1, 2),
            "total_seconds": round(t2 - t0, 2),
        })

    for r in results:
        print(r)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Confirm AWS credentials and Bedrock model access are configured**

Run: `aws sts get-caller-identity`
Expected: returns your AWS account identity (not an error) — confirms credentials are usable before spending a real Bedrock call.

- [ ] **Step 3: Run the benchmark**

Run: `cd backend && python scripts/benchmark_latency.py`
Expected: prints 3 dicts, one per scene, each with `extraction_seconds`, `render_seconds`, `total_seconds`.

- [ ] **Step 4: Record the results**

Create `docs/latency-benchmark-week1.md` and paste in the 3 printed result dicts plus one sentence noting whether `total_seconds` per scene feels acceptable for the synchronous, blocking-request-plus-spinner UX decided in the spec (Section 2, Progress UX) — if any scene's total is high enough (tens of seconds) to make a blocking HTTP call impractical, flag it now rather than in Week 4.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/benchmark_latency.py docs/latency-benchmark-week1.md
git commit -m "chore: add Week 1 latency benchmark and record results"
```

---

### Task 10: Begin the Eval Set (Zero-Candidate, Distractor-Heavy, Ambiguous-Phrasing)

**Files:**
- Create: `eval/generate_fixtures.py`
- Create: `eval/run_eval.py`
- Create: `docs/eval-results-week1.md` (results, filled in by hand)

**Interfaces:**
- Consumes: `extract_slide_texts` (Task 3), `discover_candidates_for_document` (Task 8)

No automated pass/fail assertions here — discovery quality needs a human judgment call (per the spec's Section 9 on the eval harness), not a string-match test.

- [ ] **Step 1: Write `eval/generate_fixtures.py`**

```python
from pathlib import Path

from pptx import Presentation

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _new_presentation():
    presentation = Presentation()
    return presentation, presentation.slide_layouts[1]


def build_zero_candidate_deck(path: Path) -> None:
    presentation, layout = _new_presentation()

    slide1 = presentation.slides.add_slide(layout)
    slide1.shapes.title.text = "Welcome"
    slide1.placeholders[1].text = "Chapter 4: Fractions Overview"

    slide2 = presentation.slides.add_slide(layout)
    slide2.shapes.title.text = "Agenda"
    slide2.placeholders[1].text = "Standards: 3.OA.A.1\nHomework due Friday"

    presentation.save(path)


def build_distractor_heavy_deck(path: Path) -> None:
    presentation, layout = _new_presentation()

    slide = presentation.slides.add_slide(layout)
    slide.shapes.title.text = "Warm Up"
    slide.placeholders[1].text = (
        "Date: 3/14. Standard 3.OA.A.1. Page 42.\n"
        "Sarah has 4 apples and buys 3 more apples. How many apples does she have now?"
    )

    presentation.save(path)


def build_ambiguous_phrasing_deck(path: Path) -> None:
    presentation, layout = _new_presentation()

    slide = presentation.slides.add_slide(layout)
    slide.shapes.title.text = "Think About It"
    slide.placeholders[1].text = (
        "There are some red apples and some green apples. There are 4 more red "
        "apples than green apples. How many apples are there in all?"
    )

    presentation.save(path)


def main():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    build_zero_candidate_deck(FIXTURES_DIR / "zero_candidate_deck.pptx")
    build_distractor_heavy_deck(FIXTURES_DIR / "distractor_heavy_deck.pptx")
    build_ambiguous_phrasing_deck(FIXTURES_DIR / "ambiguous_phrasing_deck.pptx")
    print(f"Wrote fixtures to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `eval/run_eval.py`**

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.pipeline.discovery import discover_candidates_for_document
from app.pipeline.parsing import extract_slide_texts

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def run_fixture(pptx_path: Path) -> dict:
    slide_texts = extract_slide_texts(pptx_path)
    candidates = discover_candidates_for_document(slide_texts)
    return {
        "fixture": pptx_path.name,
        "candidate_count": len(candidates),
        "candidates": [c.model_dump() for c in candidates],
    }


def main():
    report = [run_fixture(p) for p in sorted(FIXTURES_DIR.glob("*.pptx"))]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Generate the fixture decks**

Run: `cd eval && python generate_fixtures.py`
Expected: `Wrote fixtures to .../eval/fixtures`, and 3 `.pptx` files now exist in `eval/fixtures/`.

- [ ] **Step 4: Run discovery against the fixtures**

Run: `python run_eval.py`
Expected: a JSON report printed for all 3 fixtures.

- [ ] **Step 5: Hand-review the report and record results**

Create `docs/eval-results-week1.md`. For each fixture, note whether the result matches expectations:
- `zero_candidate_deck.pptx` should report `candidate_count: 0`
- `distractor_heavy_deck.pptx` should report exactly 1 candidate, whose `source_excerpt`/`one_line_summary` reflect the apples problem and do **not** mention "3/14", "3.OA.A.1", or "42"
- `ambiguous_phrasing_deck.pptx` — note whether discovery flags it as a candidate at all, and if so, whether the summary shows any sign of misreading the ambiguous role of "4 more" (this fixture is for observing model behavior now, not asserting a specific outcome — classification-ambiguity handling isn't wired until Week 2)

If any result doesn't match, note it as a known issue to revisit — this is exactly the kind of finding the eval set exists to catch early per the product doc's risk mitigations.

- [ ] **Step 6: Commit**

```bash
git add eval/generate_fixtures.py eval/run_eval.py docs/eval-results-week1.md
git commit -m "chore: add Week 1 eval fixtures and discovery eval harness"
```

---

## Self-Review Notes

- **Spec coverage:** every Week 1 bullet from `project description.md` Section 11 has a task — taxonomy/schema lock (Task 2, taxonomy itself already fixed by the product doc's Section 6 component table), PPTX parsing + chunking (Task 3), 2 templates with hardcoded params (Task 4/5), one full render end-to-end (Task 6), latency benchmark on 3 real scenes (Task 9, depends on Task 6+7), and beginning the eval set across all three required categories — zero-candidate, distractor-heavy, ambiguous-phrasing (Task 10).
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code and an exact command with expected output.
- **Type consistency:** `TemplateName`, `NumberLineParams`/`NumberLineStep`, `ArrayGridParams`, and `Candidate` are defined once (Tasks 2 and 4) and referenced identically by name in every later task that consumes them.
- **Deferred to Week 2 (not gaps — out of this week's stated scope):** FastAPI routes, `SessionState`/session cookie wiring, classification-and-grade-inference call, retry/fallback control flow, and the candidate-selection UI.
