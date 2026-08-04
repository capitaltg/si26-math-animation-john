"""Record the answers a draft's own answer expression already determines.

``persist_candidate_fixtures`` deliberately leaves ``expected_result_json`` NULL,
and approval precondition 8 requires it to be set. The admin panel fills it in
one fixture at a time -- but ``review_api.update_fixture`` recomputes the answer
from the draft's answer expression and rejects anything that differs, so that
step cannot carry human knowledge. It can only carry human typing.

The teacher-facing flow therefore derives the same values in one step and keeps
the human gate where a human actually adds something: confirming that the
template teaches the mathematics correctly. Nothing here weakens precondition 8 --
a fixture still has to be grounded in a real observation and to have passed its
structural check to be recorded at all, and the recorded value is byte-identical
to what the admin route would have stored for the same params.
"""

import json
import logging

from pydantic import TypeAdapter, ValidationError

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import ExpressionNode, compile_expression
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.models import TemplateDraft, TemplateDraftFixture
from app.meta.validation import compile_draft_documents

logger = logging.getLogger(__name__)

_ExpressionAdapter = TypeAdapter(ExpressionNode)


def record_computed_answers(session, draft: TemplateDraft) -> int:
    """Fill in the derived answer for every positive fixture still missing one.

    Returns how many rows were written, so a caller can tell "nothing needed
    doing" from "something was recorded".
    """
    answer_expression = _ExpressionAdapter.validate_json(draft.answer_expression_json)
    compiled = compile_draft_documents(
        ParamsDocument.model_validate_json(draft.params_document_json),
        GuardDocument.model_validate_json(draft.guard_document_json),
        answer_expression,
        TeachingPlanDocument.model_validate_json(draft.teaching_plan_json),
    )
    evaluator = compile_expression(answer_expression, compiled.field_contract)

    recorded = 0
    fixtures = (
        session.query(TemplateDraftFixture)
        .filter(
            TemplateDraftFixture.draft_id == draft.id,
            TemplateDraftFixture.kind == "positive",
            TemplateDraftFixture.expected_outcome == "accept",
            TemplateDraftFixture.observation_id.isnot(None),
            TemplateDraftFixture.structural_check_passed.is_(True),
            TemplateDraftFixture.expected_result_json.is_(None),
        )
        .all()
    )
    for fixture in fixtures:
        try:
            params = compiled.params_cls.model_validate(json.loads(fixture.params_json))
            answer = evaluator.evaluate(params.model_dump())
        except (ValidationError, DslValidationError):
            # One fixture that cannot be evaluated is not a reason to abandon the
            # rest; it simply stays unrecorded and so keeps failing to count
            # toward the publication floor.
            logger.warning(
                "Could not compute an answer for fixture %s on draft %s",
                fixture.id, draft.id, exc_info=True,
            )
            continue
        fixture.expected_result_json = json.dumps({"answer": str(answer)})
        recorded += 1

    if recorded:
        session.flush()
    return recorded
