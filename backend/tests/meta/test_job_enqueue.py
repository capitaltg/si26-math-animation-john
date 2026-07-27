import json
from datetime import datetime, timezone

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


def _seed_cluster(session, key, n, excluded_last=False):
    ids = []
    for i in range(n):
        obs = models.FallbackObservation(
            id=f"obs-{key}-{i}",
            candidate_id=f"cand-{key}-{i}",
            source_excerpt="x",
            grade_level=3,
            observation_kind="unsupported_shape",
            excluded=(excluded_last and i == n - 1),
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
