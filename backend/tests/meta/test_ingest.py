import json
import uuid
from datetime import datetime, timezone

import pytest

from app.meta import db, ingest, models
from app.models.scene import TemplateName
from app.pipeline.classification import ClassificationResult, TemplateOption
from app.meta import fingerprint as fp_mod


@pytest.fixture
def wired(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)

    def fake_tag(source_excerpt, grade_level):
        return fp_mod.Fingerprint(
            fingerprint_version=1,
            operation_family="compose",
            representation_family="bar",
            number_domain="fraction",
            operand_arity=2,
            step_count=1,
            grade_band="3-5",
        )

    monkeypatch.setattr(ingest, "tag_candidate", fake_tag)
    return engine


def _unsupported_classification():
    return ClassificationResult(
        options=[TemplateOption(template=TemplateName.TEXT_CARD, rationale="fallback")],
        grade_level=3,
        ambiguous=False,
        problem_kind="solvable",
    )


def test_flag_off_records_nothing(wired, monkeypatch):
    monkeypatch.setattr(ingest, "get_settings", lambda: _settings(enabled=False))
    ingest.record_unsupported_shape(
        candidate_id="c1", source_excerpt="2/5 + 1/5",
        classification=_unsupported_classification(),
        picked_template=TemplateName.TEXT_CARD, scene_status="pending_review",
    )
    with db.meta_session() as s:
        assert s.query(models.FallbackObservation).count() == 0


def test_unsupported_shape_records_tags_and_may_enqueue(wired, monkeypatch):
    monkeypatch.setattr(ingest, "get_settings", lambda: _settings(enabled=True, threshold=1))
    ingest.record_unsupported_shape(
        candidate_id="c1", source_excerpt="2/5 + 1/5",
        classification=_unsupported_classification(),
        picked_template=TemplateName.TEXT_CARD, scene_status="pending_review",
    )
    with db.meta_session() as s:
        assert s.query(models.FallbackObservation).count() == 1
        assert s.query(models.FingerprintTag).filter_by(is_current=True).count() == 1
        assert s.query(models.GenerationJob).count() == 1  # threshold=1 reached


def test_tag_failure_keeps_untagged_observation(wired, monkeypatch):
    monkeypatch.setattr(ingest, "get_settings", lambda: _settings(enabled=True, threshold=1))

    def boom(source_excerpt, grade_level):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(ingest, "tag_candidate", boom)
    ingest.record_unsupported_shape(
        candidate_id="c1", source_excerpt="2/5 + 1/5",
        classification=_unsupported_classification(),
        picked_template=TemplateName.TEXT_CARD, scene_status="pending_review",
    )
    with db.meta_session() as s:
        assert s.query(models.FallbackObservation).count() == 1  # not lost
        assert s.query(models.FingerprintTag).count() == 0
        assert s.query(models.GenerationJob).count() == 0


def test_trigger_observation_ids_scoped_to_own_fingerprint_cluster(wired, monkeypatch):
    monkeypatch.setattr(ingest, "get_settings", lambda: _settings(enabled=True, threshold=1))

    # Seed an unrelated observation belonging to a different fingerprint cluster,
    # tagged as current, directly via the ORM.
    unrelated_fp = fp_mod.Fingerprint(
        fingerprint_version=1,
        operation_family="decompose",
        representation_family="table",
        number_domain="integer",
        operand_arity=3,
        step_count=2,
        grade_band="6-8",
    )
    unrelated_key = fp_mod.canonical_fingerprint_key(unrelated_fp)

    with db.meta_session() as s:
        unrelated_obs = models.FallbackObservation(
            id=uuid.uuid4().hex,
            candidate_id="unrelated-candidate",
            source_excerpt="9 - 4 - 2",
            grade_level=6,
            observation_kind=ingest.OBSERVATION_KIND_UNSUPPORTED,
            excluded=False,
            created_at=datetime.now(timezone.utc),
        )
        s.add(unrelated_obs)
        s.flush()
        s.add(
            models.FingerprintTag(
                id=uuid.uuid4().hex,
                observation_id=unrelated_obs.id,
                fingerprint_version=unrelated_fp.fingerprint_version,
                fingerprint_json=unrelated_fp.model_dump_json(),
                fingerprint_key=unrelated_key,
                tagger_model_id="test-model",
                tagger_prompt_version="v1",
                is_current=True,
                created_at=datetime.now(timezone.utc),
            )
        )
    unrelated_obs_id = unrelated_obs.id

    ingest.record_unsupported_shape(
        candidate_id="c1", source_excerpt="2/5 + 1/5",
        classification=_unsupported_classification(),
        picked_template=TemplateName.TEXT_CARD, scene_status="pending_review",
    )

    with db.meta_session() as s:
        job = s.query(models.GenerationJob).one()
        trigger_ids = json.loads(job.trigger_observation_ids)
        assert unrelated_obs_id not in trigger_ids
        for oid in trigger_ids:
            tag = (
                s.query(models.FingerprintTag)
                .filter_by(observation_id=oid, is_current=True)
                .one()
            )
            assert tag.fingerprint_key == job.fingerprint_key


def _settings(*, enabled=True, threshold=5):
    class _S:
        meta_templates_enabled = enabled
        fingerprint_observation_threshold = threshold
        fingerprint_tagger_prompt_version = "v1"
        bedrock_model_id = "test-model"

    return _S()
