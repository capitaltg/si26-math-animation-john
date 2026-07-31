# Meta-template Rendered Values and Geometry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make generated meta-templates render evaluated parameter values and answers, and give rectangle problems a proportional rectangle visual with evaluated dimension annotations.

**Architecture:** Add version 2 to the closed animation DSL with two producing nodes: `expression_label` for safe numeric expression output and `rectangle` for bounded proportional geometry. Keep version 1 as a legacy read path, enforce version 2 invariants during draft compilation and generation, and use the existing expression evaluator and Manim rendering pipeline rather than adding string interpolation.

**Tech Stack:** Python 3.11+, Pydantic 2, Manim, pytest, FastAPI integration tests

## Global Constraints

- Existing version 1 animation documents and published versions remain loadable.
- New generated and refined proposals must use `animation_version: 2`.
- Static text is never evaluated or interpolated.
- A version 2 animation must visibly contain an answer-role expression identical to `answer_expression`.
- Rectangle dimensions use the existing bounded expression evaluator and must evaluate positive.
- Existing `grid`, `tally_marks`, and `object_set` primitives remain available.
- Existing approved database rows and artifacts are not mutated.
- No arbitrary Python expressions, LaTeX input, or general-purpose interpolation is introduced.

---

## File structure

- `backend/app/meta/dsl/animation.py`: defines animation versions and nodes, compiles node expressions, rejects placeholder text, and records visible answer expressions.
- `backend/app/meta/dynamic_scene.py`: evaluates expression-label and rectangle fields and dispatches to visual builders.
- `backend/app/meta/manim_primitives/visuals.py`: formats bounded numeric results and constructs the annotated rectangle.
- `backend/app/meta/validation.py`: binds a version 2 visible answer node to the draft's authoritative answer expression.
- `backend/app/meta/draft_generation.py`: requires generated proposals to use version 2 and gives the model semantic visual guidance.
- `backend/tests/meta/dsl/test_animation_schema.py`: covers version 2 schema parsing and field bounds.
- `backend/tests/meta/dsl/test_animation_compile.py`: covers version compatibility, field validation, placeholder rejection, and visible-answer metadata.
- `backend/tests/meta/test_dynamic_scene.py`: covers evaluated text rendering and rectangle dispatch.
- `backend/tests/meta/manim_primitives/test_visual_primitives.py`: covers annotated rectangle geometry and numeric formatting.
- `backend/tests/meta/test_validation.py`: covers the visible-answer invariant.
- `backend/tests/meta/test_draft_generation.py`: covers the version 2 generation boundary.
- `backend/tests/meta/test_demo_end_to_end.py`: replaces the defective perimeter proposal with the corrected contract and verifies real rendered mobject text.
- `docs/meta-template-demo.md`: updates demo checkpoints and reset guidance for the new version.

### Task 1: Animation DSL version 2 and compile-time text safety

**Files:**
- Modify: `backend/tests/meta/dsl/test_animation_schema.py`
- Modify: `backend/tests/meta/dsl/test_animation_compile.py`
- Modify: `backend/app/meta/dsl/animation.py`

**Interfaces:**
- Consumes: existing `ExpressionNode`, `compile_expression`, `DslValidationError`, and shared layout traversal.
- Produces: `ExpressionLabelNode`, `RectangleNode`, `AnimationDocument.animation_version: Literal[1, 2]`, and `CompiledAnimation.answer_expressions: tuple[ExpressionNode, ...]`.

- [ ] **Step 1: Write failing schema tests for the two version 2 nodes**

Add imports for `ExpressionLabelNode`, `RectangleNode`, and `FieldRefNode`, then add:

```python
def test_expression_label_schema_accepts_bounded_dynamic_text():
    node = ExpressionLabelNode(
        ref="answer",
        expression=FieldRefNode(field="n"),
        prefix="= ",
        suffix=" cm",
        role="answer",
        style="success",
    )
    assert node.kind == "expression_label"
    assert node.role == "answer"


def test_rectangle_schema_accepts_expression_dimensions():
    node = RectangleNode(
        ref="diagram",
        length=FieldRefNode(field="length"),
        width=FieldRefNode(field="width"),
        unit="cm",
    )
    assert node.kind == "rectangle"
    assert node.unit == "cm"
```

- [ ] **Step 2: Run the schema tests and verify they fail for missing node classes**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/dsl/test_animation_schema.py::test_expression_label_schema_accepts_bounded_dynamic_text \
  tests/meta/dsl/test_animation_schema.py::test_rectangle_schema_accepts_expression_dimensions -v
```

Expected: collection fails because `ExpressionLabelNode` and `RectangleNode` do not exist.

- [ ] **Step 3: Add the minimal version 2 node models**

In `animation.py`, add:

```python
class ExpressionLabelNode(_AnimationNodeBase):
    kind: Literal["expression_label"] = "expression_label"
    expression: ExpressionNode
    prefix: str = Field(default="", max_length=MAX_LABEL_TEXT_LENGTH)
    suffix: str = Field(default="", max_length=MAX_LABEL_TEXT_LENGTH)
    role: Literal["working", "answer"] = "working"
    style: StyleToken = "primary"


class RectangleNode(_AnimationNodeBase):
    kind: Literal["rectangle"] = "rectangle"
    length: ExpressionNode
    width: ExpressionNode
    unit: str = Field(default="", max_length=MAX_LABEL_TEXT_LENGTH)
    style: StyleToken = "primary"
```

Add both classes to `AnimationNode`, allow `AnimationDocument.animation_version` values 1 and 2, add their expression fields to `_VISUAL_EXPRESSION_FIELDS`, and add both kinds to `_PRODUCING_KINDS`.

- [ ] **Step 4: Run the schema tests and verify they pass**

Run:

```bash
cd backend
../.venv/bin/pytest tests/meta/dsl/test_animation_schema.py -v
```

Expected: all animation schema tests pass.

- [ ] **Step 5: Write failing compiler tests for versioning, fields, placeholders, and answer metadata**

Add imports for the new nodes and these tests:

```python
def test_version_one_static_document_remains_loadable():
    document = AnimationDocument(
        animation_version=1,
        root=LabelNode(ref="caption", text="{legacy_value}"),
    )
    compiled = compile_animation_document(document, known_fields=frozenset({"legacy_value"}))
    assert compiled.refs == {"caption"}
    assert compiled.answer_expressions == ()


def test_version_one_rejects_version_two_visual_nodes():
    document = AnimationDocument(
        animation_version=1,
        root=ExpressionLabelNode(
            expression=FieldRefNode(field="n"),
            role="answer",
        ),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset({"n"}))
    assert exc.value.code == "unsupported_node_for_version"


def test_version_two_compiles_expression_fields_and_records_answer_expression():
    answer = FieldRefNode(field="n")
    document = AnimationDocument(
        animation_version=2,
        root=ColumnNode(
            children=[
                ExpressionLabelNode(expression=FieldRefNode(field="n"), prefix="Value: "),
                ExpressionLabelNode(expression=answer, prefix="Answer: ", role="answer"),
            ]
        ),
    )
    compiled = compile_animation_document(document, known_fields=frozenset({"n"}))
    assert compiled.answer_expressions == (answer,)


def test_version_two_expression_label_rejects_unknown_field():
    document = AnimationDocument(
        animation_version=2,
        root=ExpressionLabelNode(expression=FieldRefNode(field="missing")),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset({"n"}))
    assert exc.value.code == "unknown_field"


def test_version_two_rejects_static_field_placeholder():
    document = AnimationDocument(
        animation_version=2,
        root=LabelNode(text="{length} cm"),
    )
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset({"length"}))
    assert exc.value.code == "unsupported_text_placeholder"


def test_version_two_allows_literal_set_notation_without_field_names():
    document = AnimationDocument(
        animation_version=2,
        root=LabelNode(text="Set {2, 4, 6}"),
    )
    compile_animation_document(document, known_fields=frozenset({"length"}))
```

- [ ] **Step 6: Run the new compiler tests and verify the expected failures**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/dsl/test_animation_compile.py::test_version_one_static_document_remains_loadable \
  tests/meta/dsl/test_animation_compile.py::test_version_one_rejects_version_two_visual_nodes \
  tests/meta/dsl/test_animation_compile.py::test_version_two_compiles_expression_fields_and_records_answer_expression \
  tests/meta/dsl/test_animation_compile.py::test_version_two_expression_label_rejects_unknown_field \
  tests/meta/dsl/test_animation_compile.py::test_version_two_rejects_static_field_placeholder \
  tests/meta/dsl/test_animation_compile.py::test_version_two_allows_literal_set_notation_without_field_names -v
```

Expected: tests fail because version-specific validation, answer metadata, and placeholder checks are absent.

- [ ] **Step 7: Implement version-specific compiler behavior**

Add `answer_expressions` to `CompiledAnimation`:

```python
@dataclass(frozen=True)
class CompiledAnimation:
    document: AnimationDocument
    refs: frozenset[str]
    total_duration_seconds: float
    answer_expressions: tuple[ExpressionNode, ...] = ()
```

During `compile_animation_document`, collect answer-role expressions, reject
`expression_label` and `rectangle` in version 1 with
`unsupported_node_for_version`, and compile their expression fields through the
existing `_VISUAL_EXPRESSION_FIELDS` loop.

Add a helper that scans each brace-delimited fragment in version 2 static text
and returns true only when the fragment contains a whole-word known field:

```python
def _contains_field_placeholder(text: str, known_fields: frozenset[str]) -> bool:
    for fragment in re.findall(r"\{([^{}]+)\}", text):
        if any(re.search(rf"\b{re.escape(field)}\b", fragment) for field in known_fields):
            return True
    return False
```

Apply it to `LabelNode.text` and `ExpressionLabelNode.prefix`/`suffix`, raising:

```python
raise DslValidationError(
    "unsupported_text_placeholder",
    "static text cannot interpolate fields; use expression_label",
)
```

Return collected answer expressions in source traversal order.

- [ ] **Step 8: Run the focused DSL tests**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/dsl/test_animation_schema.py \
  tests/meta/dsl/test_animation_compile.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit the animation DSL contract**

```bash
git add backend/app/meta/dsl/animation.py \
  backend/tests/meta/dsl/test_animation_schema.py \
  backend/tests/meta/dsl/test_animation_compile.py
git commit -m "feat: add evaluated meta animation nodes"
```

### Task 2: Evaluated labels and annotated rectangle rendering

**Files:**
- Modify: `backend/tests/meta/manim_primitives/test_visual_primitives.py`
- Modify: `backend/tests/meta/test_dynamic_scene.py`
- Modify: `backend/app/meta/manim_primitives/visuals.py`
- Modify: `backend/app/meta/dynamic_scene.py`

**Interfaces:**
- Consumes: `fractions.Fraction`, existing expression `_evaluate`, `resolve_style`, and Manim visual/layout objects.
- Produces: `format_expression_value(value: Fraction) -> str` and `build_rectangle(length: Fraction, width: Fraction, unit: str = "", style: str = "primary") -> VGroup`.

- [ ] **Step 1: Write failing primitive tests for formatting and rectangle geometry**

Import `Fraction`, Manim `Rectangle`, the new formatter, and builder. Add:

```python
def test_format_expression_value_preserves_integer_and_fraction():
    assert format_expression_value(Fraction(22, 1)) == "22"
    assert format_expression_value(Fraction(3, 4)) == "3/4"


def test_build_rectangle_preserves_ratio_and_labels_dimensions():
    group = build_rectangle(Fraction(8), Fraction(3), unit="cm")
    shapes = [m for m in group.submobjects if isinstance(m, Rectangle)]
    texts = [m.original_text for m in group.submobjects if isinstance(m, Text)]
    assert len(shapes) == 1
    assert shapes[0].width / shapes[0].height == pytest.approx(8 / 3, rel=0.02)
    assert "8 cm" in texts
    assert "3 cm" in texts


@pytest.mark.parametrize(
    ("length", "width"),
    [(Fraction(0), Fraction(3)), (Fraction(8), Fraction(-1))],
)
def test_build_rectangle_rejects_non_positive_dimensions(length, width):
    with pytest.raises(ValueError, match="positive"):
        build_rectangle(length, width)
```

- [ ] **Step 2: Run the primitive tests and verify missing-symbol failures**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/manim_primitives/test_visual_primitives.py::test_format_expression_value_preserves_integer_and_fraction \
  tests/meta/manim_primitives/test_visual_primitives.py::test_build_rectangle_preserves_ratio_and_labels_dimensions \
  tests/meta/manim_primitives/test_visual_primitives.py::test_build_rectangle_rejects_non_positive_dimensions -v
```

Expected: collection fails because the formatter and rectangle builder do not exist.

- [ ] **Step 3: Implement bounded annotated rectangle construction**

In `visuals.py`, import `Fraction`, `Rectangle`, `LEFT`, and `DOWN`. Implement
`format_expression_value` with integer-or-fraction output. Implement
`build_rectangle` by:

1. Rejecting non-positive dimensions.
2. Computing a display ratio clamped to `[0.25, 4.0]`.
3. Fitting the rectangle inside width `5.5` and height `3.0`.
4. Creating one styled `Rectangle`.
5. Adding a bottom brace labeled with the true length and a left brace labeled
   with the true width.
6. Returning a `VGroup` containing the rectangle, both braces, and both labels,
   followed by the existing `fit_width` safety call.

Use:

```python
def _dimension_text(value: Fraction, unit: str) -> str:
    return " ".join(part for part in (format_expression_value(value), unit) if part)
```

The labels use actual values even when an extreme aspect ratio is clamped.

- [ ] **Step 4: Run primitive tests and verify they pass**

Run:

```bash
cd backend
../.venv/bin/pytest tests/meta/manim_primitives/test_visual_primitives.py -v
```

Expected: all visual primitive tests pass.

- [ ] **Step 5: Write failing dynamic renderer tests for evaluated output**

Import `ExpressionLabelNode`, `RectangleNode`, and `Text`. Add:

```python
def test_render_expression_label_displays_evaluated_integer():
    node = ExpressionLabelNode(
        ref="answer",
        expression=FieldRefNode(field="n"),
        prefix="Answer: ",
        suffix=" cm",
        role="answer",
    )
    mobjects = {}
    render_animation_node(_StubScene(), node, {"n": 22}, mobjects)
    assert isinstance(mobjects["answer"], Text)
    assert mobjects["answer"].original_text == "Answer: 22 cm"


def test_render_expression_label_displays_fraction_without_float_rounding():
    node = ExpressionLabelNode(
        ref="answer",
        expression=FractionNode(
            operands=[LiteralNode(value=3), LiteralNode(value=4)]
        ),
        role="answer",
    )
    mobjects = {}
    render_animation_node(_StubScene(), node, {}, mobjects)
    assert mobjects["answer"].original_text == "3/4"


def test_render_rectangle_uses_evaluated_dimensions():
    node = RectangleNode(
        ref="diagram",
        length=FieldRefNode(field="length"),
        width=FieldRefNode(field="width"),
        unit="cm",
    )
    mobjects = {}
    render_animation_node(
        _StubScene(), node, {"length": 8, "width": 3}, mobjects
    )
    texts = [
        child.original_text
        for child in mobjects["diagram"].submobjects
        if isinstance(child, Text)
    ]
    assert "8 cm" in texts
    assert "3 cm" in texts
```

- [ ] **Step 6: Run the dynamic renderer tests and verify unknown-kind failures**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/test_dynamic_scene.py::test_render_expression_label_displays_evaluated_integer \
  tests/meta/test_dynamic_scene.py::test_render_expression_label_displays_fraction_without_float_rounding \
  tests/meta/test_dynamic_scene.py::test_render_rectangle_uses_evaluated_dimensions -v
```

Expected: tests fail because `render_animation_node` has no branches for the new kinds.

- [ ] **Step 7: Add renderer dispatch for both nodes**

Add `build_rectangle` and `format_expression_value` imports. Add a Fraction
resolver that does not impose the existing integer-count restriction:

```python
def _resolve_value(node, field_name: str, values: dict):
    return _evaluate(getattr(node, field_name), values)
```

Render `expression_label` as:

```python
value = format_expression_value(_resolve_value(node, "expression", values))
result = build_label(f"{node.prefix}{value}{node.suffix}", style=node.style)
```

Render `rectangle` by passing evaluated length and width, unit, and style to
`build_rectangle`. Keep `_resolve` unchanged for count-based visuals that
require whole numbers.

- [ ] **Step 8: Run focused renderer and primitive tests**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/manim_primitives/test_visual_primitives.py \
  tests/meta/test_dynamic_scene.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit the rendering support**

```bash
git add backend/app/meta/manim_primitives/visuals.py \
  backend/app/meta/dynamic_scene.py \
  backend/tests/meta/manim_primitives/test_visual_primitives.py \
  backend/tests/meta/test_dynamic_scene.py
git commit -m "feat: render meta values and rectangles"
```

### Task 3: Visible-answer and generation-version invariants

**Files:**
- Modify: `backend/tests/meta/test_validation.py`
- Modify: `backend/tests/meta/test_draft_generation.py`
- Modify: `backend/app/meta/validation.py`
- Modify: `backend/app/meta/draft_generation.py`

**Interfaces:**
- Consumes: `CompiledAnimation.answer_expressions` and the parsed top-level `answer_expression`.
- Produces: `DslValidationError(code="answer_not_displayed", ...)` for invalid version 2 drafts and a generation boundary that rejects model proposals below version 2.

- [ ] **Step 1: Write failing validation tests for missing, mismatched, and matching answers**

Add `ExpressionLabelNode` and `ColumnNode` imports, then add:

```python
def _version_two_documents(animation_root):
    params_document, guard_document, answer_expression, _ = _documents()
    return (
        params_document,
        guard_document,
        answer_expression,
        AnimationDocument(animation_version=2, root=animation_root),
    )


def test_version_two_draft_rejects_missing_visible_answer():
    with pytest.raises(DslValidationError) as exc:
        compile_draft_documents(
            *_version_two_documents(LabelNode(text="Solve the problem"))
        )
    assert exc.value.code == "answer_not_displayed"


def test_version_two_draft_rejects_mismatched_visible_answer():
    with pytest.raises(DslValidationError) as exc:
        compile_draft_documents(
            *_version_two_documents(
                ExpressionLabelNode(
                    expression=LiteralNode(value=999),
                    role="answer",
                )
            )
        )
    assert exc.value.code == "answer_not_displayed"


def test_version_two_draft_accepts_matching_visible_answer():
    compiled = compile_draft_documents(
        *_version_two_documents(
            ExpressionLabelNode(
                expression=FieldRefNode(field="n"),
                prefix="Answer: ",
                role="answer",
            )
        )
    )
    assert compiled.compiled_animation.answer_expressions == (
        FieldRefNode(field="n"),
    )
```

- [ ] **Step 2: Run the validation tests and verify missing invariant failures**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/test_validation.py::test_version_two_draft_rejects_missing_visible_answer \
  tests/meta/test_validation.py::test_version_two_draft_rejects_mismatched_visible_answer \
  tests/meta/test_validation.py::test_version_two_draft_accepts_matching_visible_answer -v
```

Expected: missing and mismatched cases compile when they should fail.

- [ ] **Step 3: Enforce exact visible-answer equality**

After compiling the animation in `compile_draft_documents`, add:

```python
if (
    animation_document.animation_version == 2
    and answer_expression not in compiled_animation.answer_expressions
):
    raise DslValidationError(
        "answer_not_displayed",
        "version 2 animations must display answer_expression "
        "with an answer-role expression_label",
    )
```

Use Pydantic model structural equality; do not add algebraic equivalence logic.

- [ ] **Step 4: Run all validation tests**

Run:

```bash
cd backend
../.venv/bin/pytest tests/meta/test_validation.py -v
```

Expected: all tests pass, including legacy version 1 fixtures.

- [ ] **Step 5: Convert the raw generation fixture to version 2 and add a failing legacy-output test**

Change `_raw_proposal()` in `test_draft_generation.py` to:

```python
"animation_document": {
    "animation_version": 2,
    "root": {
        "kind": "expression_label",
        "expression": {
            "node": "fraction",
            "operands": [
                {"node": "field_ref", "field": "numerator"},
                {"node": "field_ref", "field": "denominator"},
            ],
        },
        "prefix": "Answer: ",
        "role": "answer",
    },
},
```

Add:

```python
@patch("app.meta.draft_generation.call_with_tool")
def test_propose_template_draft_rejects_legacy_animation_version(mock_call):
    proposal = _raw_proposal()
    proposal["animation_document"]["animation_version"] = 1
    mock_call.return_value = ("propose_template_draft", proposal)
    with pytest.raises(ValueError, match="animation_version 2"):
        propose_template_draft(_fingerprint(), [_observation()])
```

- [ ] **Step 6: Run the generation test and verify version 1 is still accepted**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/test_draft_generation.py::test_propose_template_draft_rejects_legacy_animation_version -v
```

Expected: FAIL because `propose_template_draft` returns the version 1 proposal.

- [ ] **Step 7: Require version 2 at the model-generation boundary**

After `DraftProposal.model_validate(...)` in `propose_template_draft`, add:

```python
if proposal.animation_document.animation_version != 2:
    raise ValueError("generated animation_document must use animation_version 2")
```

Extend `_DRAFT_SYSTEM_PROMPT` to require version 2, explain that static labels
never interpolate braces, require a matching answer-role `expression_label`,
and direct rectangle length/width problems to the `rectangle` node instead of
counting visuals.

- [ ] **Step 8: Run focused generation and validation tests**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/test_validation.py \
  tests/meta/test_draft_generation.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit the publication contract**

```bash
git add backend/app/meta/validation.py \
  backend/app/meta/draft_generation.py \
  backend/tests/meta/test_validation.py \
  backend/tests/meta/test_draft_generation.py
git commit -m "fix: require visible meta-template answers"
```

### Task 4: Perimeter demo regression and documentation

**Files:**
- Modify: `backend/tests/meta/test_demo_end_to_end.py`
- Modify: `docs/meta-template-demo.md`

**Interfaces:**
- Consumes: version 2 `rectangle` and `expression_label` nodes plus the existing full generation, approval, reuse, and MP4 render path.
- Produces: a perimeter regression fixture that visibly renders `8`, `3`, and `22` for slide 1 and computes `28` for slide 2.

- [ ] **Step 1: Replace the mocked perimeter animation with the corrected version 2 document**

Change `_good_perimeter_proposal()` to use:

```python
"animation_document": {
    "animation_version": 2,
    "root": {
        "kind": "sequence",
        "steps": [
            {
                "kind": "column",
                "children": [
                    {
                        "kind": "label",
                        "ref": "title",
                        "text": "Perimeter of a Rectangle",
                        "style": "accent",
                    },
                    {
                        "kind": "rectangle",
                        "ref": "diagram",
                        "length": {"node": "field_ref", "field": "length"},
                        "width": {"node": "field_ref", "field": "width"},
                        "unit": "cm",
                        "style": "primary",
                    },
                    {
                        "kind": "row",
                        "ref": "dimensions",
                        "children": [
                            {
                                "kind": "expression_label",
                                "ref": "length_value",
                                "expression": {"node": "field_ref", "field": "length"},
                                "prefix": "Length: ",
                                "suffix": " cm",
                                "role": "working",
                                "style": "primary",
                            },
                            {
                                "kind": "expression_label",
                                "ref": "width_value",
                                "expression": {"node": "field_ref", "field": "width"},
                                "prefix": "Width: ",
                                "suffix": " cm",
                                "role": "working",
                                "style": "secondary",
                            },
                        ],
                        "gap": 1.0,
                    },
                    {
                        "kind": "label",
                        "ref": "formula",
                        "text": "P = 2 × (length + width)",
                        "style": "muted",
                    },
                    {
                        "kind": "expression_label",
                        "ref": "answer",
                        "expression": _ANSWER_EXPRESSION,
                        "prefix": "P = ",
                        "suffix": " cm",
                        "role": "answer",
                        "style": "success",
                    },
                ],
                "gap": 0.35,
            },
            {"kind": "appear", "target_ref": "title"},
            {"kind": "appear", "target_ref": "diagram"},
            {"kind": "appear", "target_ref": "dimensions"},
            {"kind": "appear", "target_ref": "formula"},
            {"kind": "appear", "target_ref": "answer"},
            {"kind": "wait", "seconds": 2},
        ],
    },
},
```

Remove `grid`, `object_set`, and placeholder-style text from this fixture.

- [ ] **Step 2: Add real rendering assertions for slide 1 values**

Import `AnimationDocument`, `compile_animation_document`,
`render_animation_node`, and Manim `Text`. Add a local `_StubScene` with
`play()` and `wait()` methods, then after the draft reaches pending review:

```python
animation = AnimationDocument.model_validate_json(draft.animation_document_json)
compiled_animation = compile_animation_document(
    animation, frozenset({"length", "width"})
)
mobjects = {}
render_animation_node(
    _StubScene(),
    compiled_animation.document.root,
    {"length": 8, "width": 3},
    mobjects,
)
assert mobjects["length_value"].original_text == "Length: 8 cm"
assert mobjects["width_value"].original_text == "Width: 3 cm"
assert mobjects["answer"].original_text == "P = 22 cm"
rectangle_text = {
    child.original_text
    for child in mobjects["diagram"].submobjects
    if isinstance(child, Text)
}
assert rectangle_text == {"8 cm", "3 cm"}
```

These assertions exercise the real expression evaluator and renderer; they do
not inspect mocked calls or merely grep JSON.

- [ ] **Step 3: Run the end-to-end test and verify it fails before the fixture update is complete**

Run:

```bash
cd backend
../.venv/bin/pytest tests/meta/test_demo_end_to_end.py -v
```

Expected before completing Steps 1–2: failure because the old version 1
proposal has no rendered value refs. Expected after completing them: both demo
tests pass and a real MP4 is created.

- [ ] **Step 4: Update the demo runbook**

Update the review, expected-checkpoint, and troubleshooting sections to state:

- The preview must show a proportional rectangle labeled `8 cm` by `3 cm`.
- The final answer must visibly resolve to `22 cm`; literal brace placeholders
  are a validation failure.
- Rehearsals using an older approved version require the documented disposable
  database reset or a refined and republished version.
- Slide 2 must visibly resolve the reused template to `28 cm`.

- [ ] **Step 5: Run the complete focused regression set**

Run:

```bash
cd backend
../.venv/bin/pytest \
  tests/meta/dsl/test_animation_schema.py \
  tests/meta/dsl/test_animation_compile.py \
  tests/meta/manim_primitives/test_visual_primitives.py \
  tests/meta/test_dynamic_scene.py \
  tests/meta/test_validation.py \
  tests/meta/test_draft_generation.py \
  tests/meta/test_demo_end_to_end.py -v
```

Expected: all focused tests pass.

- [ ] **Step 6: Run the complete backend suite**

Run:

```bash
cd backend
../.venv/bin/pytest -q
```

Expected: all backend tests pass with no new warnings or errors.

- [ ] **Step 7: Check formatting and diff integrity**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended implementation, tests, and demo
documentation are changed. The user's untracked `CLAUDE.md` remains untouched.

- [ ] **Step 8: Commit the perimeter regression**

```bash
git add backend/tests/meta/test_demo_end_to_end.py docs/meta-template-demo.md
git commit -m "test: verify visible perimeter template values"
```
