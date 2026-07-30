from datetime import datetime, timezone

import pytest

from app.config import get_settings
from app.meta import db, models
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


def test_failed_validation_draft_is_not_reviewer_refinable(engine):
    _seed_draft(models.DRAFT_FAILED_VALIDATION)

    with pytest.raises(DraftNotRefinableError):
        reject_and_refine(
            "draft-1", feedback="fix the candidate", reviewer_label="reviewer", max_refinements=5
        )
