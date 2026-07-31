# Task 4 Registry Follow-up Report

## Status

Implemented the smallest owning-layer correction: the default `ordered_values`
registry factory now uses the scene layout gap of `0.45` instead of `8`.
The direct `measure_ordered_values` API remains unchanged, including its
caller-supplied gap, and item-specific anchors remain unchanged.

Added a registry regression for the normal seven-value median
`3, 5, 6, 8, 9, 12, 15` asserting finite bounds inside `SAFE_FRAME`.

## Changed files

- `backend/app/meta/v3/visual_registry.py`
  - Changed only the default ordered-values display gap from `8` to `0.45`.
- `backend/tests/meta/v3/test_visual_registry.py`
  - Added a scene-scale text measurer and seven-value median finite/safe-bounds regression.

## Commands and outputs

Initial focused regression (brief's worktree-local interpreter path):

```text
backend/.venv/bin/pytest backend/tests/meta/v3/test_visual_registry.py::test_default_registry_keeps_seven_value_median_inside_safe_frame -q
zsh:1: no such file or directory: backend/.venv/bin/pytest
exit_code=127
```

The available project interpreter was `/Users/ctg/Desktop/ctg/si26-math-animation/.venv/bin/pytest`.

Red regression before the production change:

```text
/Users/ctg/Desktop/ctg/si26-math-animation/.venv/bin/pytest backend/tests/meta/v3/test_visual_registry.py::test_default_registry_keeps_seven_value_median_inside_safe_frame -q
1 failed in 0.02s
AssertionError: assert -25.35 >= -6.6
```

Focused geometry/registry suite after the change:

```text
/Users/ctg/Desktop/ctg/si26-math-animation/.venv/bin/pytest backend/tests/meta/v3/test_ordered_values.py backend/tests/meta/v3/test_rectangle_measurement.py backend/tests/meta/v3/test_visual_registry.py -v
18 passed in 0.02s
```

Relevant v3 resolver/probe checks:

```text
/Users/ctg/Desktop/ctg/si26-math-animation/.venv/bin/pytest backend/tests/meta/v3/test_scene_resolver.py backend/tests/meta/v3/test_render_probe.py -v
27 passed in 0.75s
```

Self-review:

```text
git diff --check
(no output; exit 0)
```

## Concerns

- The isolated worktree does not contain `backend/.venv`; verification used the
  repository-root `.venv` interpreter, which produced the requested test results.
- No remaining concerns identified.
