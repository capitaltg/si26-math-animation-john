import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.fingerprint import Fingerprint
from app.meta.models import FallbackObservation
from app.pipeline.bedrock_client import call_with_tool

MAX_CLASSIFIER_BULLET_LENGTH = 400
MIN_PROPOSED_FIXTURES = 1
MAX_PROPOSED_FIXTURES = 20


class ProposedFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["positive", "negative", "boundary"]
    expected_outcome: Literal["accept", "reject"]
    generation_method: Literal["proposed", "mutated"] = "proposed"
    observation_id: str | None = None
    params: dict = Field(default_factory=dict)


class DraftProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    params_document: ParamsDocument
    guard_document: GuardDocument
    answer_expression: ExpressionNode
    teaching_plan_document: TeachingPlanDocument
    classifier_bullet: str = Field(max_length=MAX_CLASSIFIER_BULLET_LENGTH)
    fixtures: list[ProposedFixture] = Field(min_length=MIN_PROPOSED_FIXTURES, max_length=MAX_PROPOSED_FIXTURES)


_DRAFT_SYSTEM_PROMPT = (
    "You propose a declarative K-8 math teaching template by calling the "
    "propose_template_draft tool. Output only bounded JSON: a params field "
    "schema, guard predicates over a closed expression DSL, one answer "
    "expression computing the correct numeric result from params, "
    "a semantic teaching plan, one "
    "classifier contract bullet describing when this template applies, and "
    "example fixtures (positive/negative/boundary) with the params values "
    "that make each fixture true. Never invent a field type, predicate, or "
    "teaching-plan node kind outside the schema. Never emit prose, code, "
    "imports, or file paths. A fixture's observation_id must be one of the "
    "candidate ids given to you, or null.\n\n"
    "The teaching_plan_document MUST use plan_version 3 and describe three to "
    "five teaching beats. Prefer semantic strategy over custom actions, and use "
    "custom actions only inside their owning beat. The system supplies the "
    "answer statement and stages it for you: it appears from the first beat as "
    "an unresolved \"? unit\", shows its arithmetic at the derive beat, and "
    "resolves to the value only at conclude. Name the unit of the result in "
    "answer_unit (\"meters\"; empty if unitless). Never author a label standing "
    "in for the answer, and never put \"?\" in a label. "
    "Simple collections reveal together. Perimeter explanations use "
    "boundary_trace. Median ordered values use item-specific targets. "
    "A pair_elimination plan does not write its own elimination: give it exactly "
    "one organize beat, a focus beat after it whose only target is the middle "
    "item, and no dim, emphasize, or restore action on any item of the primary "
    "visual. "
    "A custom "
    "trace or move action's path_ref must be visual_ref.path_name; the only "
    "declared path today is perimeter, on rectangle_measurement visuals only "
    "-- address any other sub-part (an edge, vertex, or item) through a "
    "target's part and index, never through path_ref. Never "
    "include URLs, raw controls, positions, durations beyond requested bounded "
    "actions, colors, code, renderer objects, or Manim concepts.\n\n"
    "Provide at least one 'positive' fixture whose observation_id references a "
    "given candidate id and whose params are the exact values stated in that "
    "candidate's excerpt -- this is the fixture a human verifies before "
    "publishing. Do NOT emit positive fixtures with a null observation_id; a "
    "positive example that is not grounded in a real observation cannot be "
    "verified and will be discarded. Keep the guard predicates to the genuine "
    "mathematical preconditions of the template; do not add incidental "
    "constraints (such as requiring one field to be larger than another) that "
    "the problem statement does not actually require."
)


_STRUCTURED_PROPOSAL_FIELDS = (
    "params_document", "guard_document", "answer_expression", "teaching_plan_document", "fixtures",
)

_STABLE_REPAIR_FEEDBACK_FIELDS = ("code", "path", "hint")


def _coerce_stringified_json_fields(raw: dict) -> dict:
    """Bedrock tool-use output occasionally stringifies a nested object/array
    field instead of emitting it inline (seen so far on ``answer_expression``,
    whose schema is a recursive discriminated union). Undo that one layer of
    over-serialization before handing the payload to pydantic.

    Restricted to the known structured (non-``str``) fields on
    ``DraftProposal`` so a ``classifier_bullet`` string that happens to parse
    as JSON (e.g. quoting a set like ``{2,3,4}``) is never coerced away from
    the ``str`` its schema requires.
    """
    coerced = dict(raw)
    for key in _STRUCTURED_PROPOSAL_FIELDS:
        value = raw.get(key)
        if not isinstance(value, str):
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            coerced[key] = parsed
    return coerced


def _observation_context(observations: list[FallbackObservation]) -> str:
    lines = [
        f"- id={obs.id} grade={obs.grade_level}: {obs.source_excerpt}" for obs in observations
    ]
    return "\n".join(lines)


def _reviewer_feedback_context(reviewer_feedback: str | dict[str, object]) -> str:
    if isinstance(reviewer_feedback, str):
        return reviewer_feedback
    normalized = {}
    for field in _STABLE_REPAIR_FEEDBACK_FIELDS:
        value = reviewer_feedback.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("structured reviewer feedback requires code, path, and hint")
        normalized[field] = value.strip()
    return json.dumps(normalized, separators=(",", ":"), sort_keys=True)


def propose_template_draft(
    fingerprint: Fingerprint,
    observations: list[FallbackObservation],
    *,
    prior_proposal: DraftProposal | None = None,
    reviewer_feedback: str | dict[str, object] | None = None,
) -> DraftProposal:
    user_message = (
        f"fingerprint={fingerprint.model_dump_json()}\n\n"
        f"observations:\n{_observation_context(observations)}"
    )
    if reviewer_feedback is not None:
        # A draft that never parsed leaves no prior proposal to echo back, but the
        # feedback still has to reach the model or the retry repeats the same mistake.
        if prior_proposal is not None:
            user_message += f"\n\nprior proposal:\n{prior_proposal.model_dump_json()}"
        user_message += (
            f"\n\nreviewer feedback to address:\n{_reviewer_feedback_context(reviewer_feedback)}"
        )
    _, raw = call_with_tool(
        system_prompt=_DRAFT_SYSTEM_PROMPT,
        user_message=user_message,
        tools=[{"name": "propose_template_draft", "schema": DraftProposal.model_json_schema()}],
    )
    proposal = DraftProposal.model_validate(_coerce_stringified_json_fields(raw))
    if proposal.teaching_plan_document.plan_version != 3:
        raise ValueError("generated teaching_plan_document must use plan_version 3")
    observation_ids = {observation.id for observation in observations}
    for fixture in proposal.fixtures:
        if fixture.observation_id is not None and fixture.observation_id not in observation_ids:
            raise ValueError(f"fixture references unknown observation_id: {fixture.observation_id}")
    return proposal
