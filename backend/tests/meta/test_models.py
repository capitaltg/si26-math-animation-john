from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.meta import db, models


@pytest.fixture
def session(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _now():
    return datetime(2026, 7, 27, tzinfo=timezone.utc)


def test_observation_unique_on_candidate_and_kind(session):
    for _ in range(2):
        session.add(
            models.FallbackObservation(
                id=f"obs-{_}" if False else "obs-fixed",
                candidate_id="cand-1",
                source_excerpt="2/5 + 1/5",
                grade_level=3,
                observation_kind="unsupported_shape",
                created_at=_now(),
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


def test_partial_unique_allows_one_current_tag_per_observation(session):
    observation = models.FallbackObservation(
        id="obs-current",
        candidate_id="cand-current",
        source_excerpt="2/5 + 1/5",
        grade_level=3,
        observation_kind="unsupported_shape",
        created_at=_now(),
    )
    session.add(observation)
    session.flush()
    common = dict(
        observation_id=observation.id,
        fingerprint_json="{}",
        fingerprint_key="k1",
        tagger_model_id="m",
        tagger_prompt_version="v1",
        is_current=True,
        created_at=_now(),
    )
    session.add(models.FingerprintTag(id="t1", fingerprint_version=1, **common))
    session.add(models.FingerprintTag(id="t2", fingerprint_version=2, **common))

    with pytest.raises(IntegrityError):
        session.flush()


def test_partial_unique_allows_one_active_job(session):
    common = dict(
        fingerprint_key="k1",
        fingerprint_version=1,
        fingerprint_json="{}",
        trigger_observation_ids="[]",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(models.GenerationJob(id="j1", status=models.JOB_QUEUED, **common))
    session.flush()
    session.add(models.GenerationJob(id="j2", status=models.JOB_RUNNING, **common))
    with pytest.raises(IntegrityError):
        session.flush()


def test_partial_unique_ignores_terminal_jobs(session):
    common = dict(
        fingerprint_key="k2",
        fingerprint_version=1,
        fingerprint_json="{}",
        trigger_observation_ids="[]",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(models.GenerationJob(id="j3", status=models.JOB_SUCCEEDED, **common))
    session.add(models.GenerationJob(id="j4", status=models.JOB_FAILED, **common))
    session.flush()  # no IntegrityError: neither is queued/running


def test_template_draft_and_fixtures_insert(session):
    common = dict(
        fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids="[]", created_at=_now(), updated_at=_now(),
    )
    session.add(models.GenerationJob(id="job-1", status=models.JOB_RUNNING, **common))
    session.flush()

    draft = models.TemplateDraft(
        id="draft-1", job_id="job-1", fingerprint_key="k1", fingerprint_version=1,
        fingerprint_json="{}", revision=1, params_document_json="{}",
        guard_document_json="{}", answer_expression_json="{}", animation_document_json="{}",
        classifier_bullet="use for X", dsl_schema_versions_json="{}", artifact_hash="sha256:x",
        status=models.DRAFT_GENERATED, created_at=_now(), updated_at=_now(),
    )
    session.add(draft)
    session.flush()

    session.add(models.TemplateDraftFixture(
        id="fixture-1", draft_id="draft-1", kind="positive", expected_outcome="accept",
        generation_method="proposed", params_json="{}", created_at=_now(),
    ))
    session.add(models.TemplateReview(
        id="review-1", draft_id="draft-1", decision="reject",
        reviewer_label="dev", feedback="fix the guard", created_at=_now(),
    ))
    session.flush()

    assert session.query(models.TemplateDraft).count() == 1
    assert session.query(models.TemplateDraftFixture).count() == 1
    assert session.query(models.TemplateReview).count() == 1


def test_template_draft_requires_known_job(session):
    session.add(models.TemplateDraft(
        id="draft-orphan", job_id="ghost-job", fingerprint_key="k1", fingerprint_version=1,
        fingerprint_json="{}", revision=1, params_document_json="{}", guard_document_json="{}",
        answer_expression_json="{}", animation_document_json="{}", classifier_bullet="x",
        dsl_schema_versions_json="{}", artifact_hash="sha256:x", status=models.DRAFT_GENERATED,
        created_at=_now(), updated_at=_now(),
    ))
    with pytest.raises(IntegrityError):
        session.flush()


def test_template_version_insert_and_query_by_fingerprint(session):
    session.add(models.TemplateVersion(
        id="tv-1", fingerprint_key="k1", template_name="decimal_comparison_grid",
        draft_id=None, artifact_hash="sha256:x", status=models.TEMPLATE_VERSION_ENABLED,
        created_at=_now(), updated_at=_now(),
    ))
    session.flush()

    rows = (
        session.query(models.TemplateVersion)
        .filter_by(fingerprint_key="k1", status=models.TEMPLATE_VERSION_ENABLED)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].template_name == "decimal_comparison_grid"


def test_template_version_requires_known_draft_when_set(session):
    from sqlalchemy.exc import IntegrityError

    session.add(models.TemplateVersion(
        id="tv-orphan", fingerprint_key="k1", template_name="x",
        draft_id="ghost-draft", artifact_hash="sha256:x", status=models.TEMPLATE_VERSION_ENABLED,
        created_at=_now(), updated_at=_now(),
    ))
    with pytest.raises(IntegrityError):
        session.flush()


def test_approved_review_preserves_math_semantics_confirmed(session):
    common = dict(
        fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids="[]", created_at=_now(), updated_at=_now(),
    )
    session.add(models.GenerationJob(id="job-approve", status=models.JOB_RUNNING, **common))
    session.flush()

    session.add(models.TemplateDraft(
        id="draft-approve", job_id="job-approve", fingerprint_key="k1", fingerprint_version=1,
        fingerprint_json="{}", revision=1, params_document_json="{}",
        guard_document_json="{}", answer_expression_json="{}", animation_document_json="{}",
        classifier_bullet="use for X", dsl_schema_versions_json="{}", artifact_hash="sha256:x",
        status=models.DRAFT_APPROVED, created_at=_now(), updated_at=_now(),
    ))
    session.flush()

    session.add(models.TemplateReview(
        id="review-approve", draft_id="draft-approve", decision="approve",
        reviewer_label="dev", feedback=None, math_semantics_confirmed=True,
        created_at=_now(),
    ))
    session.flush()

    review = session.get(models.TemplateReview, "review-approve")
    assert review.math_semantics_confirmed is True


def test_rejection_review_leaves_math_semantics_confirmed_null(session):
    common = dict(
        fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids="[]", created_at=_now(), updated_at=_now(),
    )
    session.add(models.GenerationJob(id="job-reject", status=models.JOB_RUNNING, **common))
    session.flush()

    session.add(models.TemplateDraft(
        id="draft-reject", job_id="job-reject", fingerprint_key="k1", fingerprint_version=1,
        fingerprint_json="{}", revision=1, params_document_json="{}",
        guard_document_json="{}", answer_expression_json="{}", animation_document_json="{}",
        classifier_bullet="use for X", dsl_schema_versions_json="{}", artifact_hash="sha256:x",
        status=models.DRAFT_REJECTED, created_at=_now(), updated_at=_now(),
    ))
    session.flush()

    session.add(models.TemplateReview(
        id="review-reject", draft_id="draft-reject", decision="reject",
        reviewer_label="dev", feedback="nope", created_at=_now(),
    ))
    session.flush()

    review = session.get(models.TemplateReview, "review-reject")
    assert review.math_semantics_confirmed is None


def test_partial_unique_rejects_two_enabled_versions_same_fingerprint(session):
    common = dict(
        fingerprint_key="k-shared", artifact_hash="sha256:x",
        status=models.TEMPLATE_VERSION_ENABLED, created_at=_now(), updated_at=_now(),
    )
    session.add(models.TemplateVersion(id="tv-a", template_name="name_a", **common))
    session.flush()
    session.add(models.TemplateVersion(id="tv-b", template_name="name_b", **common))
    with pytest.raises(IntegrityError):
        session.flush()


def test_partial_unique_rejects_two_enabled_versions_same_template_name(session):
    common = dict(
        template_name="shared_name", artifact_hash="sha256:x",
        status=models.TEMPLATE_VERSION_ENABLED, created_at=_now(), updated_at=_now(),
    )
    session.add(models.TemplateVersion(id="tv-c", fingerprint_key="k-c", **common))
    session.flush()
    session.add(models.TemplateVersion(id="tv-d", fingerprint_key="k-d", **common))
    with pytest.raises(IntegrityError):
        session.flush()


def test_partial_unique_allows_disabled_historical_rows_sharing_fingerprint_and_name(session):
    common = dict(
        fingerprint_key="k-hist", template_name="hist_name", artifact_hash="sha256:x",
        status=models.TEMPLATE_VERSION_DISABLED, created_at=_now(), updated_at=_now(),
    )
    session.add(models.TemplateVersion(id="tv-e", **common))
    session.add(models.TemplateVersion(id="tv-f", **common))
    session.flush()  # no IntegrityError: neither row is enabled

    assert session.query(models.TemplateVersion).filter_by(
        status=models.TEMPLATE_VERSION_DISABLED
    ).count() == 2
