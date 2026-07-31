# Task 3 implementation report

## Changed files

- `backend/app/meta/v3/geometry.py`
- `backend/app/meta/v3/ordered_values.py`
- `backend/app/meta/v3/visual_registry.py`
- `backend/tests/meta/v3/test_ordered_values.py`

## Decisions

- Added frozen `Point`, `Bounds`, `SemanticPart`, and `MeasuredVisual` dataclasses with semantic anchor calculation from either complete-visual or item-specific bounds.
- Added the `TextMeasurer` protocol and measured ordered values using each value's individual width and height.
- Stored item parts under `("item", index)` so item anchors resolve from that item's measured bounds, including uneven-width values.
- Added the callable `VisualFactory` protocol and duplicate/unknown-kind behavior specified by the brief.
- Kept the geometry layer independent of renderer controls and fixture coordinates.

## Tests

The relative virtualenv was absent, so the required fallback executable was used.

RED command:

```text
/Users/ctg/Desktop/ctg/si26-math-animation/backend/.venv/bin/pytest backend/tests/meta/v3/test_ordered_values.py -v
```

Output: collection failed with the expected `ModuleNotFoundError: No module named 'app.meta.v3.ordered_values'`.

Focused command:

```text
/Users/ctg/Desktop/ctg/si26-math-animation/backend/.venv/bin/pytest backend/tests/meta/v3/test_ordered_values.py -v
```

Output:

```text
============================= test session starts ==============================
platform darwin -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /Users/ctg/Desktop/ctg/si26-math-animation/backend/.venv/bin/python3.14
collecting ... collected 1 item

backend/tests/meta/v3/test_ordered_values.py::test_median_item_anchor_uses_eight_bounds_not_row_center PASSED [100%]

============================== 1 passed in 0.01s ===============================
```

Additional self-check command:

```text
/Users/ctg/Desktop/ctg/si26-math-animation/backend/.venv/bin/python - <<'PY'
... geometry immutability and registry assertions ...
PY
```

Output: `geometry immutability and registry checks passed`.

`git diff --check` completed with no output or errors.

## Self-review findings

- The median item anchor is calculated from `visual.parts[("item", 3)].bounds.center`, not the complete row center.
- `Point`, `Bounds`, `SemanticPart`, and `MeasuredVisual` reject direct field reassignment through frozen dataclasses.
- Registry duplicate registration and unknown semantic kinds produce the exact specified `ValueError` messages.
- No unrelated tracked files were modified.

## Concerns

- The frozen dataclasses contain ordinary dictionaries/lists as specified, so nested mappings and path lists are not deeply immutable. Deep freezing would change the supplied public shape and was intentionally not introduced in Task 3.
- Only the specified focused test was run; the full repository suite was outside this task's requested verification scope.

## Fix round 1 report

### Findings addressed

- `MeasuredVisual.__post_init__` now defensively copies `parts` and `paths`, wraps both mappings in `MappingProxyType`, and converts each path sequence to a tuple. `Point`, `Bounds`, and `SemanticPart` remain frozen, so measured geometry is immutable in practice while preserving keyed lookup and path indexing.
- Added durable pytest coverage for caller-owned input mutation, direct mapping/path mutation attempts, frozen field reassignment, duplicate registry kinds, and unknown registry kinds.

### Changed files

- `backend/app/meta/v3/geometry.py`
- `backend/tests/meta/v3/test_ordered_values.py`
- This report

### Tests and exact outputs

TDD RED command after adding the regression tests:

```text
/Users/ctg/Desktop/ctg/si26-math-animation/backend/.venv/bin/pytest backend/tests/meta/v3/test_ordered_values.py -v
```

Output: `1 failed, 3 passed`; the failure showed caller-owned `parts` and `paths` were still visible through `MeasuredVisual`.

Focused Task 3 command after the fix:

```text
/Users/ctg/Desktop/ctg/si26-math-animation/backend/.venv/bin/pytest backend/tests/meta/v3/test_ordered_values.py -v
```

Output:

```text
============================= test session starts ==============================
platform darwin -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /Users/ctg/Desktop/ctg/si26-math-animation/backend/.venv/bin/python3.14
collecting ... collected 4 items

backend/tests/meta/v3/test_ordered_values.py::test_median_item_anchor_uses_eight_bounds_not_row_center PASSED [ 25%]
backend/tests/meta/v3/test_ordered_values.py::test_measured_geometry_rejects_mutation_and_defensively_copies_inputs PASSED [ 50%]
backend/tests/meta/v3/test_ordered_values.py::test_visual_registry_rejects_duplicate_kinds PASSED [ 75%]
backend/tests/meta/v3/test_ordered_values.py::test_visual_registry_rejects_unknown_kinds PASSED [100%]

============================== 4 passed in 0.01s ===============================
```

Directly relevant DSL/security command:

```text
/Users/ctg/Desktop/ctg/si26-math-animation/backend/.venv/bin/pytest backend/tests/meta/v3/test_ordered_values.py backend/tests/meta/dsl/test_scene_program_schema.py backend/tests/meta/dsl/test_dsl_security.py -v
```

Output: `39 passed in 0.63s`.

Self-review: `git diff --check` produced no output or errors; only the Task 3 geometry/test files and this report were changed. No new concerns identified beyond the prior report's limited full-suite scope.
