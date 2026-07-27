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


def _t(minute=0):
    return datetime(2026, 7, 27, 12, minute, tzinfo=timezone.utc)


def _queued(session, job_id="job-1", **overrides):
    job = models.GenerationJob(
        id=job_id,
        fingerprint_key="k1",
        fingerprint_version=1,
        fingerprint_json="{}",
        trigger_observation_ids="[]",
        status=models.JOB_QUEUED,
        attempt=0,
        created_at=_t(),
        updated_at=_t(),
    )
    for k, v in overrides.items():
        setattr(job, k, v)
    session.add(job)
    session.flush()
    return job


def test_claim_marks_running_with_lease(session):
    _queued(session)
    claimed = jobs.claim_next_job(session, owner="w1", lease_seconds=300, now=_t(0))
    assert claimed is not None
    assert claimed.status == models.JOB_RUNNING
    assert claimed.lease_owner == "w1"
    assert claimed.lease_expires_at == _t(5)


def test_second_worker_cannot_claim_live_lease(session):
    _queued(session)
    jobs.claim_next_job(session, owner="w1", lease_seconds=300, now=_t(0))
    session.flush()
    assert jobs.claim_next_job(session, owner="w2", lease_seconds=300, now=_t(1)) is None


def test_expired_lease_can_be_reclaimed(session):
    _queued(session)
    jobs.claim_next_job(session, owner="w1", lease_seconds=300, now=_t(0))
    session.flush()
    reclaimed = jobs.claim_next_job(session, owner="w2", lease_seconds=300, now=_t(10))
    assert reclaimed is not None
    assert reclaimed.lease_owner == "w2"


def test_cooldown_hides_job_until_deadline(session):
    _queued(session, cooldown_until=_t(30))
    assert jobs.claim_next_job(session, owner="w1", lease_seconds=300, now=_t(10)) is None
    assert jobs.claim_next_job(session, owner="w1", lease_seconds=300, now=_t(40)) is not None


def test_complete_requires_owner(session):
    _queued(session)
    jobs.claim_next_job(session, owner="w1", lease_seconds=300, now=_t(0))
    session.flush()
    assert jobs.complete_job(session, job_id="job-1", owner="w2", now=_t(1)) is False
    assert jobs.complete_job(session, job_id="job-1", owner="w1", now=_t(1)) is True
    assert session.get(models.GenerationJob, "job-1").status == models.JOB_SUCCEEDED


def test_fail_backs_off_then_gives_up(session):
    _queued(session)
    jobs.claim_next_job(session, owner="w1", lease_seconds=300, now=_t(0))
    session.flush()
    jobs.fail_job(
        session, job_id="job-1", owner="w1", error_summary="boom",
        backoff_base_seconds=60, max_attempts=3, now=_t(1),
    )
    job = session.get(models.GenerationJob, "job-1")
    assert job.status == models.JOB_QUEUED
    assert job.attempt == 1
    assert job.cooldown_until == _t(1) + timedelta(seconds=60)  # 60 * 2**0
    assert job.lease_owner is None


def test_fail_reaches_manual_authoring(session):
    _queued(session, attempt=2)
    jobs.claim_next_job(session, owner="w1", lease_seconds=300, now=_t(0))
    session.flush()
    jobs.fail_job(
        session, job_id="job-1", owner="w1", error_summary="boom",
        backoff_base_seconds=60, max_attempts=3, now=_t(1),
    )
    assert session.get(models.GenerationJob, "job-1").status == models.JOB_NEEDS_MANUAL
