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


def _settings(*, enabled=True, threshold=5):
    class _S:
        meta_templates_enabled = enabled
        fingerprint_observation_threshold = threshold
        fingerprint_tagger_prompt_version = "v1"
        bedrock_model_id = "test-model"

    return _S()
