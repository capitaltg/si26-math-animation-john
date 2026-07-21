from pydantic import BaseModel, Field

from app.models.scene import TemplateName
from app.pipeline.bedrock_client import call_with_tool

# Each template is a structural contract, not a free-form illustration. The classifier
# must return only options whose parameter guards can accept the problem downstream.
_TEMPLATE_CONTRACTS = (
    "- number_line: a journey of 1 to 3 sequential add/subtract jumps from a start value "
    "(e.g. 6 + 3 or 4 + 3 - 1). A single operation is one valid jump.\n"
    "- balance_scale: a single equation with exactly two addends on one side equalling a "
    "total (e.g. 6 + 3 = ?, 10 + 2 = 12). Useful for single-operation sums.\n"
    "- array_grid: equal groups / repeated addition / multiplication shown as rows x columns.\n"
    "- fraction_bar: 2 to 3 sequential add/subtract steps on fractions sharing one denominator.\n"
    "- text_card: worksheets, lists of many problems, or any problem that does not fit the "
    "structural templates above. Use this rather than forcing an ill-fitting template."
)

_CLASSIFICATION_SYSTEM_PROMPT = (
    "You classify a single K-8 math example problem into compatible visual template "
    "categories and infer its grade level. Each template accepts only problems that "
    "match its structural contract:\n"
    f"{_TEMPLATE_CONTRACTS}\n"
    "Return every template whose structural contract this problem satisfies, ranked "
    "best-first, each with a one-phrase rationale. Never include a template the problem "
    "cannot structurally satisfy. Do not compute or state any answer. Set ambiguous=true "
    "when the operands or operation cannot be confidently determined, or when no "
    "structural template fits the problem; in that case return an empty options list."
)


class TemplateOption(BaseModel):
    template: TemplateName
    rationale: str = Field(min_length=1)


class ClassificationResult(BaseModel):
    options: list[TemplateOption] = Field(default_factory=list)
    grade_level: int = Field(ge=0, le=8)
    ambiguous: bool = False


_TEXT_CARD_OPTION = TemplateOption(
    template=TemplateName.TEXT_CARD,
    rationale="always-compatible fallback",
)


def classify_candidate(source_text: str) -> ClassificationResult:
    schema = ClassificationResult.model_json_schema()
    result = call_with_tool(
        system_prompt=_CLASSIFICATION_SYSTEM_PROMPT,
        user_message=source_text,
        tool_name="classify_problem",
        tool_schema=schema,
    )
    classification = ClassificationResult.model_validate(result)
    text_card = next(
        (
            option
            for option in classification.options
            if option.template == TemplateName.TEXT_CARD
        ),
        _TEXT_CARD_OPTION,
    )
    structural_options = []
    seen_templates: set[TemplateName] = set()
    if not classification.ambiguous:
        for option in classification.options:
            if (
                option.template == TemplateName.TEXT_CARD
                or option.template in seen_templates
            ):
                continue
            seen_templates.add(option.template)
            structural_options.append(option)
    return classification.model_copy(
        update={"options": [*structural_options, text_card]},
    )
