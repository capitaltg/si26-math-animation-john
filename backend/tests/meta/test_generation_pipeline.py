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
    # run_generation_job parses job.fingerprint_json into a real Fingerprint
    # (all 7 fields required, extra="forbid") before the propose step even
    # runs, so "{}" fails ValidationError unconditionally -- independent of
    # what's being mocked. Use a valid Fingerprint payload instead so the
    # test actually exercises the claim -> propose -> validate path the
    # brief describes.
    return Fingerprint(
        fingerprint_version=1,
        operation_family="compare",
        representation_family="grid",
        number_domain="whole",
        operand_arity=1,
        step_count=1,
        grade_band="K-2",
    ).model_dump_json()


def _seed_job_and_observation():
    with db.meta_session() as session:
        obs = models.FallbackObservation(
            id="obs-1", candidate_id="cand-1", source_excerpt="there are 5 apples",
            grade_level=2, observation_kind="unsupported_shape", excluded=False, created_at=_now(),
        )
        session.add(obs)
        session.flush()
        jobs.evaluate_and_enqueue(
            session, fingerprint_key="k1", fingerprint_version=1,
            fingerprint_json=_sample_fingerprint_json(),
            trigger_observation_ids=[obs.id], threshold=0, new_id="job-1", now=_now(),
        )


def _valid_proposal_dict(observation_id="obs-1"):
    proposal = DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
        ),
        guard_document=GuardDocument(guard_version=1, predicates=[PositivePredicate(value=FieldRefNode(field="n"))]),
        answer_expression=FieldRefNode(field="n"),
        animation_document=AnimationDocument(root={
            "kind": "sequence",
            "steps": [
                {"kind": "label", "ref": "n_label", "text": "n"},
                {"kind": "appear", "target_ref": "n_label"},
                {"kind": "wait", "seconds": 1},
            ],
        }),
        classifier_bullet="use for X",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", observation_id=observation_id, params={"n": 5}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"n": -1}),
        ],
    )
    return json.loads(proposal.model_dump_json())


@patch("app.meta.draft_generation.call_with_tool")
def test_run_generation_job_produces_pending_review_draft(mock_call, engine):
    _seed_job_and_observation()
    mock_call.return_value = ("propose_template_draft", _valid_proposal_dict())

    draft = run_generation_job(owner="worker-1")

    assert draft is not None
    assert draft.status == models.DRAFT_PENDING_REVIEW
    with db.meta_session() as session:
        job = session.get(models.GenerationJob, "job-1")
        assert job.status == models.JOB_SUCCEEDED


@patch("app.meta.draft_generation.call_with_tool")
def test_run_generation_job_fails_job_when_proposal_raises(mock_call, engine):
    _seed_job_and_observation()
    mock_call.side_effect = RuntimeError("bedrock unavailable")

    draft = run_generation_job(owner="worker-1")

    assert draft is None
    with db.meta_session() as session:
        job = session.get(models.GenerationJob, "job-1")
        assert job.status == models.JOB_FAILED
        assert "bedrock unavailable" in job.error_summary


def test_run_generation_job_returns_none_when_nothing_queued(engine):
    assert run_generation_job(owner="worker-1") is None


@pytest.mark.parametrize(
    ("feature_enabled", "codegen_enabled"),
    [(False, True), (True, False)],
)
@patch("app.meta.draft_generation.call_with_tool")
def test_run_generation_job_leaves_job_queued_when_generation_is_disabled(
    mock_call, engine, monkeypatch, feature_enabled, codegen_enabled
):
    _seed_job_and_observation()
    monkeypatch.setenv("META_TEMPLATES_ENABLED", str(int(feature_enabled)))
    monkeypatch.setenv("META_CODEGEN_ENABLED", str(int(codegen_enabled)))
    get_settings.cache_clear()

    assert run_generation_job(owner="worker-1") is None
    mock_call.assert_not_called()
    with db.meta_session() as session:
        assert session.get(models.GenerationJob, "job-1").status == models.JOB_QUEUED
