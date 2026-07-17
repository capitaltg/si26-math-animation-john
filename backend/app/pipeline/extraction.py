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
