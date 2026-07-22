from typing import Type, TypeVar

from pydantic import BaseModel

from app.pipeline.bedrock_client import call_with_tool
from app.pipeline.grounding import check_params_grounded

T = TypeVar("T", bound=BaseModel)


class TemplateMismatchError(Exception):
    """Raised when the source problem does not structurally fit the chosen template."""


_EXTRACTION_SYSTEM_PROMPT = (
    "Extract only the numbers and operations needed to fill in the given schema. "
    "Never compute or state a final answer — only report the operation type and "
    "operands exactly as they appear in the text. Preserve operand order exactly, "
    "even for commutative operations. In a phrase like 'composed of A and B', use A "
    "as the first operand and B as the second. Ignore answer choices, displayed answers, "
    "and diagram labels outside the problem statement. "
    "If the problem has no structure matching the schema — for example no add or "
    "subtract sequence for a step-based schema, or non-whole operands for a "
    "whole-number schema — call decline_extraction with a short reason instead of "
    "forcing an ill-fitting answer."
)

_DECLINE_TOOL_NAME = "decline_extraction"
_DECLINE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}},
    "required": ["reason"],
}


def _problem_statement(source_text: str) -> str:
    statement, question_mark, _ = source_text.rpartition("?")
    return f"{statement}{question_mark}" if question_mark else source_text


def extract_params(source_text: str, params_cls: Type[T]) -> T:
    schema = params_cls.model_json_schema()
    tool_name, result = call_with_tool(
        system_prompt=_EXTRACTION_SYSTEM_PROMPT,
        user_message=_problem_statement(source_text),
        tools=[
            {"name": "report_params", "schema": schema},
            {"name": _DECLINE_TOOL_NAME, "schema": _DECLINE_TOOL_SCHEMA},
        ],
    )
    if tool_name == _DECLINE_TOOL_NAME:
        reason = result.get("reason", "no reason given")
        raise TemplateMismatchError(f"Model declined extraction: {reason}")
    params = params_cls.model_validate(result)
    ungrounded = check_params_grounded(params, _problem_statement(source_text))
    if ungrounded:
        raise TemplateMismatchError(
            f"Extracted numbers not grounded in source: {', '.join(ungrounded)}"
        )
    return params
