import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.meta import db, models
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.drafts import persist_reviewable_draft
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.fingerprint import Fingerprint
from app.meta.validation import FixtureCheckResult
from app.meta.validation_pipeline import ValidatedCandidate
from app.meta.v3.compiler import compile_teaching_plan


def _now():
    return datetime(2026, 7, 30, tzinfo=timezone.utc)


def _fingerprint():
    return Fingerprint(
        fingerprint_version=1,
        operation_family="measure",
        representation_family="shape",
        number_domain="whole",
        operand_arity=2,
        step_count=2,
        grade_band="6-8",
    )


def _proposal():
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement",
            "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "literal", "value": 1},
            "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}], "intent": "show the rectangle"},
            {"id": "trace", "kind": "derive", "targets": [{"visual_ref": "rectangle"}], "intent": "trace every edge"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}], "intent": "state the perimeter"},
        ],
        "variation_seed": "fixture-edit-invalidation",
    })
    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="length", label="Length", description="", minimum=-100, maximum=100)],
        ),
        guard_document=GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=FieldRefNode(field="length"))],
        ),
        answer_expression=FieldRefNode(field="length"),
        teaching_plan_document=plan,
        classifier_bullet="Use for rectangle perimeter lessons.",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", observation_id="obs-1", params={"length": 5}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"length": -1}),
        ],
    )


def _candidate(proposal):
    scene_program = compile_teaching_plan(
        proposal.teaching_plan_document,
        proposal.answer_expression,
        frozenset({"length"}),
        CompileContext(concept_family="measure_shape", grade_band="6-8"),
    )
    return ValidatedCandidate(
        proposal=proposal,
        scene_program=scene_program,
        validation_report={
            "passed": True,
            "artifact_hash": "sha256:fixture-edit",
            "fixture_results": [],
            "preview_ok": True,
            "preview_artifact_hash": "sha256:preview-before-edit",
            "compiler_version": 3,
            "renderer_version": 3,
            "negative_predicate_coverage": [0],
        },
        quality_report={"passed": True, "checks": [], "artifact_hash": "sha256:fixture-edit"},
        preview_artifact_hash="sha256:preview-before-edit",
        fixture_results=[
            FixtureCheckResult("fixture-0", True, "params validated and guard passed"),
            FixtureCheckResult("fixture-1", True, "rejected", frozenset({0})),
        ],
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    monkeypatch.setenv("META_APPROVAL_ENABLED", "1")
    monkeypatch.setenv("META_REQUIRED_FIXTURE_COUNT", "1")
    monkeypatch.setenv("META_REVIEWER_TOKEN", "test-token")
    get_settings.cache_clear()
    from app.main import create_app
    yield TestClient(create_app(), headers={"Authorization": "Bearer test-token"})
    get_settings.cache_clear()


def _seed_passing_draft():
    proposal = _proposal()
    fingerprint = _fingerprint()
    with db.meta_session() as session:
        session.add(models.FallbackObservation(
            id="obs-1",
            candidate_id="candidate-1",
            source_excerpt="The rectangle length is 5 or 6 centimeters.",
            grade_level=6,
            observation_kind="unsupported_shape",
            excluded=False,
            created_at=_now(),
        ))
        job = models.GenerationJob(
            id="job-1",
            fingerprint_key="fixture-edit-key",
            fingerprint_version=fingerprint.fingerprint_version,
            fingerprint_json=fingerprint.model_dump_json(),
            trigger_observation_ids=json.dumps(["obs-1"]),
            status=models.JOB_SUCCEEDED,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(job)
        draft = persist_reviewable_draft(
            session,
            new_id="draft-1",
            job=job,
            candidate=_candidate(proposal),
            now=_now(),
        )
        return draft.id


def test_fixture_edit_invalidates_stale_approval_evidence(client):
    """Removing edit invalidation would leave the previous passing report approvable."""
    draft_id = _seed_passing_draft()
    before = client.get(f"/meta/drafts/{draft_id}").json()
    fixture_id = before["fixtures"][0]["id"]

    response = client.post(
        f"/meta/drafts/{draft_id}/fixtures/{fixture_id}",
        json={"params": {"length": 6}, "expected_result": {"answer": "6"}},
    )

    assert response.status_code == 200
    assert response.json()["params"] == {"length": 6}
    assert response.json()["structural_check_passed"] is None
    assert response.json()["structural_check_detail"] is None

    detail = client.get(f"/meta/drafts/{draft_id}").json()
    assert detail["status"] == models.DRAFT_PENDING_REVIEW
    assert detail["validation_report"] is None
    assert detail["quality_report"] is None
    assert detail["preview_url"] is None

    approval = client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": "fixture_edit", "math_semantics_confirmed": True},
    )
    assert approval.status_code == 422
    assert approval.json()["detail"] == "Draft has no passing validation report"


def test_fixture_edits_remain_pending_review_only(client):
    draft_id = _seed_passing_draft()
    fixture_id = client.get(f"/meta/drafts/{draft_id}").json()["fixtures"][0]["id"]
    with db.meta_session() as session:
        session.get(models.TemplateDraft, draft_id).status = models.DRAFT_FAILED_VALIDATION

    response = client.post(
        f"/meta/drafts/{draft_id}/fixtures/{fixture_id}",
        json={"params": {"length": 6}, "expected_result": {"answer": "6"}},
    )

    assert response.status_code == 409
