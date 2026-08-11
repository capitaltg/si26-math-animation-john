"""Deterministic numeric answers per template — Python-computed, not LLM.

Populated for templates whose params class exposes a natural answer.
Frontend `SolutionCard` renders when non-null.
"""
from __future__ import annotations

from typing import Callable, Optional

from app.models.scene import TemplateName
from app.templates.array_grid.params import ArrayGridParams


def _array_grid_answer(params_dict: dict) -> Optional[dict]:
    try:
        params = ArrayGridParams(**params_dict)
    except Exception:
        return None
    total = params.compute_answer()
    if params.steps:
        pieces = [str(params.starting_total())]
        for step in params.steps:
            op = "×" if step.operation == "multiply" else "÷"
            pieces.append(f"{op} {step.factor}")
        expression = f"{' '.join(pieces)} = {total}"
    else:
        expression = f"{params.rows} × {params.cols} = {total}"
    return {"value": f"= {total}", "expression": expression}


TEMPLATE_ANSWERS: dict[str, Callable[[dict], Optional[dict]]] = {
    TemplateName.ARRAY_GRID.value: _array_grid_answer,
}


def compute_answer_for(template_name: str, params: dict) -> Optional[dict]:
    fn = TEMPLATE_ANSWERS.get(template_name)
    if fn is None:
        return None
    return fn(params)
