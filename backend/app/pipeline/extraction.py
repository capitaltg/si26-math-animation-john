from typing import Type, TypeVar

from pydantic import BaseModel

from app.pipeline.bedrock_client import call_with_tool

T = TypeVar("T", bound=BaseModel)

_EXTRACTION_SYSTEM_PROMPT = (
    "Extract only the numbers and operations needed to fill in the given schema. "
    "Never compute or state a final answer — only report the operation type and "
    "operands exactly as they appear in the text. Preserve operand order exactly, "
    "even for commutative operations. In a phrase like 'composed of A and B', use A "
    "as the first operand and B as the second. Ignore answer choices, displayed answers, "
    "and diagram labels outside the problem statement."
)


def _problem_statement(source_text: str) -> str:
    statement, question_mark, _ = source_text.rpartition("?")
    return f"{statement}{question_mark}" if question_mark else source_text


def extract_params(source_text: str, params_cls: Type[T]) -> T:
    schema = params_cls.model_json_schema()
    _, result = call_with_tool(
        system_prompt=_EXTRACTION_SYSTEM_PROMPT,
        user_message=_problem_statement(source_text),
        tools=[{"name": "report_params", "schema": schema}],
    )
    return params_cls.model_validate(result)
