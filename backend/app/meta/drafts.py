import json
from datetime import datetime

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.draft_generation import DraftProposal
from app.meta.models import (
    DRAFT_PENDING_REVIEW,
    GenerationJob,
    TemplateDraft,
    TemplateDraftFixture,
    TemplateReview,
)
from app.meta.validation_pipeline import ValidatedCandidate, dsl_schema_versions

_ExpressionAdapter = TypeAdapter(ExpressionNode)


def persist_reviewable_draft(
    session: Session,
    *,
    new_id: str,
    job: GenerationJob,
    candidate: ValidatedCandidate,
    now: datetime,
    revision: int = 1,
    parent_draft_id: str | None = None,
) -> TemplateDraft:
    """Persist a candidate only after all v3 validation gates have passed."""
    if not isinstance(candidate, ValidatedCandidate):
        raise TypeError("candidate must be a ValidatedCandidate")
    if candidate.validation_report.get("passed") is not True or candidate.quality_report.get("passed") is not True:
        raise ValueError("candidate must contain passing validation and quality reports")

    proposal = candidate.proposal
    _require_matching_fixture_result_ids(proposal.fixtures, candidate.fixture_results)
    dsl_versions = dsl_schema_versions(proposal, candidate.scene_program)
    draft = TemplateDraft(
        id=new_id,
        job_id=job.id,
        fingerprint_key=job.fingerprint_key,
        fingerprint_version=job.fingerprint_version,
        fingerprint_json=job.fingerprint_json,
        revision=revision,
        parent_draft_id=parent_draft_id,
        params_document_json=proposal.params_document.model_dump_json(),
        guard_document_json=proposal.guard_document.model_dump_json(),
        answer_expression_json=proposal.answer_expression.model_dump_json(),
        teaching_plan_json=proposal.teaching_plan_document.model_dump_json(),
        scene_program_json=candidate.scene_program.model_dump_json(),
        quality_report_json=json.dumps(candidate.quality_report),
        validation_report_json=json.dumps(candidate.validation_report),
        classifier_bullet=proposal.classifier_bullet,
        dsl_schema_versions_json=json.dumps(dsl_versions),
        artifact_hash=candidate.quality_report["artifact_hash"],
        preview_artifact_hash=candidate.preview_artifact_hash,
        status=DRAFT_PENDING_REVIEW,
        created_at=now,
        updated_at=now,
    )
    session.add(draft)
    session.flush()
    persist_candidate_fixtures(
        session=session,
        draft_id=draft.id,
        proposal_fixtures=proposal.fixtures,
        fixture_results=candidate.fixture_results,
        now=now,
    )
    session.flush()
    return draft


def persist_candidate_fixtures(
    *,
    session: Session,
    draft_id: str,
    proposal_fixtures,
    fixture_results,
    now: datetime,
) -> None:
    _require_matching_fixture_result_ids(proposal_fixtures, fixture_results)

    for index, (fixture, result) in enumerate(zip(proposal_fixtures, fixture_results)):
        session.add(TemplateDraftFixture(
            id=f"{draft_id}-fixture-{index}",
            draft_id=draft_id,
            observation_id=fixture.observation_id,
            kind=fixture.kind,
            expected_outcome=fixture.expected_outcome,
            generation_method=fixture.generation_method,
            params_json=json.dumps(fixture.params),
            structural_check_passed=result.passed,
            structural_check_detail=result.detail,
            created_at=now,
        ))


def _require_matching_fixture_result_ids(proposal_fixtures, fixture_results) -> None:
    expected_ids = [f"fixture-{index}" for index, _ in enumerate(proposal_fixtures)]
    actual_ids = [result.fixture_id for result in fixture_results]
    if actual_ids != expected_ids:
        raise ValueError("fixture result ids must match proposal fixture ids")


def record_review(
    session: Session,
    *,
    new_id: str,
    draft_id: str,
    decision: str,
    reviewer_label: str,
    feedback: str | None,
    now: datetime,
    math_semantics_confirmed: bool | None = None,
) -> TemplateReview:
    review = TemplateReview(
        id=new_id,
        draft_id=draft_id,
        decision=decision,
        reviewer_label=reviewer_label,
        feedback=feedback,
        created_at=now,
        math_semantics_confirmed=math_semantics_confirmed,
    )
    session.add(review)
    session.flush()
    return review


def load_draft_documents(draft: TemplateDraft) -> DraftProposal:
    """Reconstruct persisted documents for a refinement proposal.

    Fixtures deliberately remain in their separate table; refinements generate a
    fresh fixture set after receiving the review feedback.
    """
    return DraftProposal.model_construct(
        params_document=ParamsDocument.model_validate_json(draft.params_document_json),
        guard_document=GuardDocument.model_validate_json(draft.guard_document_json),
        answer_expression=_ExpressionAdapter.validate_json(draft.answer_expression_json),
        teaching_plan_document=TeachingPlanDocument.model_validate_json(draft.teaching_plan_json),
        classifier_bullet=draft.classifier_bullet,
        fixtures=[],
    )
