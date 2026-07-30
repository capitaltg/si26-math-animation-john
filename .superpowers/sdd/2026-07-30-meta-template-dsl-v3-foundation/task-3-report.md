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
