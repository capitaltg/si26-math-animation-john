import json
from datetime import datetime, timezone

import pytest

from app.meta import db, jobs, models


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    return engine


def _now():
    return datetime(2026, 7, 27, tzinfo=timezone.utc)


def _seed_cluster(session, key, n):
    ids = []
    for i in range(n):
        obs = models.FallbackObservation(
            id=f"obs-{i}", candidate_id=f"c{i}", source_excerpt="x",
            grade_level=3, observation_kind="unsupported_shape",
            excluded=False, created_at=_now(),
        )
        tag = models.FingerprintTag(
            id=f"t{i}", observation_id=obs.id, fingerprint_version=1,
            fingerprint_json="{}", fingerprint_key=key, tagger_model_id="m",
            tagger_prompt_version="v1", is_current=True, created_at=_now(),
        )
        session.add_all([obs, tag])
        ids.append(obs.id)
    session.flush()
    return ids


def test_concurrent_threshold_crossing_creates_one_job(engine):
    # Two independent sessions both try to enqueue after the same crossing.
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s1, s2 = factory(), factory()
    ids = _seed_cluster(s1, "k1", 5)
    s1.commit()

    j1 = jobs.evaluate_and_enqueue(
        s1, fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids=ids, threshold=5, new_id="job-a", now=_now(),
    )
    s1.commit()
    j2 = jobs.evaluate_and_enqueue(
        s2, fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids=ids, threshold=5, new_id="job-b", now=_now(),
    )
    s2.commit()
    assert (j1 is None) != (j2 is None)  # exactly one won
    with db.meta_session() as s:
        active = s.query(models.GenerationJob).filter(
            models.GenerationJob.status.in_((models.JOB_QUEUED, models.JOB_RUNNING))
        ).count()
        assert active == 1
    s1.close()
    s2.close()


def test_evaluate_and_enqueue_recovers_from_integrity_error(engine, monkeypatch):
    # Seed an existing active job for the fingerprint_key directly, then bypass
    # the has_active_job() guard that would normally short-circuit before the
    # insert — this forces evaluate_and_enqueue's real INSERT to collide with
    # the partial unique index, exercising the actual
    # `except IntegrityError: session.rollback(); return None` branch that no
    # other test in this suite reaches.
    with db.meta_session() as s:
        s.add(models.GenerationJob(
            id="existing-active", fingerprint_key="k1", fingerprint_version=1,
            fingerprint_json="{}", trigger_observation_ids="[]",
            status=models.JOB_QUEUED, attempt=0, created_at=_now(), updated_at=_now(),
        ))

    monkeypatch.setattr(jobs, "has_active_job", lambda *args, **kwargs: False)

    with db.meta_session() as s:
        result = jobs.evaluate_and_enqueue(
            s, fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
            trigger_observation_ids=[], threshold=0, new_id="new-job", now=_now(),
        )
        assert result is None

    with db.meta_session() as s:
        # The pre-existing job survives untouched; the rollback didn't
        # corrupt or remove it, and no second row was inserted for this key.
        jobs_for_key = s.query(models.GenerationJob).filter_by(fingerprint_key="k1").all()
        assert [j.id for j in jobs_for_key] == ["existing-active"]


def test_restart_preserves_rows(engine, tmp_path, monkeypatch):
    with db.meta_session() as s:
        _seed_cluster(s, "k1", 3)
    # Simulate a restart: brand-new engine over the same file.
    fresh = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: fresh)
    with db.meta_session() as s:
        assert s.query(models.FallbackObservation).count() == 3
        assert s.query(models.FingerprintTag).count() == 3


def test_failure_cooldown_prevents_retry_storm(engine):
    with db.meta_session() as s:
        s.add(models.GenerationJob(
            id="job-1", fingerprint_key="k1", fingerprint_version=1,
            fingerprint_json="{}", trigger_observation_ids="[]",
            status=models.JOB_QUEUED, attempt=0, created_at=_now(), updated_at=_now(),
        ))
    with db.meta_session() as s:
        from datetime import datetime as _dt, timezone as _tz
        t0 = _dt(2026, 7, 27, 12, 0, tzinfo=_tz.utc)
        jobs.claim_next_job(s, owner="w1", lease_seconds=300, now=t0)
        s.flush()
        jobs.fail_job(
            s, job_id="job-1", owner="w1", error_summary="x",
            backoff_base_seconds=60, max_attempts=5, now=t0,
        )
        s.flush()
        # Immediately after failing, the job is in cooldown and cannot be reclaimed.
        assert jobs.claim_next_job(s, owner="w1", lease_seconds=300, now=t0) is None
