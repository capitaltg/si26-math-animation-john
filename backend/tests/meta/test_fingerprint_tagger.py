from datetime import datetime, timezone

import pytest

from app.meta import db, fingerprint, models


@pytest.fixture
def session(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    with db.meta_session() as s:
        yield s


def _fp():
    return fingerprint.Fingerprint(
        fingerprint_version=1,
        operation_family="compose",
        representation_family="bar",
        number_domain="fraction",
        operand_arity=2,
        step_count=1,
        grade_band="3-5",
    )


def test_tag_candidate_validates_bedrock_output(monkeypatch):
    captured = {}

    def fake_call(system_prompt, user_message, tools):
        captured["tools"] = tools
        return "fingerprint", _fp().model_dump()

    monkeypatch.setattr(fingerprint, "call_with_tool", fake_call)
    result = fingerprint.tag_candidate("2/5 + 1/5", grade_level=3)
    assert isinstance(result, fingerprint.Fingerprint)
    assert captured["tools"][0]["schema"] == fingerprint.FINGERPRINT_TOOL_SCHEMA


def test_store_tag_flips_previous_current(session):
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    # Create the observation first
    session.add(
        models.FallbackObservation(
            id="obs-1",
            candidate_id="cand-1",
            source_excerpt="2/5 + 1/5",
            grade_level=3,
            observation_kind="test",
            created_at=now,
        )
    )
    session.flush()
    # Seed a prior "current" tag directly at the ORM layer (bypassing store_tag
    # and the Fingerprint model, whose fingerprint_version is Literal[1] in
    # Phase 1) so it carries a *different* fingerprint_version than the new
    # tag store_tag is about to insert. This avoids uq_tag_observation_version
    # while still exercising the real flip: store_tag's UPDATE flips every
    # is_current=True row for the observation, regardless of that row's version.
    session.add(
        models.FingerprintTag(
            id="tag-old",
            observation_id="obs-1",
            fingerprint_version=0,
            fingerprint_json="{}",
            fingerprint_key="stale-key",
            tagger_model_id="m0",
            tagger_prompt_version="v0",
            is_current=True,
            created_at=now,
        )
    )
    session.flush()

    fingerprint.store_tag(
        session,
        observation_id="obs-1",
        fingerprint=_fp(),
        tagger_model_id="m1",
        tagger_prompt_version="v1",
        new_id="tag-new",
        created_at=now,
    )
    session.flush()

    tags = session.query(models.FingerprintTag).order_by(models.FingerprintTag.id).all()
    current = [t for t in tags if t.is_current]
    assert len(tags) == 2  # append-only: the prior row is retained, not deleted
    assert len(current) == 1
    assert current[0].id == "tag-new"
