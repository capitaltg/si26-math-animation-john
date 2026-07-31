"""Re-run the v3 validation pipeline for a draft whose evidence was cleared.

``review_api.update_fixture`` clears every piece of approval evidence when a
reviewer actually changes a fixture's params: render evidence produced for the
old params must not survive the edit, and approval preconditions 3, 5 and 8
(``app/meta/approval.py``) all require that evidence. Without a way to rebuild
it the corrected draft could never leave ``pending_review``, and the only way
forward -- reject and regenerate -- discarded the correction (issue #63).

This module rebuilds it in place. It re-runs the same ``validate_candidate``
that produced the draft, against the reviewer's edited fixtures, and writes the
resulting evidence back onto the existing draft. Nothing here re-generates or
re-proposes: the reviewer's fixture set is authoritative, so the generation-time
fixture repairs (``drop_ungrounded_positive_fixtures`` /
``ensure_negative_fixtures``) are deliberately not re-run, and
``expected_result_json`` is left alone -- ``update_fixture`` is its only writer.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import TypeAdapter

from app.config import get_settings
from app.meta.db import meta_session
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.dsl.expression import ExpressionNode
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.fingerprint import Fingerprint
from app.meta.models import (
    DRAFT_PENDING_REVIEW,
    FallbackObservation,
    TemplateDraft,
    TemplateDraftFixture,
)
from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.validation_pipeline import dsl_schema_versions, validate_candidate

_ExpressionAdapter = TypeAdapter(ExpressionNode)


class RevalidationError(Exception):
    """Base class for all revalidation failures."""


class RevalidationDraftNotFoundError(RevalidationError):
    """The draft id does not exist (maps to HTTP 404)."""


class DraftNotRevalidatableError(RevalidationError):
    """The draft is not in ``pending_review`` (maps to HTTP 409)."""


class RevalidationFailedError(RevalidationError):
    """The candidate no longer validates (maps to HTTP 422).

    Carries the structured ``V3Failure`` and renders it as one line, because
    the review panel puts the response detail straight into text.
    """

    def __init__(self, failure: V3Failure):
        super().__init__(
            f"Revalidation failed at {failure.path} ({failure.code}): "
            f"expected {failure.expected}, observed {failure.observed} -- {failure.hint}"
        )
        self.failure = failure


@dataclass(frozen=True)
class _ObservationExcerpt:
    """The only thing fixture validation needs from an observation.

    Copied out of the session so the grounding check can read it after the read
    transaction closes -- a committed ORM instance has expired attributes.
    """

    source_excerpt: str | None


def revalidate_draft(draft_id: str) -> None:
    """Rebuild a pending draft's validation evidence from its current fixtures.

    Raises ``RevalidationFailedError`` if the draft no longer validates; in that
    case nothing is written, so the draft keeps its cleared evidence and stays
    unapprovable rather than persisting a failing report.
    """
    settings = get_settings()

    with meta_session() as session:
        draft = _require_pending_draft(session, draft_id)
        fixtures = _ordered_fixtures(session, draft_id)
        # Fixture ids are captured in the same order the proposal is built in,
        # so the structural results can be mapped back positionally.
        fixture_ids = [fixture.id for fixture in fixtures]
        proposal = _proposal_from_draft(draft, fixtures)
        observations_by_id = _observation_excerpts(session, fixtures)
        fingerprint = Fingerprint.model_validate_json(draft.fingerprint_json)

    compile_context = CompileContext(
        concept_family=f"{fingerprint.operation_family}_{fingerprint.representation_family}",
        grade_band=fingerprint.grade_band,
    )
    # Validated with no session held: this renders a preview through a manim
    # subprocess, exactly as `generation_pipeline.generate_and_validate_revision`
    # does outside its own session.
    try:
        candidate = validate_candidate(
            proposal,
            observations_by_id=observations_by_id,
            artifact_root=settings.meta_artifact_root,
            compile_context=compile_context,
        )
    except V3ValidationError as exc:
        raise RevalidationFailedError(exc.failure) from exc

    with meta_session() as session:
        # Re-checked because the render above ran outside any transaction: a
        # concurrent approve or reject may have decided the draft meanwhile, and
        # evidence must never be written onto a decided draft.
        draft = _require_pending_draft(session, draft_id)
        _write_evidence(session, draft, fixture_ids, candidate)


def _require_pending_draft(session, draft_id: str) -> TemplateDraft:
    draft = session.get(TemplateDraft, draft_id)
    if draft is None:
        raise RevalidationDraftNotFoundError(f"Unknown draft {draft_id}")
    if draft.status != DRAFT_PENDING_REVIEW:
        raise DraftNotRevalidatableError(
            f"Draft {draft_id} cannot be revalidated in status {draft.status}"
        )
    return draft


def _ordered_fixtures(session, draft_id: str) -> list[TemplateDraftFixture]:
    # Any stable order works -- the proposal, the report's positional fixture
    # ids and the write-back all derive from this one list -- but ordering by id
    # keeps two revalidations of the same draft byte-identical.
    return (
        session.query(TemplateDraftFixture)
        .filter_by(draft_id=draft_id)
        .order_by(TemplateDraftFixture.id)
        .all()
    )


def _proposal_from_draft(draft: TemplateDraft, fixtures) -> DraftProposal:
    return DraftProposal(
        params_document=ParamsDocument.model_validate_json(draft.params_document_json),
        guard_document=GuardDocument.model_validate_json(draft.guard_document_json),
        answer_expression=_ExpressionAdapter.validate_json(draft.answer_expression_json),
        teaching_plan_document=TeachingPlanDocument.model_validate_json(draft.teaching_plan_json),
        classifier_bullet=draft.classifier_bullet,
        fixtures=[
            ProposedFixture(
                kind=fixture.kind,
                expected_outcome=fixture.expected_outcome,
                generation_method=fixture.generation_method,
                observation_id=fixture.observation_id,
                params=json.loads(fixture.params_json),
            )
            for fixture in fixtures
        ],
    )


def _observation_excerpts(session, fixtures) -> dict[str, _ObservationExcerpt]:
    observation_ids = {
        fixture.observation_id for fixture in fixtures if fixture.observation_id
    }
    if not observation_ids:
        return {}
    rows = (
        session.query(FallbackObservation)
        .filter(FallbackObservation.id.in_(observation_ids))
        .all()
    )
    return {row.id: _ObservationExcerpt(source_excerpt=row.source_excerpt) for row in rows}


def _write_evidence(session, draft: TemplateDraft, fixture_ids: list[str], candidate) -> None:
    draft.validation_report_json = json.dumps(candidate.validation_report)
    draft.quality_report_json = json.dumps(candidate.quality_report)
    draft.preview_artifact_hash = candidate.preview_artifact_hash
    # Fixture params are not inputs to `compute_candidate_hash`, so in the
    # ordinary case these three rewrite what is already there. They matter only
    # if the compiler or renderer version moved on since generation: then the
    # reports, the scene program and the hash all come from this one run,
    # instead of the draft silently re-deadlocking on approval precondition 4's
    # stale-hash check.
    draft.scene_program_json = candidate.scene_program.model_dump_json()
    draft.artifact_hash = candidate.quality_report["artifact_hash"]
    draft.dsl_schema_versions_json = json.dumps(
        dsl_schema_versions(candidate.proposal, candidate.scene_program)
    )
    draft.updated_at = datetime.now(timezone.utc)

    for fixture_id, result in zip(fixture_ids, candidate.fixture_results, strict=True):
        fixture = session.get(TemplateDraftFixture, fixture_id)
        if fixture is None:
            raise DraftNotRevalidatableError(
                f"Draft {draft.id} fixtures changed during revalidation"
            )
        fixture.structural_check_passed = result.passed
        fixture.structural_check_detail = result.detail
    session.flush()
