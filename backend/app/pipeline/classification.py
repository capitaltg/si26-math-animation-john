from pydantic import BaseModel, Field

from app.models.scene import TemplateName
from app.pipeline.bedrock_client import call_with_tool

# Each template is a structural contract, not a free-form illustration. The classifier
# must respect these constraints, otherwise it routes problems to templates whose
# parameter guards will reject them downstream (e.g. a single-operation sum sent to
# number_line, which requires a 2-3 step journey).
_TEMPLATE_CONTRACTS = (
    "- number_line: a journey of 2 to 3 sequential add/subtract jumps from a start value "
    "(e.g. 4 + 3 - 1). NOT for a single operation.\n"
    "- balance_scale: a single equation with exactly two addends on one side equalling a "
    "total (e.g. 6 + 3 = ?, 10 + 2 = 12). This is the right choice for single-operation sums.\n"
    "- array_grid: equal groups / repeated addition / multiplication shown as rows x columns.\n"
    "- fraction_bar: 2 to 3 sequential add/subtract steps on fractions sharing one denominator.\n"
    "- text_card: worksheets, lists of many problems, or any problem that does not fit the "
    "structural templates above. Use this rather than forcing an ill-fitting template."
)

_CLASSIFICATION_SYSTEM_PROMPT = (
    "You classify a single K-8 math example problem into one visual template category, "
    "or flag it as unsupported/ambiguous. Choose the template whose representation best "
    "fits the problem and the inferred grade level. Each template accepts only problems "
    "that match its structural contract:\n"
    f"{_TEMPLATE_CONTRACTS}\n"
    "Never pick a template the problem cannot structurally satisfy; when in doubt, prefer "
    "text_card over a mismatch. Do not compute or state any answer. "
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
