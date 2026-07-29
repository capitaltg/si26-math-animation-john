import copy
import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.meta.dynamic_templates import EnabledSnapshot, load_enabled_snapshot
from app.models.scene import TemplateName
from app.pipeline.bedrock_client import call_with_tool
from app.templates.registry import static_ref

logger = logging.getLogger(__name__)

# Each template is a structural contract, not a free-form illustration. The classifier
# must return only options whose parameter guards can accept the problem downstream.
_TEMPLATE_CONTRACTS = (
    "- number_line: a journey of 1 to 3 sequential add/subtract jumps from a start value "
    "(e.g. 6 + 3 or 4 + 3 - 1). A single operation is one valid jump. Requires an actual "
    "add or subtract operation that moves along the line. Do NOT use for plotting, drawing, "
    "or labeling given numbers or fractions on a line when no operation is performed — a "
    "static plot-the-points task has no journey and belongs to text_card.\n"
    "- balance_scale: a single equation with exactly two addends on one side equalling a "
    "total (e.g. 6 + 3 = ?, 10 + 2 = 12). Useful for single-operation sums.\n"
    "- array_grid: equal groups / repeated addition / multiplication shown as rows x columns. "
    "May also include 1 to 3 sequential multiply/divide steps applied to a source-stated "
    "starting total (e.g. a grouped amount doubled, then split into smaller equal groups) "
    "as long as division is exact and every positive whole-number state fits a renderable "
    "grid.\n"
    "- fraction_of_whole: a single static fraction shown as a shaded part of one whole "
    "(e.g. \"what fraction is shaded\", \"color 1/2 blue\"). No operation, no sequence — "
    "just naming or representing one fraction.\n"
    "- fraction_bar: 2 to 3 sequential add/subtract steps on fractions sharing one "
    "denominator (e.g. repeated-addition word problems like \"swims 1/4 mile a day, how far "
    "in 3 days\"). Requires an actual operation across steps — a single static fraction "
    "belongs to fraction_of_whole instead.\n"
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
    "cannot structurally satisfy. Do not compute or state any answer. "
    "Set ambiguous=true only when the operands or operation cannot be confidently "
    "determined. Set problem_kind='not_a_problem' when the text is not a concrete "
    "solvable math problem (a heading, instruction, or prose). When the text IS a "
    "solvable problem but no structural template above fits it, return an empty "
    "options list with ambiguous=false and problem_kind='solvable'."
)


class TemplateOption(BaseModel):
    template: str
    rationale: str = Field(min_length=1)
    version_id: str = ""


class ClassificationResult(BaseModel):
    options: list[TemplateOption] = Field(default_factory=list)
    grade_level: int = Field(ge=0, le=8)
    ambiguous: bool = False
    problem_kind: Literal["solvable", "not_a_problem"] = "solvable"


_TEXT_CARD_OPTION = TemplateOption(
    template=TemplateName.TEXT_CARD,
    rationale="always-compatible fallback",
    version_id=static_ref(TemplateName.TEXT_CARD).version_id,
)


def _patch_schema_enum(schema: dict, allowed_names: list[str]) -> dict:
    patched = copy.deepcopy(schema)
    patched["$defs"]["TemplateOption"]["properties"]["template"]["enum"] = allowed_names
    return patched


def classify_candidate(
    source_text: str, session=None, snapshot: EnabledSnapshot | None = None
) -> ClassificationResult:
    """Classify a candidate problem into compatible template options.

    When the `meta_dynamic_classifier_enabled` flag is on AND either a
    pre-loaded `snapshot` or a DB `session` is passed, this also offers every
    currently-enabled dynamic template to the classifier, and drops/stamps
    options against that snapshot. A caller classifying a batch of candidates
    in one request should load one snapshot up front and pass it via
    `snapshot=` to every call, rather than passing `session=` and letting each
    call load its own snapshot. With neither passed (the default) or the flag
    off, this is byte-identical to the pre-dynamic-classifier behavior: no
    snapshot is loaded, the system prompt and schema are unmodified, and an
    unrecognized template name raises (via `static_ref`) rather than being
    silently dropped.
    """
    settings = get_settings()
    schema = ClassificationResult.model_json_schema()
    system_prompt = _CLASSIFICATION_SYSTEM_PROMPT
    dynamic_snapshot = None

    if settings.meta_dynamic_classifier_enabled:
        if snapshot is not None:
            dynamic_snapshot = snapshot
        elif session is not None:
            dynamic_snapshot = load_enabled_snapshot(session)

    if dynamic_snapshot is not None:
        dynamic_names = sorted(dynamic_snapshot.names())
        static_names = [member.value for member in TemplateName]
        if dynamic_names:
            bullets = "\n".join(
                dynamic_snapshot.entry(name).classifier_bullet for name in dynamic_names
            )
            system_prompt = f"{_CLASSIFICATION_SYSTEM_PROMPT}\n{bullets}"
        schema = _patch_schema_enum(schema, [*static_names, *dynamic_names])

    _, result = call_with_tool(
        system_prompt=system_prompt,
        user_message=source_text,
        tools=[{"name": "classify_problem", "schema": schema}],
    )
    classification = ClassificationResult.model_validate(result)

    if dynamic_snapshot is not None:
        static_names_set = frozenset(member.value for member in TemplateName)
        allowed_names = static_names_set | dynamic_snapshot.names()
        stamped_options = []
        for option in classification.options:
            if option.template not in allowed_names:
                logger.warning(
                    "Dropping classifier option %r: not in the current template snapshot",
                    option.template,
                )
                continue
            if option.template in static_names_set:
                version_id = static_ref(option.template).version_id
            else:
                version_id = dynamic_snapshot.entry(option.template).version_id
            stamped_options.append(option.model_copy(update={"version_id": version_id}))
        classification = classification.model_copy(update={"options": stamped_options})
    else:
        classification = classification.model_copy(
            update={
                "options": [
                    option.model_copy(update={"version_id": static_ref(option.template).version_id})
                    for option in classification.options
                ]
            }
        )
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
