import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.draft_generation import DraftProposal
from app.meta.draft_hash import compute_artifact_hash
from app.meta.models import DRAFT_GENERATED, DRAFT_SUPERSEDED, GenerationJob, TemplateDraft, TemplateDraftFixture, TemplateReview
from app.meta.versions import DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION

from pydantic import TypeAdapter

_ExpressionAdapter = TypeAdapter(ExpressionNode)


def create_generated_draft(
    session: Session,
    *,
    new_id: str,
    job: GenerationJob,
    proposal: DraftProposal,
    now: datetime,
    revision: int = 1,
    parent_draft_id: str | None = None,
    fixture_ids: list[str] | None = None,
) -> TemplateDraft:
    dsl_versions = {
        "params_version": proposal.params_document.params_version,
        "guard_version": proposal.guard_document.guard_version,
        "animation_version": proposal.animation_document.animation_version,
    }
    artifact_hash = compute_artifact_hash(
        params_document=proposal.params_document.model_dump(mode="json"),
        guard_document=proposal.guard_document.model_dump(mode="json"),
        answer_expression=proposal.answer_expression.model_dump(mode="json"),
        animation_document=proposal.animation_document.model_dump(mode="json"),
        classifier_bullet=proposal.classifier_bullet,
        dsl_schema_versions=dsl_versions,
        compiler_version=DSL_COMPILER_VERSION,
        renderer_version=DYNAMIC_RENDERER_VERSION,
    )
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
        animation_document_json=proposal.animation_document.model_dump_json(),
        classifier_bullet=proposal.classifier_bullet,
        dsl_schema_versions_json=json.dumps(dsl_versions),
        artifact_hash=artifact_hash,
        status=DRAFT_GENERATED,
        created_at=now,
        updated_at=now,
    )
    session.add(draft)
    session.flush()

    ids = fixture_ids or [f"{new_id}-fixture-{i}" for i in range(len(proposal.fixtures))]
    if len(ids) != len(proposal.fixtures):
        raise ValueError("fixture_ids must have one entry per proposal fixture")
    for fixture_id, fixture in zip(ids, proposal.fixtures):
        session.add(TemplateDraftFixture(
            id=fixture_id,
            draft_id=draft.id,
            observation_id=fixture.observation_id,
            kind=fixture.kind,
            expected_outcome=fixture.expected_outcome,
            generation_method=fixture.generation_method,
            params_json=json.dumps(fixture.params),
            created_at=now,
        ))
    session.flush()
    return draft


def supersede_and_refine(
    session: Session,
    *,
    draft: TemplateDraft,
    proposal: DraftProposal,
    new_id: str,
    now: datetime,
    fixture_ids: list[str] | None = None,
) -> TemplateDraft:
    draft.status = DRAFT_SUPERSEDED
    draft.updated_at = now
    session.flush()

    job = session.get(GenerationJob, draft.job_id)
    return create_generated_draft(
        session, new_id=new_id, job=job, proposal=proposal, now=now,
        revision=draft.revision + 1, parent_draft_id=draft.id, fixture_ids=fixture_ids,
    )


def record_review(
    session: Session,
    *,
    new_id: str,
    draft_id: str,
    decision: str,
    reviewer_label: str,
    feedback: str | None,
    now: datetime,
) -> TemplateReview:
    review = TemplateReview(
        id=new_id, draft_id=draft_id, decision=decision,
        reviewer_label=reviewer_label, feedback=feedback, created_at=now,
    )
    session.add(review)
    session.flush()
    return review


def load_draft_documents(draft: TemplateDraft) -> DraftProposal:
    # DraftProposal.fixtures enforces min_length=MIN_PROPOSED_FIXTURES (>=1) for
    # freshly-generated proposals (see draft_generation.py). This reconstruction
    # deliberately omits fixtures (they live in a separate table and aren't needed
    # here — see the docstring/brief), so build via model_construct to skip that
    # constraint rather than re-validating already-persisted, already-valid
    # sub-documents against a rule that doesn't apply to this use case.
    return DraftProposal.model_construct(
        params_document=ParamsDocument.model_validate_json(draft.params_document_json),
        guard_document=GuardDocument.model_validate_json(draft.guard_document_json),
        answer_expression=_ExpressionAdapter.validate_json(draft.answer_expression_json),
        animation_document=AnimationDocument.model_validate_json(draft.animation_document_json),
        classifier_bullet=draft.classifier_bullet,
        fixtures=[],
    )
