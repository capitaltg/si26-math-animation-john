import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
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
    animation_document: AnimationDocument
    classifier_bullet: str = Field(max_length=MAX_CLASSIFIER_BULLET_LENGTH)
    fixtures: list[ProposedFixture] = Field(min_length=MIN_PROPOSED_FIXTURES, max_length=MAX_PROPOSED_FIXTURES)


_DRAFT_SYSTEM_PROMPT = (
    "You propose a declarative K-8 math animation template by calling the "
    "propose_template_draft tool. Output only bounded JSON: a params field "
    "schema, guard predicates over a closed expression DSL, one answer "
    "expression computing the correct numeric result from params, an "
    "animation document built only from the closed library of layout/visual/"
    "animation primitives already described in the tool schema, one "
    "classifier contract bullet describing when this template applies, and "
    "example fixtures (positive/negative/boundary) with the params values "
    "that make each fixture true. Never invent a field type, predicate, or "
    "animation node kind outside the schema. Never emit prose, code, "
    "imports, or file paths. A fixture's observation_id must be one of the "
    "candidate ids given to you, or null.\n\n"
    "The animation document MUST use animation_version 2. Static label text "
    "never interpolates braces or evaluates expressions; use expression_label "
    "for dynamic values. The animation MUST visibly contain an answer-role "
    "expression_label whose expression exactly matches answer_expression. For "
    "length and width problems, use the rectangle node with expression-backed "
    "dimensions instead of counting visuals.\n\n"
    "The animation document MUST actually display its content over time, or it "
    "renders a blank frame and cannot be published. Layout and visual nodes "
    "(row, column, label, grid, tally_marks, object_set, ...) only BUILD a "
    "mobject; they do not show it. Every visual you want on screen must be "
    "given a 'ref' and then revealed by an 'appear' node targeting that ref, "
    "held on screen with a 'wait' node. Structure the animation as a "
    "'sequence' whose steps interleave building a visual, an 'appear' of it, "
    "and a 'wait'. Include at least one 'appear' and at least one 'wait'; an "
    "animation with no appear/wait nodes is invalid.\n\n"
    "A sequence controls time, not spatial position. Manim places independently "
    "built visuals at the frame center, so appearing several independent sequence "
    "children makes them overlap. When displaying more than one persistent visual, "
    "build every appeared visual inside one shared row, column, overlay, align, or "
    "padding layout tree. You may progressively appear positioned descendants of "
    "that shared tree. Do not create multiple independent layout trees for visuals "
    "that remain on screen together.\n\n"
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
    "params_document", "guard_document", "answer_expression", "animation_document", "fixtures",
)


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


def propose_template_draft(
    fingerprint: Fingerprint,
    observations: list[FallbackObservation],
    *,
    prior_proposal: DraftProposal | None = None,
    reviewer_feedback: str | None = None,
) -> DraftProposal:
    user_message = (
        f"fingerprint={fingerprint.model_dump_json()}\n\n"
        f"observations:\n{_observation_context(observations)}"
    )
    if prior_proposal is not None and reviewer_feedback:
        user_message += (
            f"\n\nprior proposal:\n{prior_proposal.model_dump_json()}"
            f"\n\nreviewer feedback to address:\n{reviewer_feedback}"
        )
    _, raw = call_with_tool(
        system_prompt=_DRAFT_SYSTEM_PROMPT,
        user_message=user_message,
        tools=[{"name": "propose_template_draft", "schema": DraftProposal.model_json_schema()}],
    )
    proposal = DraftProposal.model_validate(_coerce_stringified_json_fields(raw))
    if proposal.animation_document.animation_version != 2:
        raise ValueError("generated animation_document must use animation_version 2")
    observation_ids = {observation.id for observation in observations}
    for fixture in proposal.fixtures:
        if fixture.observation_id is not None and fixture.observation_id not in observation_ids:
            raise ValueError(f"fixture references unknown observation_id: {fixture.observation_id}")
    return proposal
