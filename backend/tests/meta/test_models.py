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
