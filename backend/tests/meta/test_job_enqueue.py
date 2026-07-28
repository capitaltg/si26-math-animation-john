import json
from datetime import datetime, timedelta, timezone

import pytest

from app.meta import db, jobs, models


@pytest.fixture
def session(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    with db.meta_session() as s:
        yield s


def _now():
    return datetime(2026, 7, 27, tzinfo=timezone.utc)


def _seed_cluster(session, key, n, excluded_last=False, start=0):
    ids = []
    for i in range(start, start + n):
        obs = models.FallbackObservation(
            id=f"obs-{key}-{i}",
            candidate_id=f"cand-{key}-{i}",
            source_excerpt="x",
            grade_level=3,
            observation_kind="unsupported_shape",
            excluded=(excluded_last and i == start + n - 1),
            created_at=_now(),
        )
        tag = models.FingerprintTag(
            id=f"tag-{key}-{i}",
            observation_id=obs.id,
            fingerprint_version=1,
            fingerprint_json="{}",
            fingerprint_key=key,
            tagger_model_id="m",
            tagger_prompt_version="v1",
            is_current=True,
            created_at=_now(),
        )
        session.add_all([obs, tag])
        ids.append(obs.id)
    session.flush()
    return ids


def test_count_ignores_excluded(session):
    _seed_cluster(session, "k1", 5, excluded_last=True)
    assert jobs.count_eligible_observations(session, "k1") == 4


def test_enqueue_when_threshold_met(session):
    ids = _seed_cluster(session, "k1", 5)
    job = jobs.evaluate_and_enqueue(
        session,
        fingerprint_key="k1",
        fingerprint_version=1,
        fingerprint_json="{}",
        trigger_observation_ids=ids,
        threshold=5,
        new_id="job-1",
        now=_now(),
    )
    assert job is not None
    assert job.status == models.JOB_QUEUED
    assert json.loads(job.trigger_observation_ids) == ids


def test_below_threshold_does_not_enqueue(session):
    ids = _seed_cluster(session, "k1", 4)
    job = jobs.evaluate_and_enqueue(
        session,
        fingerprint_key="k1",
        fingerprint_version=1,
        fingerprint_json="{}",
        trigger_observation_ids=ids,
        threshold=5,
        new_id="job-1",
        now=_now(),
    )
    assert job is None


def test_second_enqueue_is_noop_when_active_job_exists(session):
    ids = _seed_cluster(session, "k1", 5)
    first = jobs.evaluate_and_enqueue(
        session, fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids=ids, threshold=5, new_id="job-1", now=_now(),
    )
    session.flush()
    second = jobs.evaluate_and_enqueue(
        session, fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids=ids, threshold=5, new_id="job-2", now=_now(),
    )
    assert first is not None
    assert second is None
    assert session.query(models.GenerationJob).count() == 1


def test_failed_job_requires_new_observation_and_expired_cooldown(session):
    original_ids = _seed_cluster(session, "k1", 5)
    failed_at = _now()
    session.add(
        models.GenerationJob(
            id="failed-job",
            fingerprint_key="k1",
            fingerprint_version=1,
            fingerprint_json="{}",
            trigger_observation_ids=json.dumps(original_ids),
            status=models.JOB_FAILED,
            attempt=1,
            cooldown_until=failed_at + timedelta(seconds=60),
            created_at=failed_at,
            updated_at=failed_at,
        )
    )
    session.flush()

    no_new_observation = jobs.evaluate_and_enqueue(
        session,
        fingerprint_key="k1",
        fingerprint_version=1,
        fingerprint_json="{}",
        trigger_observation_ids=original_ids,
        threshold=5,
        new_id="retry-too-early",
        now=failed_at + timedelta(seconds=120),
    )
    assert no_new_observation is None

    extra_ids = _seed_cluster(session, "k1", 1, start=5)
    all_ids = [*original_ids, *extra_ids]
    still_in_cooldown = jobs.evaluate_and_enqueue(
        session,
        fingerprint_key="k1",
        fingerprint_version=1,
        fingerprint_json="{}",
        trigger_observation_ids=all_ids,
        threshold=5,
        new_id="retry-in-cooldown",
        now=failed_at + timedelta(seconds=30),
    )
    assert still_in_cooldown is None

    retry = jobs.evaluate_and_enqueue(
        session,
        fingerprint_key="k1",
        fingerprint_version=1,
        fingerprint_json="{}",
        trigger_observation_ids=all_ids,
        threshold=5,
        new_id="retry-job",
        now=failed_at + timedelta(seconds=60),
    )
    assert retry is not None
    assert retry.status == models.JOB_QUEUED
    assert retry.attempt == 1


def test_succeeded_job_does_not_retrigger(session):
    ids = _seed_cluster(session, "k1", 5)
    session.add(
        models.GenerationJob(
            id="completed-job",
            fingerprint_key="k1",
            fingerprint_version=1,
            fingerprint_json="{}",
            trigger_observation_ids=json.dumps(ids),
            status=models.JOB_SUCCEEDED,
            attempt=0,
            created_at=_now(),
            updated_at=_now(),
        )
    )
    session.flush()
    new_ids = [*ids, *_seed_cluster(session, "k1", 1, start=5)]

    assert (
        jobs.evaluate_and_enqueue(
            session,
            fingerprint_key="k1",
            fingerprint_version=1,
            fingerprint_json="{}",
            trigger_observation_ids=new_ids,
            threshold=5,
            new_id="unexpected-job",
            now=_now() + timedelta(seconds=60),
        )
        is None
    )


def test_has_enabled_version_is_false_without_a_row(session):
    assert jobs.has_enabled_version(session, "k1") is False


def test_has_enabled_version_is_true_for_an_enabled_row(session):
    session.add(models.TemplateVersion(
        id="tv-1", fingerprint_key="k1", template_name="x", draft_id=None,
        artifact_hash="sha256:x", status=models.TEMPLATE_VERSION_ENABLED,
        created_at=_now(), updated_at=_now(),
    ))
    session.flush()
    assert jobs.has_enabled_version(session, "k1") is True


def test_has_enabled_version_ignores_disabled_rows(session):
    session.add(models.TemplateVersion(
        id="tv-1", fingerprint_key="k1", template_name="x", draft_id=None,
        artifact_hash="sha256:x", status=models.TEMPLATE_VERSION_DISABLED,
        created_at=_now(), updated_at=_now(),
    ))
    session.flush()
    assert jobs.has_enabled_version(session, "k1") is False


def test_enqueue_is_a_noop_when_an_enabled_version_already_exists(session):
    session.add(models.TemplateVersion(
        id="tv-1", fingerprint_key="k1", template_name="x", draft_id=None,
        artifact_hash="sha256:x", status=models.TEMPLATE_VERSION_ENABLED,
        created_at=_now(), updated_at=_now(),
    ))
    session.flush()
    _seed_cluster(session, "k1", 5)
    job = jobs.evaluate_and_enqueue(
        session, fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids=["obs-k1-0"], threshold=5, new_id="job-1", now=_now(),
    )
    assert job is None
