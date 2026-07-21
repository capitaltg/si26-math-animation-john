from pydantic import BaseModel, Field

from app.models.scene import TemplateName
from app.pipeline.bedrock_client import call_with_tool

_CLASSIFICATION_SYSTEM_PROMPT = (
    "You classify a single K-8 math example problem into one visual template category, "
    "or flag it as unsupported/ambiguous. Choose the template whose representation best "
    "fits the problem and the inferred grade level. Do not compute or state any answer. "
    "Set ambiguous=true when the operands or operation cannot be confidently determined, "
    "or when no template fits the problem."
)


class ClassificationResult(BaseModel):
    template: TemplateName | None = None
    grade_level: int = Field(ge=0, le=8)
    ambiguous: bool = False


def classify_candidate(source_text: str) -> ClassificationResult:
    schema = ClassificationResult.model_json_schema()
    result = call_with_tool(
        system_prompt=_CLASSIFICATION_SYSTEM_PROMPT,
        user_message=source_text,
        tool_name="classify_problem",
        tool_schema=schema,
    )
    return ClassificationResult.model_validate(result)
