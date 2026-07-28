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
    "candidate ids given to you, or null."
)


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
    return DraftProposal.model_validate(raw)
