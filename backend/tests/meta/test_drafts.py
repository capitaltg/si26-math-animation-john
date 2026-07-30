import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.meta import db, models
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.dsl.expression import AddNode, FieldRefNode, MultiplyNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.validation import FixtureCheckResult
from app.meta.validation_pipeline import ValidatedCandidate


@pytest.fixture
def session(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    current_session = factory()
    try:
        yield current_session
    finally:
        current_session.close()


def _now():
    return datetime(2026, 7, 30, tzinfo=timezone.utc)


def _job(session):
    job = models.GenerationJob(
        id="job-1", fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids="[]", status=models.JOB_RUNNING, created_at=_now(), updated_at=_now(),
    )
    session.add(job)
    session.flush()
    return job


def _proposal():
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"}, "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}], "intent": "show the rectangle"},
            {"id": "trace", "kind": "derive", "targets": [{"visual_ref": "rectangle"}], "intent": "trace every edge"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}], "intent": "state the perimeter"},
        ],
        "variation_seed": "draft-persistence",
    })
    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[
                IntegerFieldSpec(name="length", label="Length", description="", minimum=-100, maximum=100),
                IntegerFieldSpec(name="width", label="Width", description="", minimum=-100, maximum=100),
            ],
        ),
        guard_document=GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=FieldRefNode(field="length"))],
        ),
        answer_expression=AddNode(operands=[
            MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="length")]),
            MultiplyNode(operands=[FieldRefNode(field="width"), FieldRefNode(field="width")]),
        ]),
        teaching_plan_document=plan,
        classifier_bullet="Use for rectangle perimeter lessons.",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", params={"length": 8, "width": 3}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"length": -1, "width": 3}),
        ],
    )


@pytest.fixture
def validated_candidate():
    proposal = _proposal()
    scene_program = compile_teaching_plan(
        proposal.teaching_plan_document,
        proposal.answer_expression,
        frozenset({"length", "width"}),
        CompileContext(concept_family="measure_shape", grade_band="6-8"),
    )
    return ValidatedCandidate(
        proposal=proposal,
        scene_program=scene_program,
        validation_report={
            "passed": True,
            "fixture_results": [],
            "preview_ok": True,
            "preview_artifact_hash": "sha256:preview",
            "compiler_version": 3,
            "renderer_version": 3,
            "negative_predicate_coverage": [0],
        },
        quality_report={"passed": True, "checks": [], "artifact_hash": "sha256:candidate"},
        preview_artifact_hash="sha256:preview",
        fixture_results=[
            FixtureCheckResult("fixture-0", True, "accepted"),
            FixtureCheckResult("fixture-1", True, "rejected", frozenset({0})),
        ],
    )


def test_template_draft_persists_dedicated_v3_documents(session, validated_candidate):
    from app.meta.drafts import persist_reviewable_draft

    draft = persist_reviewable_draft(
        session,
        new_id="draft-1",
        job=_job(session),
        candidate=validated_candidate,
        now=_now(),
    )

    assert json.loads(draft.teaching_plan_json)["plan_version"] == 3
    assert json.loads(draft.scene_program_json)["scene_version"] == 3
    assert json.loads(draft.quality_report_json)["passed"] is True
    assert not hasattr(draft, "animation_document_json")
    fixtures = session.query(models.TemplateDraftFixture).filter_by(draft_id=draft.id).all()
    assert [fixture.structural_check_passed for fixture in fixtures] == [True, True]


def test_persistence_rejects_fixture_result_with_unknown_identity(session, validated_candidate):
    from app.meta.drafts import persist_reviewable_draft

    candidate = replace(
        validated_candidate,
        fixture_results=[
            FixtureCheckResult("unexpected", True, "accepted"),
            *validated_candidate.fixture_results[1:],
        ],
    )

    with pytest.raises(ValueError, match="fixture result ids"):
        persist_reviewable_draft(
            session,
            new_id="draft-1",
            job=_job(session),
            candidate=candidate,
            now=_now(),
        )

    assert session.query(models.TemplateDraftFixture).count() == 0


def test_persistence_accepts_only_validated_candidates(session):
    from app.meta.drafts import persist_reviewable_draft

    with pytest.raises(TypeError, match="ValidatedCandidate"):
        persist_reviewable_draft(
            session,
            new_id="draft-1",
            job=_job(session),
            candidate=_proposal(),
            now=_now(),
        )
