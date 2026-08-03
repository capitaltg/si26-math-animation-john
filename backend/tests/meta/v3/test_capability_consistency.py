"""Static agreement checks between the v3 plan schema and the compiler
capability tables.

These tests compare *declarations*. They never execute the compiler, so
agreement between two tables is not evidence that any combination of kind,
strategy, and custom action compiles, measures, or renders. A green file means
the declarations are mutually consistent and the known gaps are recorded.

Design: docs/superpowers/specs/2026-08-03-v3-capability-consistency-design.md
"""

from typing import get_args

import pytest
from pydantic import ValidationError

from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.v3.visual_registry import _SUPPORTED_STRATEGIES


def _declared_strategies():
    return set(get_args(TeachingPlanDocument.model_fields["strategy"].annotation))


def test_every_declared_strategy_is_reachable():
    reachable = set().union(*_SUPPORTED_STRATEGIES.values())
    assert _declared_strategies() - reachable == set()


def test_removed_strategy_is_rejected_at_schema_validation():
    assert "representation_transform" not in _declared_strategies()

    with pytest.raises(ValidationError):
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
