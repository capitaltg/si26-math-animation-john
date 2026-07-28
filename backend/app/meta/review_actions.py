import json
from datetime import datetime, timezone
from uuid import uuid4

from app.meta.db import meta_session
from app.meta.drafts import load_draft_documents, record_review
from app.meta.fingerprint import Fingerprint
from app.meta.generation_pipeline import generate_and_validate_revision
from app.meta.jobs import mark_needs_manual
from app.meta.models import (
    DRAFT_FAILED_VALIDATION,
    DRAFT_PENDING_REVIEW,
    DRAFT_REJECTED,
    FallbackObservation,
    GenerationJob,
    TemplateDraft,
)


class DraftNotRefinableError(Exception):
    pass


class DraftRefinementFailedError(Exception):
    pass


_REFINABLE_STATUSES = {DRAFT_PENDING_REVIEW, DRAFT_FAILED_VALIDATION}


def reject_and_refine(
    draft_id: str, *, feedback: str, reviewer_label: str, max_refinements: int
) -> TemplateDraft | None:
    now = datetime.now(timezone.utc)
    with meta_session() as session:
        draft = session.get(TemplateDraft, draft_id)
        if draft is None or draft.status not in _REFINABLE_STATUSES:
            raise DraftNotRefinableError(f"draft {draft_id} is not in a refinable state")

        record_review(
            session, new_id=uuid4().hex, draft_id=draft.id, decision="reject",
            reviewer_label=reviewer_label, feedback=feedback, now=now,
        )
        draft.status = DRAFT_REJECTED
        draft.reviewer_feedback = feedback
        draft.updated_at = now
        session.flush()

        if draft.revision >= max_refinements:
            mark_needs_manual(session, job_id=draft.job_id, now=now)
            return None

        job = session.get(GenerationJob, draft.job_id)
        prior_proposal = load_draft_documents(draft)
        trigger_ids = json.loads(job.trigger_observation_ids)
        observations = (
            session.query(FallbackObservation).filter(FallbackObservation.id.in_(trigger_ids)).all()
            if trigger_ids
            else []
        )
        revision = draft.revision
        parent_draft_id = draft.id

    # `job` (a GenerationJob ORM instance) remains readable after the
    # `with meta_session()` block exits because meta_session()'s sessionmaker
    # is built with expire_on_commit=False (see app/meta/db.py) — the same
    # pattern app/meta/generation_pipeline.py:run_generation_job already
    # relies on when passing `job` across session boundaries.
    try:
        return generate_and_validate_revision(
            job=job,
            fingerprint=Fingerprint.model_validate_json(job.fingerprint_json),
            observations=observations,
            prior_proposal=prior_proposal,
            reviewer_feedback=feedback,
            revision=revision + 1,
            parent_draft_id=parent_draft_id,
        )
    except Exception as exc:
        with meta_session() as session:
            draft = session.get(TemplateDraft, draft_id)
            if draft is not None and draft.status == DRAFT_REJECTED:
                draft.status = DRAFT_PENDING_REVIEW
                draft.updated_at = datetime.now(timezone.utc)
        raise DraftRefinementFailedError(
            "draft refinement failed; the draft was restored to pending review and can be retried"
        ) from exc
