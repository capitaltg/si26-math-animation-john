"""Static agreement checks between the v3 plan schema and the compiler
capability tables.

These tests compare *declarations*. They never compile a plan, so
agreement between two tables is not evidence that any combination of kind,
strategy, and custom action compiles, measures, or renders. A green file means
the declarations are mutually consistent and the known gaps are recorded.

Design: docs/superpowers/specs/2026-08-03-v3-capability-consistency-design.md
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.v3 import beat_expander
from app.meta.v3.compiler import (
    _DECLARED_PATHS, _DRAWABLE_TARGETS, _MOVABLE_TARGETS, _TRANSFORM_COMPATIBILITY,
)
from app.meta.v3.visual_registry import _SUPPORTED_STRATEGIES


def _declared_strategies():
    return set(get_args(TeachingPlanDocument.model_fields["strategy"].annotation))


def test_every_declared_strategy_is_reachable():
    reachable = set().union(*_SUPPORTED_STRATEGIES.values())
    assert _declared_strategies() == reachable


def test_removed_strategy_is_rejected_at_schema_validation():
    assert "representation_transform" not in _declared_strategies()

    with pytest.raises(ValidationError, match="strategy"):
        TeachingPlanDocument.model_validate({
            "plan_version": 3,
            "learning_objective": "Unreachable strategies must not validate.",
            "primary_visual": {"kind": "label", "ref": "caption", "text": "hello"},
            "strategy": "representation_transform",
            "beats": [
                {"id": "reveal_caption", "kind": "reveal",
                 "targets": [{"visual_ref": "caption"}], "intent": "show the caption"},
                {"id": "focus_caption", "kind": "focus",
                 "targets": [{"visual_ref": "caption"}], "intent": "draw attention to it"},
                {"id": "state_answer", "kind": "conclude",
                 "targets": [{"visual_ref": "caption"}], "intent": "state the answer"},
            ],
            "variation_seed": "capability-consistency",
        })


# Strategies that `_SUPPORTED_STRATEGIES` offers and `expand_beats` does not
# branch on. Shrinking this set is the work; each entry is a known gap.
#
#   group_reveal          -- the default path. Needs no branch, never will.
#   regroup               -- degrades to an undifferentiated group reveal.
#   magnitude_comparison  -- degrades to an undifferentiated group reveal.
#
# The two degrading entries produce no failure and no warning, only a wrong
# animation. See the design's "Schema-complete, behavior-thin" tier:
# docs/superpowers/specs/2026-08-03-v3-capability-consistency-design.md
# Tracking issue: capitaltg/si26-math-animation-john#66
_STRATEGIES_WITHOUT_EXPANDER_BEHAVIOR = {
    "group_reveal",
    "magnitude_comparison",
    "regroup",
}


def test_every_supported_strategy_has_expander_behavior():
    # A source-text search, deliberately crude: it proves a strategy name is
    # *mentioned*, not that the branch differentiates output. `partition` counts
    # as handled on this measure because the name also appears as a visual-kind
    # key in beat_expander's program-visual map. A stronger check requires
    # executing the compiler and diffing scene programs -- the design's Phase 2.
    source = Path(beat_expander.__file__).read_text()
    supported = set().union(*_SUPPORTED_STRATEGIES.values())
    unhandled = {strategy for strategy in supported if strategy not in source}

    assert unhandled == _STRATEGIES_WITHOUT_EXPANDER_BEHAVIOR


# Kinds each capability table covers today. Adding a kind to a table fails this
# test, forcing the expected set to be updated in the same change -- capability
# growth becomes a reviewable one-line diff. Seven of eight kinds are absent
# from all four tables, so trace/draw/move/transform custom actions fail on
# everything but rectangle_measurement.
_EXPECTED_TABLE_COVERAGE = [
    ("_DECLARED_PATHS", _DECLARED_PATHS, {"rectangle_measurement"}),
    ("_DRAWABLE_TARGETS", _DRAWABLE_TARGETS, {"rectangle_measurement"}),
    ("_MOVABLE_TARGETS", _MOVABLE_TARGETS, {"rectangle_measurement"}),
    ("_TRANSFORM_COMPATIBILITY", _TRANSFORM_COMPATIBILITY, {"rectangle_measurement"}),
]


@pytest.mark.parametrize(
    "table, expected_kinds",
    [(table, expected) for _, table, expected in _EXPECTED_TABLE_COVERAGE],
    ids=[name for name, _, _ in _EXPECTED_TABLE_COVERAGE],
)
def test_capability_tables_cover_declared_kinds(table, expected_kinds):
    assert set(table) == expected_kinds


def test_hint_enumeration_is_deterministic_across_hash_seeds():
    # The capability tables hold `set` literals and the expected hint strings in
    # test_teaching_compiler.py are committed verbatim. Set iteration order is
    # fixed per process but varies with PYTHONHASHSEED, so an unsorted
    # enumeration passes every same-process test and flakes in CI. Two seeds,
    # one expectation.
    probe = (
        "from app.meta.v3.compiler import _enumerate_legal; "
        "print(_enumerate_legal({'zebra', 'apple', 'mango'}, 'pick one', 'none'))"
    )
    outputs = {
        seed: subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("0", "1", "12345")
    }

    assert set(outputs.values()) == {"pick one: apple, mango, zebra"}
