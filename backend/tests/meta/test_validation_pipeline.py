import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.meta import db, models
from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.drafts import create_generated_draft
from app.meta.validation_pipeline import persist_validation


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
    return datetime(2026, 7, 28, tzinfo=timezone.utc)


def _job(session):
    job = models.GenerationJob(
        id="job-1", fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids="[]", status=models.JOB_RUNNING, created_at=_now(), updated_at=_now(),
    )
    session.add(job)
    session.flush()
    return job


def _observation(session):
    obs = models.FallbackObservation(
        id="obs-1", candidate_id="cand-1", source_excerpt="there are 5 apples",
        grade_level=2, observation_kind="unsupported_shape", excluded=False, created_at=_now(),
    )
    session.add(obs)
    session.flush()
    return obs


def _valid_proposal(observation_id):
    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
        ),
        guard_document=GuardDocument(guard_version=1, predicates=[PositivePredicate(value=FieldRefNode(field="n"))]),
        answer_expression=FieldRefNode(field="n"),
        animation_document=AnimationDocument(root={"kind": "label", "text": "n"}),
        classifier_bullet="use for X",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", observation_id=observation_id, params={"n": 5}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"n": -1}),
        ],
    )


def test_persist_validation_marks_draft_pending_review_when_everything_passes(session, tmp_path):
    job = _job(session)
    obs = _observation(session)
    draft = create_generated_draft(
        session, new_id="draft-1", job=job, proposal=_valid_proposal(obs.id), now=_now(),
        fixture_ids=["fx-1", "fx-2"],
    )
    passed = persist_validation(session, draft, {obs.id: obs}, _now(), tmp_path)
    session.flush()

    assert passed is True
    assert draft.status == models.DRAFT_PENDING_REVIEW
    assert draft.preview_artifact_hash is not None
    report = json.loads(draft.validation_report_json)
    assert report["passed"] is True
    assert len(report["fixture_results"]) == 2

    fixtures = {f.id: f for f in session.query(models.TemplateDraftFixture).filter_by(draft_id=draft.id).all()}
    assert fixtures["fx-1"].structural_check_passed is True
    assert fixtures["fx-2"].structural_check_passed is True


def test_persist_validation_marks_draft_failed_when_a_fixture_is_ungrounded(session, tmp_path):
    job = _job(session)
    obs = models.FallbackObservation(
        id="obs-2", candidate_id="cand-2", source_excerpt="there are seven oranges",
        grade_level=2, observation_kind="unsupported_shape", excluded=False, created_at=_now(),
    )
    session.add(obs)
    session.flush()
    draft = create_generated_draft(
        session, new_id="draft-2", job=job, proposal=_valid_proposal(obs.id), now=_now(),
        fixture_ids=["fx-1", "fx-2"],
    )
    passed = persist_validation(session, draft, {obs.id: obs}, _now(), tmp_path)
    session.flush()

    assert passed is False
    assert draft.status == models.DRAFT_FAILED_VALIDATION
    assert draft.preview_artifact_hash is None
    report = json.loads(draft.validation_report_json)
    assert report["passed"] is False


def test_persist_validation_uses_positive_fixture_not_boundary_fixture_for_preview(session, tmp_path, monkeypatch):
    # A "boundary"-kind fixture with expected_outcome="accept" ordered before the
    # genuine "positive"-kind fixture must NOT be selected as the preview source,
    # even though it also satisfies expected_outcome == "accept".
    job = _job(session)
    obs = _observation(session)
    proposal = DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
        ),
        guard_document=GuardDocument(guard_version=1, predicates=[PositivePredicate(value=FieldRefNode(field="n"))]),
        answer_expression=FieldRefNode(field="n"),
        animation_document=AnimationDocument(root={"kind": "label", "text": "n"}),
        classifier_bullet="use for X",
        fixtures=[
            ProposedFixture(kind="boundary", expected_outcome="accept", params={"n": 10}),
            ProposedFixture(kind="positive", expected_outcome="accept", observation_id=obs.id, params={"n": 5}),
        ],
    )
    draft = create_generated_draft(
        session, new_id="draft-4", job=job, proposal=proposal, now=_now(),
        fixture_ids=["fx-boundary", "fx-positive"],
    )

    captured = {}

    def fake_render(compiled_animation, known_fields, field_values, artifact_root):
        captured["field_values"] = field_values
        return "fakehash"

    monkeypatch.setattr("app.meta.validation_pipeline.render_and_store_preview", fake_render)

    passed = persist_validation(session, draft, {obs.id: obs}, _now(), tmp_path)
    session.flush()

    assert passed is True
    assert captured["field_values"] == {"n": 5}


def test_persist_validation_marks_draft_failed_on_compile_error(session, tmp_path):
    job = _job(session)
    proposal = _valid_proposal(None)
    draft = create_generated_draft(session, new_id="draft-3", job=job, proposal=proposal, now=_now(), fixture_ids=["fx-1", "fx-2"])
    # Corrupt the persisted animation document so compilation fails.
    draft.animation_document_json = json.dumps({"animation_version": 1, "root": {"kind": "label", "text": "x", "sneaky": True}})
    session.flush()

    passed = persist_validation(session, draft, {}, _now(), tmp_path)
    session.flush()

    assert passed is False
    assert draft.status == models.DRAFT_FAILED_VALIDATION
    report = json.loads(draft.validation_report_json)
    assert report["compile_error"] is not None
