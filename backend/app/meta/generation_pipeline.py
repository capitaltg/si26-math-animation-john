import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from app.config import get_settings
from app.meta.db import meta_session
from app.meta.draft_generation import DraftProposal, propose_template_draft
from app.meta.drafts import persist_reviewable_draft
from app.meta.dsl.v3_common import CompileContext
from app.meta.fingerprint import Fingerprint
from app.meta.fixture_mutation import drop_ungrounded_positive_fixtures, ensure_negative_fixtures
from app.meta.jobs import claim_next_job, complete_job, fail_job, mark_needs_manual
from app.meta.models import FallbackObservation, TemplateDraft
from app.meta.validation_pipeline import validate_candidate
from app.meta.v3.errors import V3Failure, V3ValidationError

logger = logging.getLogger(__name__)

_PUBLIC_EXHAUSTION_CODE = "automatic_generation_needs_manual_authoring"


class CandidateGenerationExhausted(RuntimeError):
    """Automatic generation exhausted validation retries without a persistable draft."""

    public_code = _PUBLIC_EXHAUSTION_CODE

    def __init__(self, last_failure: V3Failure):
        super().__init__("meta-template generation exhausted automatic validation retries")
        self.last_failure = last_failure

    def structured_report(self) -> dict[str, str]:
        return {
            "code": self.last_failure.code,
            "path": self.last_failure.path,
            "expected": self.last_failure.expected,
            "observed": self.last_failure.observed,
            "hint": self.last_failure.hint,
        }


_MAX_REPORTED_SCHEMA_ERRORS = 3


def _error_path(location) -> str:
    return ".".join(str(part) for part in location)


def _schema_failure(exc: ValidationError) -> V3Failure:
    """Turn an off-schema tool response into repair feedback the model can act on."""
    errors = exc.errors()
    reported = "; ".join(
        f"{_error_path(error['loc'])}: {error['msg']}" for error in errors[:_MAX_REPORTED_SCHEMA_ERRORS]
    )
    return V3Failure(
        code="draft_schema_invalid",
        path=_error_path(errors[0]["loc"]) or "draft_proposal",
        expected="a proposal that satisfies the propose_template_draft tool schema",
        observed=f"{len(errors)} schema violation(s)",
        hint=f"re-emit the draft with these fields corrected -- {reported}",
    )


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
    reviewer_feedback: str | dict[str, str] | None = None,
    revision: int = 1,
    parent_draft_id: str | None = None,
) -> TemplateDraft:
    """Generate, validate entirely in memory, then persist one passing candidate."""
    feedback = reviewer_feedback
    prior = prior_proposal
    observations_by_id = {observation.id: observation for observation in observations}
    last_failure: V3Failure | None = None

    for _ in range(get_settings().meta_draft_generation_max_attempts):
        try:
            proposal = propose_template_draft(
                fingerprint,
                observations,
                prior_proposal=prior,
                reviewer_feedback=feedback,
            )
        except ValidationError as exc:
            last_failure = _schema_failure(exc)
            feedback = {
                "code": last_failure.code,
                "path": last_failure.path,
                "hint": last_failure.hint,
            }
            continue
        proposal.fixtures = drop_ungrounded_positive_fixtures(proposal.fixtures)
        proposal.fixtures = ensure_negative_fixtures(proposal.params_document, proposal.fixtures)
        compile_context = CompileContext(
            concept_family=f"{fingerprint.operation_family}_{fingerprint.representation_family}",
            grade_band=fingerprint.grade_band,
        )
        try:
            candidate = validate_candidate(
                proposal,
                observations_by_id=observations_by_id,
                artifact_root=get_settings().meta_artifact_root,
                compile_context=compile_context,
            )
        except V3ValidationError as exc:
            last_failure = exc.failure
            prior = proposal
            feedback = {
                "code": exc.failure.code,
                "path": exc.failure.path,
                "hint": exc.failure.hint,
            }
            continue

        with meta_session() as session:
            return persist_reviewable_draft(
                session,
                new_id=uuid4().hex,
                job=job,
                candidate=candidate,
                now=datetime.now(timezone.utc),
                revision=revision,
                parent_draft_id=parent_draft_id,
            )

    assert last_failure is not None
    raise CandidateGenerationExhausted(last_failure)


def run_generation_job(*, owner: str) -> TemplateDraft | None:
    settings = get_settings()
    if not settings.meta_templates_enabled or not settings.meta_codegen_enabled:
        return None

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
    except CandidateGenerationExhausted as exc:
        structured_report = exc.structured_report()
        logger.warning(
            "Draft generation exhausted automatic validation retries for job %s: %s",
            job_id,
            json.dumps(structured_report, sort_keys=True),
        )
        with meta_session() as session:
            if mark_needs_manual(session, job_id=job_id, now=datetime.now(timezone.utc)):
                session.get(type(job), job_id).error_summary = exc.public_code
        return None
    except Exception as exc:
        with meta_session() as session:
            fail_job(
                session,
                job_id=job_id,
                owner=owner,
                error_summary=str(exc),
                backoff_base_seconds=settings.job_backoff_base_seconds,
                max_attempts=settings.job_max_attempts,
                now=datetime.now(timezone.utc),
            )
        logger.warning("Draft generation failed for job %s", job_id, exc_info=True)
        return None

    with meta_session() as session:
        complete_job(session, job_id=job_id, owner=owner, now=datetime.now(timezone.utc))
    return draft
