from datetime import datetime, timezone

import pytest

from app.meta import db, observations, models


@pytest.fixture
def session(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    with db.meta_session() as s:
        yield s


def _now():
    return datetime(2026, 7, 27, tzinfo=timezone.utc)


def test_first_record_creates_row(session):
    row, created = observations.record_observation(
        session,
        new_id="obs-1",
        candidate_id="cand-1",
        source_excerpt="2/5 + 1/5",
        grade_level=3,
        observation_kind=observations.OBSERVATION_KIND_UNSUPPORTED,
        created_at=_now(),
    )
    assert created is True
    assert row.id == "obs-1"


def test_repeat_is_idempotent(session):
    kwargs = dict(
        candidate_id="cand-1",
        source_excerpt="2/5 + 1/5",
        grade_level=3,
        observation_kind=observations.OBSERVATION_KIND_UNSUPPORTED,
        created_at=_now(),
    )
    observations.record_observation(session, new_id="obs-1", **kwargs)
    session.flush()
    row, created = observations.record_observation(session, new_id="obs-2", **kwargs)
    assert created is False
    assert row.id == "obs-1"
    assert session.query(models.FallbackObservation).count() == 1
