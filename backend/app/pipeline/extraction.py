import logging
from fractions import Fraction
from typing import Type, TypeVar

from pydantic import BaseModel

from app.pipeline.bedrock_client import call_with_tool
from app.pipeline.grounding import check_params_grounded

logger = logging.getLogger(__name__)

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

#: The six static templates share one schema vocabulary -- operands, step
#: sequences, whole numbers -- and `_EXTRACTION_SYSTEM_PROMPT` names it directly,
#: including in its decline guidance. A dynamic template's schema has none of
#: those notions: it is an arbitrary set of described fields. Offered the static
#: prompt, a km-conversion template was declined for having "no add or subtract
#: sequence" and a "non-whole operand" -- the model quoted both criteria back as
#: its reason -- even though the value sat plainly in the text and inside the
#: field's declared range. So dynamic templates get a prompt that describes the
#: schema it is actually handed, and declines only on the one ground that
#: generalises: the problem does not contain these values.
_DYNAMIC_EXTRACTION_SYSTEM_PROMPT = (
    "Extract the values described by the given schema from the problem text. "
    "Each field's description states what it holds -- follow it, and use the "
    "field's stated bounds to decide whether a value belongs there. "
    "Report values exactly as they appear in the text; never compute or state a "
    "final answer, even when the problem asks for one. "
    "Ignore answer choices, displayed answers, and diagram labels outside the "
    "problem statement. "
    "Call decline_extraction only if the problem does not contain the values this "
    "schema describes. Do not decline because the problem's operation, wording, or "
    "number format is not one you expected -- the schema is the only contract."
)

_DECLINE_TOOL_NAME = "decline_extraction"
_DECLINE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}},
    "required": ["reason"],
}

_STATED_ANSWER_SYSTEM_PROMPT = (
    "Report only the answer the source itself states as *the* answer to this "
    "problem -- one explicitly labelled as the answer, presented after an "
    "equals sign, or otherwise unambiguously identified. Ignore answer "
    "choices, distractors, worked examples for other problems, and any label "
    "that could plausibly be a hint or a step. If no answer is unambiguously "
    "stated, call decline_stated_answer. Return the answer as a "
    "rational-number string (for example '9' or '3/4') and the exact "
    "substring of the source in which it appears."
)

_STATED_ANSWER_REPORT_TOOL = "report_stated_answer"
_STATED_ANSWER_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": "string"},
        "source_span": {"type": "string"},
    },
    "required": ["value", "source_span"],
}

_STATED_ANSWER_DECLINE_TOOL = "decline_stated_answer"


def _system_prompt_for(params_cls: Type[T]) -> str:
    """Which extraction vocabulary this params class should be read against.

    Keyed on the compiled dynamic base rather than on a template-name lookup, so
    every future dynamic template gets the schema-driven prompt by construction
    instead of by anyone remembering to register it. Imported lazily: `app.meta`
    pulls in the DSL and its DB models, and the pipeline must not depend on that
    at import time -- `app.templates.registry.get_template` defers the same way.
    """
    from app.meta.dsl.params import TemplateParamsBase

    if isinstance(params_cls, type) and issubclass(params_cls, TemplateParamsBase):
        return _DYNAMIC_EXTRACTION_SYSTEM_PROMPT
    return _EXTRACTION_SYSTEM_PROMPT


def _problem_statement(source_text: str) -> str:
    statement, question_mark, _ = source_text.rpartition("?")
    return f"{statement}{question_mark}" if question_mark else source_text


def extract_params(source_text: str, params_cls: Type[T]) -> T:
    schema = params_cls.model_json_schema()
    tool_name, result = call_with_tool(
        system_prompt=_system_prompt_for(params_cls),
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


def extract_stated_answer(source_text: str) -> tuple[Fraction, str] | None:
    try:
        tool_name, result = call_with_tool(
            system_prompt=_STATED_ANSWER_SYSTEM_PROMPT,
            user_message=source_text,
            tools=[
                {"name": _STATED_ANSWER_REPORT_TOOL, "schema": _STATED_ANSWER_REPORT_SCHEMA},
                {"name": _STATED_ANSWER_DECLINE_TOOL, "schema": _DECLINE_TOOL_SCHEMA},
            ],
        )
    except Exception:
        logger.warning("Stated-answer extraction call failed", exc_info=True)
        return None
    if tool_name != _STATED_ANSWER_REPORT_TOOL:
        return None
    value_str = result.get("value", "")
    span = result.get("source_span", "")
    if not span or span not in source_text:
        return None
    try:
        value = Fraction(value_str)
    except (ValueError, ZeroDivisionError):
        return None
    return value, span
