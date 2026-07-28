import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.config import get_settings
from app.meta.db import meta_session
from app.meta.draft_generation import DraftProposal, propose_template_draft
from app.meta.drafts import create_generated_draft
from app.meta.fingerprint import Fingerprint
from app.meta.fixture_mutation import ensure_negative_fixtures
from app.meta.jobs import claim_next_job, complete_job, fail_job
from app.meta.models import FallbackObservation, TemplateDraft
from app.meta.validation_pipeline import persist_validation

logger = logging.getLogger(__name__)


def _load_observations(session, observation_ids: list[str]) -> list[FallbackObservation]:
    if not observation_ids:
        return []
    return (
        session.query(FallbackObservation)
        .filter(FallbackObservation.id.in_(observation_ids))
        .all()
    )


def generate_and_validate_revision(
    *,
    job,
    fingerprint: Fingerprint,
    observations: list[FallbackObservation],
    prior_proposal: DraftProposal | None = None,
    reviewer_feedback: str | None = None,
    revision: int = 1,
    parent_draft_id: str | None = None,
) -> TemplateDraft:
    proposal = propose_template_draft(
        fingerprint, observations, prior_proposal=prior_proposal, reviewer_feedback=reviewer_feedback,
    )
    proposal.fixtures = ensure_negative_fixtures(proposal.params_document, proposal.fixtures)

    now = datetime.now(timezone.utc)
    with meta_session() as session:
        draft = create_generated_draft(
            session, new_id=uuid4().hex, job=job, proposal=proposal, now=now,
            revision=revision, parent_draft_id=parent_draft_id,
        )
        observations_by_id = {obs.id: obs for obs in observations}
        persist_validation(session, draft, observations_by_id, now, get_settings().meta_artifact_root)
        # persist_validation mutates `draft` in-memory only (no flush of its own).
        # session.refresh() reloads attributes straight from the DB and does not
        # autoflush pending changes on the object being refreshed, so without an
        # explicit flush() here it silently discards the validation outcome and
        # reverts draft.status back to its last-flushed value ("generated").
        session.flush()
        session.refresh(draft)
        return draft


def run_generation_job(*, owner: str) -> TemplateDraft | None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    with meta_session() as session:
        job = claim_next_job(session, owner=owner, lease_seconds=settings.job_lease_seconds, now=now)
        if job is None:
            return None
        job_id = job.id
        fingerprint = Fingerprint.model_validate_json(job.fingerprint_json)
        observations = _load_observations(session, json.loads(job.trigger_observation_ids))

    try:
        draft = generate_and_validate_revision(job=job, fingerprint=fingerprint, observations=observations)
    except Exception as exc:
        with meta_session() as session:
            fail_job(
                session, job_id=job_id, owner=owner, error_summary=str(exc),
                backoff_base_seconds=settings.job_backoff_base_seconds,
                max_attempts=settings.job_max_attempts, now=datetime.now(timezone.utc),
            )
        logger.warning("Draft generation failed for job %s", job_id, exc_info=True)
        return None

    with meta_session() as session:
        complete_job(session, job_id=job_id, owner=owner, now=datetime.now(timezone.utc))
    return draft
