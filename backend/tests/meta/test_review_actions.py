import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.meta import db, jobs, models
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.fingerprint import Fingerprint
from app.meta.generation_pipeline import run_generation_job
from app.meta.review_actions import DraftNotRefinableError, reject_and_refine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    get_settings.cache_clear()
    yield engine
    get_settings.cache_clear()


def _now():
    return datetime(2026, 7, 28, tzinfo=timezone.utc)


def _sample_fingerprint_json():
    # The brief's test sketch used the literal placeholder "{}" here, but
    # run_generation_job / reject_and_refine both parse job.fingerprint_json
    # into a real Fingerprint (all 7 fields required, extra="forbid") before
    # the propose step even runs, so "{}" fails ValidationError
    # unconditionally, independent of what's being mocked. Use a valid
    # Fingerprint payload instead, matching the precedent already established
    # in test_generation_pipeline.py's _sample_fingerprint_json().
    return Fingerprint(
        fingerprint_version=1,
        operation_family="compare",
        representation_family="grid",
        number_domain="whole",
        operand_arity=1,
        step_count=1,
        grade_band="K-2",
    ).model_dump_json()


def _proposal_dict(observation_id="obs-1"):
    proposal = DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
        ),
        guard_document=GuardDocument(guard_version=1, predicates=[PositivePredicate(value=FieldRefNode(field="n"))]),
        answer_expression=FieldRefNode(field="n"),
        animation_document=AnimationDocument(root={"kind": "sequence", "steps": [
            {"kind": "label", "ref": "n_label", "text": "n"},
            {"kind": "appear", "target_ref": "n_label"},
            {"kind": "wait", "seconds": 1},
        ]}),
        classifier_bullet="use for X",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", observation_id=observation_id, params={"n": 5}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"n": -1}),
        ],
    )
    return json.loads(proposal.model_dump_json())


def _seeded_pending_review_draft():
    with db.meta_session() as session:
        obs = models.FallbackObservation(
            id="obs-1", candidate_id="cand-1", source_excerpt="there are 5 apples",
            grade_level=2, observation_kind="unsupported_shape", excluded=False, created_at=_now(),
        )
        session.add(obs)
        session.flush()
        jobs.evaluate_and_enqueue(
            session, fingerprint_key="k1", fingerprint_version=1, fingerprint_json=_sample_fingerprint_json(),
            trigger_observation_ids=[obs.id], threshold=0, new_id="job-1", now=_now(),
        )
    with patch("app.meta.draft_generation.call_with_tool") as mock_call:
        mock_call.return_value = ("propose_template_draft", _proposal_dict())
        return run_generation_job(owner="worker-1")


@patch("app.meta.draft_generation.call_with_tool")
def test_reject_and_refine_creates_new_pending_review_revision(mock_call, engine):
    draft = _seeded_pending_review_draft()
    mock_call.return_value = ("propose_template_draft", _proposal_dict())

    refined = reject_and_refine(
        draft.id, feedback="tighten the guard", reviewer_label="dev", max_refinements=5
    )

    assert refined is not None
    assert refined.revision == 2
    assert refined.parent_draft_id == draft.id
    assert refined.status == models.DRAFT_PENDING_REVIEW

    with db.meta_session() as session:
        original = session.get(models.TemplateDraft, draft.id)
        assert original.status == models.DRAFT_REJECTED
        assert original.reviewer_feedback == "tighten the guard"
        reviews = session.query(models.TemplateReview).filter_by(draft_id=draft.id).all()
        assert len(reviews) == 1
        assert reviews[0].decision == "reject"


@patch("app.meta.draft_generation.call_with_tool")
def test_reject_and_refine_marks_needs_manual_authoring_when_exhausted(mock_call, engine):
    draft = _seeded_pending_review_draft()
    mock_call.return_value = ("propose_template_draft", _proposal_dict())

    result = reject_and_refine(
        draft.id, feedback="still wrong", reviewer_label="dev", max_refinements=1
    )

    assert result is None
    mock_call.assert_not_called()
    with db.meta_session() as session:
        job = session.get(models.GenerationJob, draft.job_id)
        assert job.status == models.JOB_NEEDS_MANUAL


def test_reject_and_refine_raises_for_unknown_draft(engine):
    with pytest.raises(DraftNotRefinableError):
        reject_and_refine("no-such-draft", feedback="x", reviewer_label="dev", max_refinements=5)
