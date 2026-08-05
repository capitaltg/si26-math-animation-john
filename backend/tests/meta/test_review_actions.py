from datetime import datetime, timezone

import pytest

from app.config import get_settings
from app.meta import db, models
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.fingerprint import Fingerprint
from app.meta.review_actions import DraftNotRefinableError, reject_and_refine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    yield engine
    get_settings.cache_clear()


def _now():
    return datetime(2026, 7, 30, tzinfo=timezone.utc)


def _seed_draft(status):
    with db.meta_session() as session:
        job = models.GenerationJob(
            id="job-1", fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
            trigger_observation_ids="[]", status=models.JOB_SUCCEEDED, created_at=_now(), updated_at=_now(),
        )
        session.add(job)
        session.add(models.TemplateDraft(
            id="draft-1", job_id=job.id, fingerprint_key="k1", fingerprint_version=1,
            fingerprint_json="{}", revision=1, params_document_json="{}", guard_document_json="{}",
            answer_expression_json="{}", teaching_plan_json="{}", scene_program_json="{}",
            quality_report_json="{}", classifier_bullet="Use for X", dsl_schema_versions_json="{}",
            artifact_hash="sha256:candidate", status=status, created_at=_now(), updated_at=_now(),
        ))


def _fingerprint():
    return Fingerprint(
        fingerprint_version=1,
        operation_family="measure",
        representation_family="shape",
        number_domain="whole",
        operand_arity=2,
        step_count=2,
        grade_band="6-8",
    )


def _proposal():
    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="length", label="Length", description="", minimum=1, maximum=100)],
        ),
        guard_document=GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=FieldRefNode(field="length"))],
        ),
        answer_expression=FieldRefNode(field="length"),
        teaching_plan_document=TeachingPlanDocument.model_validate({
            "plan_version": 3,
            "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
            "primary_visual": {
                "kind": "rectangle_measurement", "ref": "rectangle",
                "length": {"node": "field_ref", "field": "length"},
                "width": {"node": "literal", "value": 1}, "unit": "cm",
            },
            "strategy": "boundary_trace",
            "beats": [
                {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}], "intent": "show the rectangle"},
                {"id": "trace", "kind": "derive", "targets": [{"visual_ref": "rectangle"}], "intent": "trace every edge"},
                {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}], "intent": "state the perimeter"},
            ],
            "variation_seed": "review-refinement",
        }),
        classifier_bullet="Use for rectangle perimeter lessons.",
        fixtures=[ProposedFixture(kind="positive", expected_outcome="accept", params={"length": 8})],
    )


def _seed_pending_review_draft():
    proposal = _proposal()
    with db.meta_session() as session:
        job = models.GenerationJob(
            id="pending-job",
            fingerprint_key="pending-key",
            fingerprint_version=1,
            fingerprint_json=_fingerprint().model_dump_json(),
            trigger_observation_ids="[]",
            status=models.JOB_SUCCEEDED,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(job)
        session.add(models.TemplateDraft(
            id="pending-draft",
            job_id=job.id,
            fingerprint_key=job.fingerprint_key,
            fingerprint_version=job.fingerprint_version,
            fingerprint_json=job.fingerprint_json,
            revision=1,
            params_document_json=proposal.params_document.model_dump_json(),
            guard_document_json=proposal.guard_document.model_dump_json(),
            answer_expression_json=proposal.answer_expression.model_dump_json(),
            teaching_plan_json=proposal.teaching_plan_document.model_dump_json(),
            scene_program_json="{}",
            quality_report_json='{"passed": true}',
            classifier_bullet=proposal.classifier_bullet,
            dsl_schema_versions_json="{}",
            artifact_hash="sha256:parent",
            status=models.DRAFT_PENDING_REVIEW,
            validation_report_json='{"passed": true}',
            created_at=_now(),
            updated_at=_now(),
        ))
    return proposal


def test_failed_validation_draft_is_not_reviewer_refinable(engine):
    _seed_draft(models.DRAFT_FAILED_VALIDATION)

    with pytest.raises(DraftNotRefinableError):
        reject_and_refine(
            "draft-1", feedback="fix the candidate", reviewer_label="reviewer", max_refinements=5
        )


def test_pending_review_refinement_persists_the_next_revision(monkeypatch, engine):
    proposal = _seed_pending_review_draft()
    generated = {}

    def generate_next_revision(**kwargs):
        generated.update(kwargs)
        with db.meta_session() as session:
            child = models.TemplateDraft(
                id="refined-draft",
                job_id=kwargs["job"].id,
                fingerprint_key=kwargs["job"].fingerprint_key,
                fingerprint_version=kwargs["job"].fingerprint_version,
                fingerprint_json=kwargs["job"].fingerprint_json,
                revision=kwargs["revision"],
                parent_draft_id=kwargs["parent_draft_id"],
                params_document_json=proposal.params_document.model_dump_json(),
                guard_document_json=proposal.guard_document.model_dump_json(),
                answer_expression_json=proposal.answer_expression.model_dump_json(),
                teaching_plan_json=proposal.teaching_plan_document.model_dump_json(),
                scene_program_json="{}",
                quality_report_json='{"passed": true}',
                classifier_bullet=proposal.classifier_bullet,
                dsl_schema_versions_json="{}",
                artifact_hash="sha256:child",
                status=models.DRAFT_PENDING_REVIEW,
                validation_report_json='{"passed": true}',
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(child)
            session.flush()
            return child

    monkeypatch.setattr("app.meta.review_actions.generate_and_validate_revision", generate_next_revision)

    refined = reject_and_refine(
        "pending-draft", feedback="tighten the explanation", reviewer_label="reviewer", max_refinements=5
    )

    assert refined.id == "refined-draft"
    assert refined.revision == 2
    assert refined.parent_draft_id == "pending-draft"
    assert generated["revision"] == 2
    with db.meta_session() as session:
        parent = session.get(models.TemplateDraft, "pending-draft")
        child = session.get(models.TemplateDraft, "refined-draft")
        assert parent.status == models.DRAFT_REJECTED
        assert parent.reviewer_feedback == "tighten the explanation"
        assert child.revision == 2
        assert child.parent_draft_id == parent.id
        assert child.status == models.DRAFT_PENDING_REVIEW
        assert session.query(models.TemplateReview).filter_by(draft_id=parent.id).count() == 1


# ------------------------------------- asynchronous refinement (teacher path)


def test_requeue_for_refinement_hands_the_work_back_to_the_worker(engine):
    """A teacher's reject must not block on generation.

    reject_and_refine calls the model inline, which is fine for an admin and
    unusable for a teacher: it would hold the HTTP request open for minutes. The
    teacher path records the rejection and puts the job back on the queue.
    """
    from app.meta.review_actions import requeue_for_refinement

    _seed_draft(models.DRAFT_PENDING_REVIEW)

    outcome = requeue_for_refinement(
        "draft-1", feedback="the rows aren't labelled", reviewer_label="teacher",
        max_refinements=5,
    )

    assert outcome.requeued is True
    with db.meta_session() as session:
        draft = session.get(models.TemplateDraft, "draft-1")
        assert draft.status == models.DRAFT_REJECTED
        assert draft.reviewer_feedback == "the rows aren't labelled"
        assert session.get(models.GenerationJob, "job-1").status == models.JOB_QUEUED
        review = session.query(models.TemplateReview).filter_by(draft_id="draft-1").one()
        assert review.decision == "reject"
        assert review.feedback == "the rows aren't labelled"


def test_requeue_for_refinement_clears_a_stale_cooldown_and_lease(engine):
    """The requeued job must be claimable now, not after an old backoff.

    A job that previously failed carries a future cooldown_until, and a job that
    succeeded may still carry its last lease. _claimable would skip the first and
    the second could look like someone else's running work.
    """
    from app.meta.review_actions import requeue_for_refinement

    _seed_draft(models.DRAFT_PENDING_REVIEW)
    with db.meta_session() as session:
        job = session.get(models.GenerationJob, "job-1")
        job.cooldown_until = datetime(2099, 1, 1, tzinfo=timezone.utc)
        job.lease_owner = "worker-old"
        job.lease_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

    requeue_for_refinement(
        "draft-1", feedback="try again", reviewer_label="teacher", max_refinements=5
    )

    with db.meta_session() as session:
        job = session.get(models.GenerationJob, "job-1")
        assert job.cooldown_until is None
        assert job.lease_owner is None
        assert job.lease_expires_at is None


def test_requeue_for_refinement_stops_at_the_refinement_ceiling(engine):
    from app.meta.review_actions import requeue_for_refinement

    _seed_draft(models.DRAFT_PENDING_REVIEW)
    with db.meta_session() as session:
        session.get(models.TemplateDraft, "draft-1").revision = 5

    outcome = requeue_for_refinement(
        "draft-1", feedback="still wrong", reviewer_label="teacher", max_refinements=5
    )

    assert outcome.requeued is False
    with db.meta_session() as session:
        assert session.get(models.GenerationJob, "job-1").status == models.JOB_NEEDS_MANUAL
        assert session.get(models.TemplateDraft, "draft-1").status == models.DRAFT_REJECTED


def test_requeue_for_refinement_refuses_a_draft_that_is_not_pending_review(engine):
    from app.meta.review_actions import requeue_for_refinement

    _seed_draft(models.DRAFT_FAILED_VALIDATION)

    with pytest.raises(DraftNotRefinableError):
        requeue_for_refinement(
            "draft-1", feedback="fix it", reviewer_label="teacher", max_refinements=5
        )
