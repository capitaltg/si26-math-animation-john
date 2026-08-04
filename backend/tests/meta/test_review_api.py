import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.meta import db, jobs, models
from app.meta.approval import (
    ApprovalConflictError,
    ApprovalPreconditionError,
    DraftNotApprovableError,
    DraftNotFoundError,
    RevokedConflictError,
    TemplateNameConflictError,
)
from app.meta.artifacts import store_artifact
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.drafts import persist_reviewable_draft
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.fingerprint import Fingerprint
from app.meta.generation_pipeline import run_generation_job
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3Failure, V3ValidationError
from app.meta.v3.quality import QualityCheck, QualityReport, validate_static_quality
from app.meta.validation import FixtureCheckResult
from app.meta.validation_pipeline import ValidatedCandidate, validate_candidate
from app.meta.versions import DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    monkeypatch.setenv("META_REVIEWER_TOKEN", "test-token")
    get_settings.cache_clear()
    from app.main import create_app
    yield TestClient(create_app(), headers={"Authorization": "Bearer test-token"})
    get_settings.cache_clear()


@pytest.fixture
def approval_client(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    monkeypatch.setenv("META_APPROVAL_ENABLED", "1")
    monkeypatch.setenv("META_REVIEWER_TOKEN", "test-token")
    get_settings.cache_clear()
    from app.main import create_app
    yield TestClient(create_app(), headers={"Authorization": "Bearer test-token"})
    get_settings.cache_clear()


@pytest.fixture
def client_without_token(tmp_path, monkeypatch):
    """Same server config as `client`, but the TestClient sends no Authorization
    header at all -- proves the gate rejects an absent header, not just a wrong one."""
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    monkeypatch.setenv("META_APPROVAL_ENABLED", "1")
    monkeypatch.setenv("META_REVIEWER_TOKEN", "test-token")
    get_settings.cache_clear()
    from app.main import create_app
    yield TestClient(create_app())
    get_settings.cache_clear()


def _now():
    return datetime(2026, 7, 28, tzinfo=timezone.utc)


def _sample_fingerprint_json():
    # run_generation_job parses job.fingerprint_json into a real Fingerprint
    # (all 7 fields required, extra="forbid"), so it must be a valid payload.
    return Fingerprint(
        fingerprint_version=1,
        operation_family="compare",
        representation_family="grid",
        number_domain="whole",
        operand_arity=1,
        step_count=1,
        grade_band="K-2",
    ).model_dump_json()


# ------------------------------------------------------------- v3 seeding
#
# There is no v2 `create_generated_draft` any more: persisting a reviewable
# draft in v3 requires a full `ValidatedCandidate` (a real compiled teaching
# plan/scene program plus passing validation and quality reports). These
# helpers build one directly -- real `compile_teaching_plan` and
# `validate_static_quality` calls, a real on-disk preview artifact via
# `store_artifact` (so `/meta/preview/{hash}` has something to serve) -- and
# hand `persist_reviewable_draft` the result, exactly like
# `test_review_api_v3.py`'s `_seed_passing_draft` does. This exercises the
# review API itself without paying for Bedrock or a real subprocess render.


def _plan(variation_seed="review-api"):
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "State a whole number result.",
        "primary_visual": {"kind": "label", "ref": "n_label", "text": "value"},
        "strategy": "group_reveal",
        "beats": [
            {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "n_label"}],
             "intent": "show the value"},
            {"id": "focus", "kind": "focus", "targets": [{"visual_ref": "n_label"}],
             "intent": "focus on the value"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "n_label"}],
             "intent": "state the result"},
        ],
        "variation_seed": variation_seed,
    })


def _proposal(observation_id="obs-1"):
    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
        ),
        guard_document=GuardDocument(guard_version=1, predicates=[PositivePredicate(value=FieldRefNode(field="n"))]),
        answer_expression=FieldRefNode(field="n"),
        teaching_plan_document=_plan(),
        classifier_bullet="use for X",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", observation_id=observation_id, params={"n": 5}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"n": -1}),
        ],
    )


def _candidate(proposal, *, artifact_root):
    scene_program = compile_teaching_plan(
        proposal.teaching_plan_document,
        proposal.answer_expression,
        frozenset(field.name for field in proposal.params_document.fields),
        CompileContext(concept_family="review_api_test", grade_band="K-2"),
    )
    quality_payload = validate_static_quality(proposal.teaching_plan_document, scene_program).model_payload()
    artifact_hash = f"sha256:{uuid4().hex}"
    quality_payload["artifact_hash"] = artifact_hash
    preview_hash = store_artifact(artifact_root, b"fake preview bytes for review-api tests")
    fixture_results = [
        FixtureCheckResult(
            f"fixture-{index}", True,
            "accepted" if fixture.kind == "positive" else "rejected",
            frozenset() if fixture.kind == "positive" else frozenset({0}),
        )
        for index, fixture in enumerate(proposal.fixtures)
    ]
    return ValidatedCandidate(
        proposal=proposal,
        scene_program=scene_program,
        validation_report={
            "passed": True,
            "fixture_results": [],
            "preview_ok": True,
            "preview_artifact_hash": preview_hash,
            "artifact_hash": artifact_hash,
            "compiler_version": DSL_COMPILER_VERSION,
            "renderer_version": DYNAMIC_RENDERER_VERSION,
            "negative_predicate_coverage": [0],
        },
        quality_report=quality_payload,
        preview_artifact_hash=preview_hash,
        fixture_results=fixture_results,
    )


def _seed_pending_review_draft(observation_id="obs-1", draft_id=None):
    with db.meta_session() as session:
        obs = models.FallbackObservation(
            id=observation_id, candidate_id="cand-1", source_excerpt="there are 5 apples",
            grade_level=2, observation_kind="unsupported_shape", excluded=False, created_at=_now(),
        )
        session.add(obs)
        session.flush()
        job = models.GenerationJob(
            id=f"job-{observation_id}", fingerprint_key="k1", fingerprint_version=1,
            fingerprint_json=_sample_fingerprint_json(),
            trigger_observation_ids=json.dumps([observation_id]),
            status=models.JOB_SUCCEEDED, created_at=_now(), updated_at=_now(),
        )
        session.add(job)
        session.flush()
        proposal = _proposal(observation_id)
        candidate = _candidate(proposal, artifact_root=get_settings().meta_artifact_root)
        return persist_reviewable_draft(
            session, new_id=draft_id or uuid4().hex, job=job, candidate=candidate, now=_now(),
        )


# A teaching plan with realistic beat text, used only by the v3 review-evidence
# test (Step 1 of the brief): the first beat's id must be "reveal_values" so
# `timeline[0].beat_id` proves the compiled timeline -- not just the teaching
# plan -- made it through to the review payload.
def _evidence_plan():
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Compare three numbers to find the largest.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [
                {"node": "field_ref", "field": "a"},
                {"node": "field_ref", "field": "b"},
                {"node": "field_ref", "field": "c"},
            ],
        },
        "strategy": "group_reveal",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together"},
            {"id": "focus_largest", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 2}],
             "intent": "focus on the largest value"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "values"}],
             "intent": "state the largest value"},
        ],
        "variation_seed": "review-evidence",
    })


def _evidence_proposal():
    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[
                IntegerFieldSpec(name="a", label="A", description="", minimum=1, maximum=10),
                IntegerFieldSpec(name="b", label="B", description="", minimum=1, maximum=10),
                IntegerFieldSpec(name="c", label="C", description="", minimum=1, maximum=10),
            ],
        ),
        guard_document=GuardDocument(guard_version=1, predicates=[PositivePredicate(value=FieldRefNode(field="a"))]),
        answer_expression=FieldRefNode(field="c"),
        teaching_plan_document=_evidence_plan(),
        classifier_bullet="use for comparing three numbers",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", observation_id="obs-evidence", params={"a": 3, "b": 5, "c": 9}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"a": -1, "b": 5, "c": 9}),
        ],
    )


@pytest.fixture
def pending_v3_draft(client):
    with db.meta_session() as session:
        obs = models.FallbackObservation(
            id="obs-evidence", candidate_id="cand-evidence", source_excerpt="3, 5, and 9",
            grade_level=3, observation_kind="unsupported_shape", excluded=False, created_at=_now(),
        )
        session.add(obs)
        session.flush()
        job = models.GenerationJob(
            id="job-evidence", fingerprint_key="k-evidence", fingerprint_version=1,
            fingerprint_json=_sample_fingerprint_json(), trigger_observation_ids=json.dumps(["obs-evidence"]),
            status=models.JOB_SUCCEEDED, created_at=_now(), updated_at=_now(),
        )
        session.add(job)
        session.flush()
        proposal = _evidence_proposal()
        candidate = _candidate(proposal, artifact_root=get_settings().meta_artifact_root)
        return persist_reviewable_draft(
            session, new_id="draft-evidence", job=job, candidate=candidate, now=_now(),
        )


@pytest.fixture
def failed_private_job(client, monkeypatch):
    """A generation attempt that never becomes a draft: every retry fails
    validation, so the job is marked needs-manual and no `TemplateDraft` row
    is ever created -- the failure stays entirely private. Named for the
    brief's Step 1 test, which proves this can never leak into the reviewer's
    pending-review list."""
    with db.meta_session() as session:
        obs = models.FallbackObservation(
            id="obs-failed", candidate_id="cand-failed", source_excerpt="ambiguous shape",
            grade_level=2, observation_kind="unsupported_shape", excluded=False, created_at=_now(),
        )
        session.add(obs)
        session.flush()
        jobs.evaluate_and_enqueue(
            session, fingerprint_key="k-failed", fingerprint_version=1,
            fingerprint_json=_sample_fingerprint_json(), trigger_observation_ids=[obs.id],
            threshold=0, new_id="job-failed", now=_now(),
        )

    failure = V3Failure(
        code="serial_simple_reveal", path="timeline", expected="together",
        observed="stagger", hint="reveal values together",
    )
    monkeypatch.setattr(
        "app.meta.generation_pipeline.propose_template_draft",
        lambda *args, **kwargs: _proposal(),
    )

    def _always_fails(*args, **kwargs):
        raise V3ValidationError(failure)

    monkeypatch.setattr("app.meta.generation_pipeline.validate_candidate", _always_fails)

    assert run_generation_job(owner="worker-1") is None
    with db.meta_session() as session:
        assert session.query(models.TemplateDraft).count() == 0
    return "job-failed"


def _seed_approvable_draft(
    *,
    draft_id="draft-approve",
    fingerprint_key="k-approve",
    positive_count=5,
    status=models.DRAFT_PENDING_REVIEW,
    passed=True,
    report_hash=None,
    coverage=None,
    set_expected_result=True,
):
    """Seed a draft with enough real, confirmed fixtures and a passing report
    to satisfy every ``approve_draft_service`` precondition by default, with
    knobs to violate exactly one precondition at a time (mirrors
    ``tests/meta/test_approval.py``'s ``_seed_draft``). Built directly from
    real DSL document models and TemplateDraft/TemplateDraftFixture rows,
    not via a draft-creation pipeline helper -- the v2 `create_generated_draft`
    this used to call is gone in v3."""
    with db.meta_session() as session:
        job = models.GenerationJob(
            id=f"job-{draft_id}", fingerprint_key=fingerprint_key, fingerprint_version=1,
            fingerprint_json="{}", trigger_observation_ids="[]", status=models.JOB_SUCCEEDED,
            created_at=_now(), updated_at=_now(),
        )
        session.add(job)

        for i in range(positive_count):
            session.add(models.FallbackObservation(
                id=f"obs-{draft_id}-{i}", candidate_id=f"cand-{draft_id}-{i}",
                source_excerpt="there are 5 apples", grade_level=2,
                observation_kind="unsupported_shape", excluded=False, created_at=_now(),
            ))
        session.flush()

        params_document = ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
        )
        guard_document = GuardDocument(
            guard_version=1, predicates=[PositivePredicate(value=FieldRefNode(field="n"))],
        )
        answer_expression = FieldRefNode(field="n")
        plan = _plan(variation_seed=f"approve-{draft_id}")
        scene_program = compile_teaching_plan(
            plan, answer_expression, frozenset({"n"}),
            CompileContext(concept_family="review_api_approve", grade_band="K-2"),
        )
        artifact_hash = f"sha256:{draft_id}"

        draft = models.TemplateDraft(
            id=draft_id, job_id=job.id, fingerprint_key=fingerprint_key, fingerprint_version=1,
            fingerprint_json="{}", revision=1,
            params_document_json=params_document.model_dump_json(),
            guard_document_json=guard_document.model_dump_json(),
            answer_expression_json=answer_expression.model_dump_json(),
            teaching_plan_json=plan.model_dump_json(),
            scene_program_json=scene_program.model_dump_json(),
            classifier_bullet="use for X",
            dsl_schema_versions_json=json.dumps({"params": 1, "guard": 1, "teaching_plan": 3, "scene": 3}),
            artifact_hash=artifact_hash,
            status=status,
            created_at=_now(), updated_at=_now(),
        )
        session.add(draft)
        session.flush()

        for i in range(positive_count):
            session.add(models.TemplateDraftFixture(
                id=f"{draft_id}-fixture-pos-{i}", draft_id=draft_id,
                observation_id=f"obs-{draft_id}-{i}", kind="positive", expected_outcome="accept",
                generation_method="proposed", params_json=json.dumps({"n": 5}),
                expected_result_json=json.dumps({"answer": "5"}) if set_expected_result else None,
                structural_check_passed=True, created_at=_now(),
            ))
        session.add(models.TemplateDraftFixture(
            id=f"{draft_id}-fixture-neg", draft_id=draft_id, observation_id=None,
            kind="negative", expected_outcome="reject", generation_method="proposed",
            params_json=json.dumps({"n": -1}), expected_result_json=None,
            structural_check_passed=True, created_at=_now(),
        ))

        draft.preview_artifact_hash = "preview-hash"
        cov = coverage if coverage is not None else [0]
        report = {
            "passed": passed,
            "compile_error": None,
            "fixture_results": [],
            "preview_ok": passed,
            "preview_error": None,
            "artifact_hash": report_hash if report_hash is not None else artifact_hash,
            "compiler_version": DSL_COMPILER_VERSION,
            "renderer_version": DYNAMIC_RENDERER_VERSION,
            "negative_predicate_coverage": cov,
        }
        draft.validation_report_json = json.dumps(report)
        draft.quality_report_json = json.dumps({"passed": passed, "checks": [], "artifact_hash": artifact_hash})
        session.flush()
        return draft.id


# --------------------------------------------------------------- list/detail


def test_list_drafts_filters_by_status(client):
    draft = _seed_pending_review_draft()
    resp = client.get("/meta/drafts", params={"status": "pending_review"})
    assert resp.status_code == 200
    assert [d["id"] for d in resp.json()] == [draft.id]


def test_list_returns_only_pending_review(client, failed_private_job):
    rows = client.get("/meta/drafts?status=pending_review").json()
    assert rows == []


def test_list_never_leaks_non_pending_drafts_regardless_of_status_query(client):
    """The reviewer list must never contain private/failed candidates no
    matter what `status` value a caller passes."""
    pending = _seed_pending_review_draft()
    _seed_approvable_draft(draft_id="draft-approved-x", fingerprint_key="k-approved-x", status=models.DRAFT_APPROVED)
    _seed_approvable_draft(draft_id="draft-rejected-x", fingerprint_key="k-rejected-x", status=models.DRAFT_REJECTED)

    for query in ({"status": "approved"}, {"status": "rejected"}, {}):
        rows = client.get("/meta/drafts", params=query).json()
        assert [row["id"] for row in rows] == [pending.id]


def test_get_draft_detail_includes_fixtures_and_preview_url(client, monkeypatch):
    monkeypatch.setenv("META_REQUIRED_FIXTURE_COUNT", "1")
    get_settings.cache_clear()
    draft = _seed_pending_review_draft()
    resp = client.get(f"/meta/drafts/{draft.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["classifier_bullet"] == "use for X"
    assert len(body["fixtures"]) == 2
    assert body["fixtures"][0]["observation_id"] == "obs-1"
    assert body["preview_url"] == f"/meta/preview/{draft.preview_artifact_hash}"
    assert body["required_fixture_count"] == 1


def test_draft_detail_returns_v3_review_evidence(client, pending_v3_draft):
    detail = client.get(f"/meta/drafts/{pending_v3_draft.id}").json()
    assert detail["teaching_plan"]["plan_version"] == 3
    assert detail["timeline"][0]["beat_id"] == "reveal_values"
    assert detail["quality_report"]["passed"] is True
    assert "animation_document" not in detail
    # The API must forward the compiler's *declared* total_duration_seconds,
    # not a value derived from the timeline entries: each TimedAction's
    # duration_seconds is independently clamped to MAX_ACTION_SECONDS (2.0s),
    # so summing/maxing timeline entries can undercount the real total and
    # even report a scene as shorter than the 6-second floor when it is not.
    real_scene_program = json.loads(pending_v3_draft.scene_program_json)
    assert detail["total_duration_seconds"] == real_scene_program["total_duration_seconds"]
    assert 6.0 <= detail["total_duration_seconds"] <= 12.0


@pytest.mark.parametrize(
    "status",
    [models.DRAFT_APPROVED, models.DRAFT_REJECTED, models.DRAFT_GENERATED, models.DRAFT_SUPERSEDED],
)
def test_get_draft_404s_for_any_non_pending_status(client, status):
    """A draft ID is proof the candidate is already approvable -- once it
    leaves pending_review (approved, rejected, superseded, or never reached
    review), direct access must 404 like an unknown draft. No audit endpoint
    in this codebase reads an approved draft by id, so there is no carve-out."""
    draft_id = _seed_approvable_draft(draft_id=f"draft-{status}", fingerprint_key=f"k-{status}", status=status)
    resp = client.get(f"/meta/drafts/{draft_id}")
    assert resp.status_code == 404


def test_get_preview_serves_stored_artifact(client):
    draft = _seed_pending_review_draft()
    resp = client.get(f"/meta/preview/{draft.preview_artifact_hash}")
    assert resp.status_code == 200
    assert len(resp.content) > 0


# ----------------------------------------------------------- fixture edits


def test_update_fixture_params_and_expected_result(client):
    draft = _seed_pending_review_draft()
    fixture_id = client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]["id"]
    response = client.post(
        f"/meta/drafts/{draft.id}/fixtures/{fixture_id}",
        json={"params": {"n": 6}, "expected_result": {"answer": "6"}},
    )
    assert response.status_code == 200
    assert response.json()["params"] == {"n": 6}
    assert response.json()["expected_result"] == {"answer": "6"}


def test_update_fixture_rejects_invalid_params_without_persisting(client):
    draft = _seed_pending_review_draft()
    fixture_id = client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]["id"]
    response = client.post(
        f"/meta/drafts/{draft.id}/fixtures/{fixture_id}",
        json={"params": {"n": -1}, "expected_result": {"answer": "-1"}},
    )
    assert response.status_code == 422
    assert client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]["params"] == {"n": 5}


def test_update_fixture_rejects_result_mismatch_without_persisting(client):
    draft = _seed_pending_review_draft()
    fixture_id = client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]["id"]
    response = client.post(
        f"/meta/drafts/{draft.id}/fixtures/{fixture_id}",
        json={"params": {"n": 6}, "expected_result": {"answer": "7"}},
    )
    assert response.status_code == 422
    fixture = client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]
    assert fixture["params"] == {"n": 5}
    assert fixture["expected_result"] is None


def test_update_fixture_rejects_unevaluable_params_without_persisting(client):
    draft = _seed_pending_review_draft()
    with db.meta_session() as session:
        stored_draft = session.get(models.TemplateDraft, draft.id)
        stored_draft.params_document_json = json.dumps({
            "params_version": 1,
            "fields": [{
                "type": "integer", "name": "n", "label": "N", "description": "",
                "minimum": 0, "maximum": 10,
            }],
        })
        stored_draft.guard_document_json = json.dumps({
            "guard_version": 1,
            "predicates": [{
                "predicate": "range",
                "value": {"node": "field_ref", "field": "n"},
                "minimum": {"node": "literal", "value": 0},
                "maximum": {"node": "literal", "value": 10},
            }],
        })
        stored_draft.answer_expression_json = json.dumps({
            "node": "divide",
            "operands": [
                {"node": "literal", "value": 1},
                {"node": "field_ref", "field": "n"},
            ],
        })

    fixture_id = client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]["id"]
    response = client.post(
        f"/meta/drafts/{draft.id}/fixtures/{fixture_id}",
        json={"params": {"n": 0}, "expected_result": {"answer": "0"}},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Fixture params cannot be evaluated"
    fixture = client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]
    assert fixture["params"] == {"n": 5}
    assert fixture["expected_result"] is None


def test_update_fixture_confirming_unchanged_params_preserves_approval_evidence(client, pending_v3_draft):
    """Defect B: `update_fixture` is the only production writer of
    expected_result_json, and unconditionally nulling structural_check_passed
    and the three draft-level reports every time it runs means the one path
    that can satisfy approval precondition 8 (a human-confirmed answer)
    always breaks precondition 3/5 in the same transaction -- no production
    draft could ever become approvable. Confirming the SAME params must
    preserve all four, since nothing about the rendered candidate changed."""
    draft_id = pending_v3_draft.id
    before = client.get(f"/meta/drafts/{draft_id}").json()
    fixture = before["fixtures"][0]
    assert fixture["observation_id"] == "obs-evidence"
    assert fixture["params"] == {"a": 3, "b": 5, "c": 9}
    assert fixture["structural_check_passed"] is True
    assert before["validation_report"] is not None
    assert before["quality_report"] is not None
    assert before["preview_url"] is not None

    response = client.post(
        f"/meta/drafts/{draft_id}/fixtures/{fixture['id']}",
        json={"params": {"a": 3, "b": 5, "c": 9}, "expected_result": {"answer": "9"}},
    )
    assert response.status_code == 200
    assert response.json()["structural_check_passed"] is True

    after = client.get(f"/meta/drafts/{draft_id}").json()
    assert after["validation_report"] == before["validation_report"]
    assert after["quality_report"] == before["quality_report"]
    assert after["preview_url"] == before["preview_url"]


def test_update_fixture_reordered_or_reformatted_params_count_as_unchanged(client, pending_v3_draft):
    """Params that differ only in JSON key order, or in numeric formatting
    (9 vs 9.0), must not masquerade as a real change -- the comparison must
    be over parsed values, not the raw JSON string. Both cases are actually
    exercised here, not just asserted by name: reordering is handled by
    ``json.loads`` producing a plain dict (key order is not part of dict
    equality); the numeric-format case is load-bearing on two distinct
    mechanisms working together -- pydantic's lax float-to-int coercion
    surviving ``params_cls.model_validate`` (``review_api.py``, which runs
    BEFORE the params comparison, so a rejected float would 422 rather than
    ever reach the unchanged-params branch) and then ``3 == 3.0`` in the
    dict comparison itself."""
    draft_id = pending_v3_draft.id
    before = client.get(f"/meta/drafts/{draft_id}").json()
    fixture = before["fixtures"][0]
    assert fixture["params"] == {"a": 3, "b": 5, "c": 9}

    reordered = client.post(
        f"/meta/drafts/{draft_id}/fixtures/{fixture['id']}",
        json={"params": {"c": 9, "a": 3, "b": 5}, "expected_result": {"answer": "9"}},
    )
    assert reordered.status_code == 200
    assert reordered.json()["structural_check_passed"] is True

    after_reorder = client.get(f"/meta/drafts/{draft_id}").json()
    assert after_reorder["validation_report"] == before["validation_report"]
    assert after_reorder["quality_report"] == before["quality_report"]
    assert after_reorder["preview_url"] == before["preview_url"]

    reformatted = client.post(
        f"/meta/drafts/{draft_id}/fixtures/{fixture['id']}",
        json={"params": {"a": 3.0, "b": 5, "c": 9}, "expected_result": {"answer": "9"}},
    )
    assert reformatted.status_code == 200, reformatted.json()
    assert reformatted.json()["structural_check_passed"] is True

    after_reformat = client.get(f"/meta/drafts/{draft_id}").json()
    assert after_reformat["validation_report"] == before["validation_report"]
    assert after_reformat["quality_report"] == before["quality_report"]
    assert after_reformat["preview_url"] == before["preview_url"]


def test_update_fixture_changed_params_still_invalidates_approval_evidence(client, pending_v3_draft):
    """The narrowed invalidation must keep Task 10's fail-closed behavior
    exactly for an actual params change (not just widen it to never fire)."""
    draft_id = pending_v3_draft.id
    fixture = client.get(f"/meta/drafts/{draft_id}").json()["fixtures"][0]

    response = client.post(
        f"/meta/drafts/{draft_id}/fixtures/{fixture['id']}",
        json={"params": {"a": 4, "b": 5, "c": 9}, "expected_result": {"answer": "9"}},
    )
    assert response.status_code == 200
    assert response.json()["structural_check_passed"] is None
    assert response.json()["structural_check_detail"] is None

    after = client.get(f"/meta/drafts/{draft_id}").json()
    assert after["validation_report"] is None
    assert after["quality_report"] is None
    assert after["preview_url"] is None


def test_update_fixture_rejects_edit_on_approved_draft_without_mutation(client):
    draft = _seed_pending_review_draft()
    fixture_id = client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]["id"]
    with db.meta_session() as session:
        stored = session.get(models.TemplateDraft, draft.id)
        stored.status = models.DRAFT_APPROVED

    response = client.post(
        f"/meta/drafts/{draft.id}/fixtures/{fixture_id}",
        json={"params": {"n": 6}, "expected_result": {"answer": "6"}},
    )

    assert response.status_code == 409
    # The draft is no longer pending_review, so GET must now 404 it (the
    # reviewer never sees non-pending drafts) -- check the no-mutation claim
    # against the database directly rather than through the review API.
    assert client.get(f"/meta/drafts/{draft.id}").status_code == 404
    with db.meta_session() as session:
        fixture = session.get(models.TemplateDraftFixture, fixture_id)
        assert json.loads(fixture.params_json) == {"n": 5}
        assert fixture.expected_result_json is None
        stored = session.get(models.TemplateDraft, draft.id)
        assert stored.status == models.DRAFT_APPROVED


# --------------------------------------------------------------- reject flow


def test_reject_draft_creates_new_revision(client, monkeypatch):
    draft = _seed_pending_review_draft()
    monkeypatch.setattr(
        "app.meta.generation_pipeline.propose_template_draft",
        lambda *args, **kwargs: _proposal(),
    )
    monkeypatch.setattr(
        "app.meta.generation_pipeline.validate_candidate",
        lambda *args, **kwargs: _candidate(_proposal(), artifact_root=get_settings().meta_artifact_root),
    )
    resp = client.post(f"/meta/drafts/{draft.id}/reject", json={"feedback": "too loose"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_manual_authoring"] is False
    assert body["new_draft"]["revision"] == 2


def test_reject_draft_restores_pending_review_when_refinement_fails(client, monkeypatch):
    draft = _seed_pending_review_draft()

    def _bedrock_unavailable(*args, **kwargs):
        raise RuntimeError("bedrock unavailable")

    monkeypatch.setattr("app.meta.generation_pipeline.propose_template_draft", _bedrock_unavailable)

    resp = client.post(f"/meta/drafts/{draft.id}/reject", json={"feedback": "too loose"})

    assert resp.status_code == 409
    assert "retried" in resp.json()["detail"]
    with db.meta_session() as session:
        original = session.get(models.TemplateDraft, draft.id)
        assert original.status == models.DRAFT_PENDING_REVIEW
        assert original.reviewer_feedback == "too loose"
        assert session.query(models.TemplateReview).filter_by(draft_id=draft.id).count() == 1


# ------------------------------------------------------------------ approve


def test_approve_disabled_returns_409_before_checking_preconditions(client):
    # meta_approval_enabled defaults to False on the `client` fixture. The
    # flag must be checked before the request is even validated against real
    # preconditions -- proven here by sending a deliberately-failing
    # confirmation flag and still getting 409, not 422.
    draft_id = _seed_approvable_draft(draft_id="draft-disabled", fingerprint_key="k-disabled")
    resp = client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": "apples_count", "math_semantics_confirmed": False},
    )
    assert resp.status_code == 409
    assert "disabled" in resp.json()["detail"].lower()


def test_approve_success_returns_200_and_publishes_version(approval_client):
    draft_id = _seed_approvable_draft(draft_id="draft-ok", fingerprint_key="k-ok")
    resp = approval_client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": "apples_count", "reviewer_label": "qa", "math_semantics_confirmed": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["template_name"] == "apples_count"
    assert body["status"] == "enabled"
    assert body["template_version_id"]

    with db.meta_session() as session:
        version = session.query(models.TemplateVersion).filter_by(fingerprint_key="k-ok").one()
        assert version.status == "enabled"
        assert version.id == body["template_version_id"]
        reloaded_draft = session.get(models.TemplateDraft, draft_id)
        assert reloaded_draft.status == models.DRAFT_APPROVED


def test_approve_succeeds_after_confirming_a_fixture_through_the_real_production_pipeline(
    approval_client, monkeypatch, tmp_path,
):
    """The required end-to-end proof: walks the real production path --
    ``validate_candidate()`` (the actual production builder, not a hand-built
    ``ValidatedCandidate`` literal) -> ``persist_reviewable_draft()`` ->
    ``update_fixture()`` to confirm the human-verified answer for UNCHANGED
    params -> ``approve_draft_service()``. This single test fails if either
    defect A or defect B is reintroduced:
      - defect A: if ``build_validation_report`` ever again drops (or
        mismatches) ``artifact_hash``, approval 422s at precondition 4
        ("Validation report is stale: artifact hash mismatch");
      - defect B: if ``update_fixture`` ever again unconditionally nulls
        ``structural_check_passed``/``validation_report_json``/
        ``quality_report_json``/``preview_artifact_hash`` even for an
        unchanged-params confirmation, approval 422s at precondition 3
        ("Draft has no passing validation report").
    (Defect C is proven separately at the render-probe layer in
    ``test_dynamic_render_worker.py``, since this plan's "label" visual has
    no dimension relations to observe.)
    """
    monkeypatch.setenv("META_REQUIRED_FIXTURE_COUNT", "1")
    get_settings.cache_clear()
    # TWO stubs are installed here, not one (same pair as
    # test_validation_pipeline.py's `passing_render_probe` fixture):
    #   1. `render_preview_and_probe` -- replaces the expensive manim probe
    #      subprocess with the sentinel manifest `{"probe": "complete"}`.
    #   2. `validate_rendered_quality` -- stubbed *because of* (1). That
    #      sentinel is not real probe output and would fail
    #      `check_manifest_contract` outright, so this stub is load-bearing:
    #      without it nothing past preview would run at all.
    # So the rendered-quality gate is REPLACED here, not merely its renderer.
    # This test's value is the API/persistence path: compilation, fixture
    # validation, validation- and quality-report assembly, `persist_reviewable_
    # draft`, `update_fixture` and the entire approval transaction all run the
    # real production code. Real rendered-gate coverage lives in
    # `tests/meta/v3/test_render_probe.py` and, against a real probe
    # subprocess, in `test_demo_end_to_end.py` / `test_v3_demo_quality.py`.
    monkeypatch.setattr(
        "app.meta.validation_pipeline.render_preview_and_probe",
        lambda *args, **kwargs: ("sha256:e2e-preview", {"probe": "complete"}),
    )
    monkeypatch.setattr(
        "app.meta.validation_pipeline.validate_rendered_quality",
        lambda probe: QualityReport(True, [
            QualityCheck("render_probe_complete", True, "probe", "passed"),
        ]),
    )

    observation_id = "obs-e2e"
    with db.meta_session() as session:
        session.add(models.FallbackObservation(
            id=observation_id, candidate_id="cand-e2e", source_excerpt="there are 5 apples",
            grade_level=2, observation_kind="unsupported_shape", excluded=False, created_at=_now(),
        ))
        job = models.GenerationJob(
            id="job-e2e", fingerprint_key="k-e2e", fingerprint_version=1,
            fingerprint_json=_sample_fingerprint_json(), trigger_observation_ids=json.dumps([observation_id]),
            status=models.JOB_SUCCEEDED, created_at=_now(), updated_at=_now(),
        )
        session.add(job)
        session.flush()

        observation = session.get(models.FallbackObservation, observation_id)
        candidate = validate_candidate(
            _proposal(observation_id),
            observations_by_id={observation_id: observation},
            artifact_root=tmp_path / "artifacts",
            compile_context=CompileContext(concept_family="review_api_e2e", grade_band="K-2"),
        )
        draft = persist_reviewable_draft(
            session, new_id="draft-e2e", job=job, candidate=candidate, now=_now(),
        )
        draft_id = draft.id

    detail = approval_client.get(f"/meta/drafts/{draft_id}").json()
    fixture = next(f for f in detail["fixtures"] if f["observation_id"] == observation_id)
    assert fixture["params"] == {"n": 5}

    confirm = approval_client.post(
        f"/meta/drafts/{draft_id}/fixtures/{fixture['id']}",
        json={"params": {"n": 5}, "expected_result": {"answer": "5"}},
    )
    assert confirm.status_code == 200
    assert confirm.json()["structural_check_passed"] is True

    approve = approval_client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": "e2e_apples", "math_semantics_confirmed": True},
    )
    assert approve.status_code == 200, approve.json()
    assert approve.json()["status"] == "enabled"


def test_approve_unconfirmed_semantics_returns_422(approval_client):
    draft_id = _seed_approvable_draft(draft_id="draft-unconf", fingerprint_key="k-unconf")
    resp = approval_client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": "apples", "math_semantics_confirmed": False},
    )
    assert resp.status_code == 422


def test_approve_unknown_draft_returns_404(approval_client):
    resp = approval_client.post(
        "/meta/drafts/does-not-exist/approve",
        json={"template_name": "apples", "math_semantics_confirmed": True},
    )
    assert resp.status_code == 404


def test_approve_wrong_status_returns_409(approval_client):
    draft_id = _seed_approvable_draft(
        draft_id="draft-wrong-status", fingerprint_key="k-wrong-status", status=models.DRAFT_GENERATED,
    )
    resp = approval_client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": "apples", "math_semantics_confirmed": True},
    )
    assert resp.status_code == 409


def test_approve_revoked_fingerprint_returns_409(approval_client):
    draft_id = _seed_approvable_draft(draft_id="draft-revoked", fingerprint_key="k-revoked")
    with db.meta_session() as session:
        session.add(models.TemplateVersion(
            id="ver-revoked", fingerprint_key="k-revoked", template_name="old_name",
            draft_id=None, artifact_hash="sha256:old", status=models.TEMPLATE_VERSION_REVOKED,
            created_at=_now(), updated_at=_now(),
        ))
    resp = approval_client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": "apples", "math_semantics_confirmed": True},
    )
    assert resp.status_code == 409


def test_approve_template_name_collision_returns_409(approval_client):
    draft_id = _seed_approvable_draft(draft_id="draft-name-collision", fingerprint_key="k-collision")
    with db.meta_session() as session:
        session.add(models.TemplateVersion(
            id="ver-other", fingerprint_key="k-other", template_name="taken",
            draft_id=None, artifact_hash="sha256:other", status=models.TEMPLATE_VERSION_ENABLED,
            created_at=_now(), updated_at=_now(),
        ))
    resp = approval_client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": "taken", "math_semantics_confirmed": True},
    )
    assert resp.status_code == 409


@pytest.mark.parametrize("exc_cls,expected_status", [
    (DraftNotFoundError, 404),
    (DraftNotApprovableError, 409),
    (ApprovalPreconditionError, 422),
    (RevokedConflictError, 409),
    (TemplateNameConflictError, 409),
    (ApprovalConflictError, 409),
])
def test_approve_maps_each_service_exception_to_http_status(exc_cls, expected_status, approval_client):
    from unittest.mock import patch

    with patch("app.meta.review_api.approve_draft_service", side_effect=exc_cls("boom")):
        resp = approval_client.post(
            "/meta/drafts/any-id/approve",
            json={"template_name": "apples", "math_semantics_confirmed": True},
        )
    assert resp.status_code == expected_status
    assert resp.json()["detail"] == "boom"


# ----------------------------------------------------------------- revalidate
#
# Issue #63: `update_fixture` correctly clears approval evidence when a
# reviewer actually changes a fixture's params, but until `/revalidate` existed
# nothing could rebuild it, so the edited draft could never leave
# pending_review and rejecting it discarded the correction.


@pytest.fixture
def stubbed_render(monkeypatch):
    """Replace the manim probe subprocess for both the seeding validation and
    the revalidation under test, exactly as
    `test_approve_succeeds_after_confirming_a_fixture_through_the_real_production_pipeline`
    does. `validate_rendered_quality` must be stubbed too: the sentinel
    manifest is not real probe output and would fail the manifest contract, so
    without it nothing past preview would run at all.

    The preview hash changes on every call so a test can prove revalidation
    re-rendered rather than leaving the pre-edit preview in place.
    """
    renders = {"count": 0}

    def _render(*args, **kwargs):
        renders["count"] += 1
        return f"sha256:revalidate-preview-{renders['count']}", {"probe": "complete"}

    monkeypatch.setattr("app.meta.validation_pipeline.render_preview_and_probe", _render)
    monkeypatch.setattr(
        "app.meta.validation_pipeline.validate_rendered_quality",
        lambda probe: QualityReport(True, [
            QualityCheck("render_probe_complete", True, "probe", "passed"),
        ]),
    )
    return renders


def _seed_revalidatable_draft(
    *, draft_id, fingerprint_key, observation_id, source_excerpt, artifact_root,
):
    """Seed through the real production path -- `validate_candidate()` then
    `persist_reviewable_draft()` -- so the draft carries genuine reports whose
    artifact hash matches the draft's, and so revalidation is re-running the
    same pipeline that produced it."""
    with db.meta_session() as session:
        session.add(models.FallbackObservation(
            id=observation_id, candidate_id=f"cand-{observation_id}",
            source_excerpt=source_excerpt, grade_level=2,
            observation_kind="unsupported_shape", excluded=False, created_at=_now(),
        ))
        job = models.GenerationJob(
            id=f"job-{draft_id}", fingerprint_key=fingerprint_key, fingerprint_version=1,
            fingerprint_json=_sample_fingerprint_json(),
            trigger_observation_ids=json.dumps([observation_id]),
            status=models.JOB_SUCCEEDED, created_at=_now(), updated_at=_now(),
        )
        session.add(job)
        session.flush()

        observation = session.get(models.FallbackObservation, observation_id)
        candidate = validate_candidate(
            _proposal(observation_id),
            observations_by_id={observation_id: observation},
            artifact_root=artifact_root,
            compile_context=CompileContext(concept_family="revalidate", grade_band="K-2"),
        )
        draft = persist_reviewable_draft(
            session, new_id=draft_id, job=job, candidate=candidate, now=_now(),
        )
        return draft.id


def test_revalidate_after_a_params_edit_restores_evidence_and_allows_approval(
    approval_client, monkeypatch, tmp_path, stubbed_render,
):
    """The issue #63 end-to-end proof: a reviewer corrects a fixture's params,
    which clears the approval evidence, and revalidation rebuilds it in place
    so the corrected draft can be approved -- without regenerating and without
    losing the correction."""
    monkeypatch.setenv("META_REQUIRED_FIXTURE_COUNT", "1")
    get_settings.cache_clear()
    draft_id = _seed_revalidatable_draft(
        draft_id="draft-reval-ok", fingerprint_key="k-reval-ok",
        observation_id="obs-reval-ok",
        # Both 5 (as generated) and 7 (the reviewer's correction) are grounded
        # in this excerpt, so the edit is a legitimate correction rather than an
        # ungrounded value the grounding check must reject.
        source_excerpt="there are 5 apples and 7 pears",
        artifact_root=get_settings().meta_artifact_root,
    )

    before = approval_client.get(f"/meta/drafts/{draft_id}").json()
    fixture = next(f for f in before["fixtures"] if f["observation_id"] == "obs-reval-ok")
    assert fixture["params"] == {"n": 5}

    edit = approval_client.post(
        f"/meta/drafts/{draft_id}/fixtures/{fixture['id']}",
        json={"params": {"n": 7}, "expected_result": {"answer": "7"}},
    )
    assert edit.status_code == 200, edit.json()
    assert edit.json()["structural_check_passed"] is None
    cleared = approval_client.get(f"/meta/drafts/{draft_id}").json()
    assert cleared["validation_report"] is None
    assert cleared["quality_report"] is None
    assert cleared["preview_url"] is None

    revalidated = approval_client.post(f"/meta/drafts/{draft_id}/revalidate")
    assert revalidated.status_code == 200, revalidated.json()
    body = revalidated.json()
    assert body["validation_report"]["passed"] is True
    assert body["quality_report"]["passed"] is True
    assert body["preview_url"] is not None
    assert body["preview_url"] != before["preview_url"]
    # The reports must describe the artifact now on the draft, or approval
    # precondition 4 would 422 on a stale-hash mismatch.
    assert body["validation_report"]["artifact_hash"] == body["artifact_hash"]
    assert body["quality_report"]["artifact_hash"] == body["artifact_hash"]
    # The reviewer's correction, and the answer they confirmed for it, survive.
    revalidated_fixture = next(f for f in body["fixtures"] if f["id"] == fixture["id"])
    assert revalidated_fixture["params"] == {"n": 7}
    assert revalidated_fixture["expected_result"] == {"answer": "7"}
    assert revalidated_fixture["structural_check_passed"] is True

    approve = approval_client.post(
        f"/meta/drafts/{draft_id}/approve",
        json={"template_name": "reval_apples", "math_semantics_confirmed": True},
    )
    assert approve.status_code == 200, approve.json()
    assert approve.json()["status"] == "enabled"


def test_revalidate_reports_the_failure_and_leaves_evidence_cleared(
    client, monkeypatch, tmp_path, stubbed_render,
):
    """A params edit that genuinely breaks a check must not become approvable.
    The route reports why, and no failing validation report is persisted -- the
    v3 invariant is that only a passing report can exist in the database."""
    monkeypatch.setenv("META_REQUIRED_FIXTURE_COUNT", "1")
    get_settings.cache_clear()
    draft_id = _seed_revalidatable_draft(
        draft_id="draft-reval-bad", fingerprint_key="k-reval-bad",
        observation_id="obs-reval-bad", source_excerpt="there are 5 apples",
        artifact_root=get_settings().meta_artifact_root,
    )
    fixture = client.get(f"/meta/drafts/{draft_id}").json()["fixtures"][0]

    # 9 is a valid param and evaluates fine, so `update_fixture` accepts it --
    # but it appears nowhere in the source excerpt, so the grounding check in
    # `validate_fixture` must fail on revalidation.
    edit = client.post(
        f"/meta/drafts/{draft_id}/fixtures/{fixture['id']}",
        json={"params": {"n": 9}, "expected_result": {"answer": "9"}},
    )
    assert edit.status_code == 200, edit.json()

    resp = client.post(f"/meta/drafts/{draft_id}/revalidate")
    assert resp.status_code == 422
    assert "not grounded in source" in resp.json()["detail"]

    after = client.get(f"/meta/drafts/{draft_id}")
    # Still pending_review (a non-pending draft would 404 here), still
    # unapprovable, and no report was written.
    assert after.status_code == 200
    assert after.json()["validation_report"] is None
    assert after.json()["quality_report"] is None
    assert after.json()["preview_url"] is None


def test_revalidate_aborts_when_the_draft_is_decided_mid_flight(
    client, monkeypatch, tmp_path, stubbed_render,
):
    """Validation runs a preview render outside any database session, so a
    concurrent approve or reject can land while it is in flight. The write must
    re-check the status and abort rather than writing evidence onto a draft
    that has already been decided."""
    monkeypatch.setenv("META_REQUIRED_FIXTURE_COUNT", "1")
    get_settings.cache_clear()
    draft_id = _seed_revalidatable_draft(
        draft_id="draft-reval-race", fingerprint_key="k-reval-race",
        observation_id="obs-reval-race", source_excerpt="there are 5 apples",
        artifact_root=get_settings().meta_artifact_root,
    )
    with db.meta_session() as session:
        session.get(models.TemplateDraft, draft_id).validation_report_json = None

    real_validate = validate_candidate

    def _validate_then_approve_concurrently(*args, **kwargs):
        candidate = real_validate(*args, **kwargs)
        with db.meta_session() as session:
            session.get(models.TemplateDraft, draft_id).status = models.DRAFT_APPROVED
        return candidate

    monkeypatch.setattr(
        "app.meta.revalidation.validate_candidate", _validate_then_approve_concurrently
    )

    resp = client.post(f"/meta/drafts/{draft_id}/revalidate")
    assert resp.status_code == 409
    with db.meta_session() as session:
        draft = session.get(models.TemplateDraft, draft_id)
        assert draft.status == models.DRAFT_APPROVED
        assert draft.validation_report_json is None


def test_revalidate_unknown_draft_returns_404(client):
    resp = client.post("/meta/drafts/does-not-exist/revalidate")
    assert resp.status_code == 404


def test_revalidate_non_pending_draft_returns_409(client):
    draft_id = _seed_approvable_draft(
        draft_id="draft-reval-approved", fingerprint_key="k-reval-approved",
        status=models.DRAFT_APPROVED,
    )
    resp = client.post(f"/meta/drafts/{draft_id}/revalidate")
    assert resp.status_code == 409


def test_review_router_absent_when_meta_templates_disabled(monkeypatch, tmp_path):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.delenv("META_TEMPLATES_ENABLED", raising=False)
    get_settings.cache_clear()
    from app.main import create_app
    disabled_client = TestClient(create_app())
    resp = disabled_client.get("/meta/drafts")
    assert resp.status_code == 404


@pytest.mark.parametrize("method,path", [
    ("get", "/meta/drafts"),
    ("get", "/meta/drafts/any-id"),
    ("get", "/meta/preview/any-hash"),
    ("post", "/meta/drafts/any-id/fixtures/any-fixture"),
    ("post", "/meta/drafts/any-id/reject"),
    ("post", "/meta/drafts/any-id/revalidate"),
    ("post", "/meta/drafts/any-id/approve"),
])
def test_meta_routes_require_a_bearer_token(method, path, client_without_token):
    kwargs = {"json": {}} if method == "post" else {}
    resp = getattr(client_without_token, method)(path, **kwargs)
    assert resp.status_code == 401


def test_approve_fails_closed_when_token_not_configured(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_APPROVAL_ENABLED", "1")
    monkeypatch.delenv("META_REVIEWER_TOKEN", raising=False)
    get_settings.cache_clear()
    from app.main import create_app
    unconfigured_client = TestClient(create_app())

    resp = unconfigured_client.post(
        "/meta/drafts/any-id/approve",
        json={"template_name": "apples", "math_semantics_confirmed": True},
        headers={"Authorization": "Bearer anything"},
    )

    assert resp.status_code == 401
    assert "not configured" in resp.json()["detail"]
    get_settings.cache_clear()
    get_settings.cache_clear()


# ------------------------------------------------ sharing a teacher's template


def _enabled_version(*, version_id, key, name, owner, draft_id=None):
    with db.meta_session() as session:
        session.add(models.TemplateVersion(
            id=version_id, fingerprint_key=key, template_name=name, draft_id=draft_id,
            artifact_hash="sha256:x", status=models.TEMPLATE_VERSION_ENABLED,
            owner_session_id=owner, created_at=_now(), updated_at=_now(),
        ))


def _fill_expected_results(draft_id):
    """Give every positive fixture the derived answer publication requires."""
    from app.meta.fixture_answers import record_computed_answers

    with db.meta_session() as session:
        record_computed_answers(session, session.get(models.TemplateDraft, draft_id))


def _make_shareable(draft_id):
    """Bring a draft up to the full shared-publication evidence bar.

    Sharing demands meta_required_fixture_count verified fixtures against
    distinct real observations, and the seeding helper provides one. This adds
    the rest rather than lowering the bar, so the promote tests exercise the
    floor that actually ships.
    """
    with db.meta_session() as session:
        for index in range(1, get_settings().meta_required_fixture_count):
            observation_id = f"obs-{draft_id}-extra-{index}"
            session.add(models.FallbackObservation(
                id=observation_id, candidate_id=f"cand-{observation_id}",
                source_excerpt="there are 5 apples", grade_level=2,
                observation_kind="unsupported_shape", excluded=False, created_at=_now(),
            ))
            session.flush()
            session.add(models.TemplateDraftFixture(
                id=f"{draft_id}-extra-{index}", draft_id=draft_id,
                observation_id=observation_id, kind="positive", expected_outcome="accept",
                generation_method="proposed", params_json=json.dumps({"n": 5}),
                structural_check_passed=True, created_at=_now(),
            ))
    _fill_expected_results(draft_id)


def test_versions_listing_names_who_owns_each_one(approval_client):
    draft = _seed_pending_review_draft(observation_id="obs-list")
    _enabled_version(
        version_id="tv-own", key="k-own", name="theirs", owner="session-a", draft_id=draft.id
    )
    _enabled_version(version_id="tv-shared", key="k-shared", name="everyones", owner=None)

    rows = approval_client.get("/meta/versions").json()

    by_name = {row["template_name"]: row for row in rows}
    assert by_name["theirs"]["owner_session_id"] == "session-a"
    assert by_name["everyones"]["owner_session_id"] is None


def test_promoting_a_version_shares_it_with_everyone(approval_client):
    draft = _seed_pending_review_draft(observation_id="obs-promote")
    _make_shareable(draft.id)
    _enabled_version(
        version_id="tv-own", key="k-own", name="theirs", owner="session-a", draft_id=draft.id
    )

    resp = approval_client.post("/meta/versions/tv-own/promote")

    assert resp.status_code == 200
    with db.meta_session() as session:
        version = session.get(models.TemplateVersion, "tv-own")
        assert version.owner_session_id is None
        assert version.status == models.TEMPLATE_VERSION_ENABLED


def test_promoting_refuses_a_template_with_too_little_evidence(approval_client):
    """Private approval relaxes the fixture floor; sharing must not inherit that."""
    draft = _seed_pending_review_draft(observation_id="obs-thin")
    _enabled_version(
        version_id="tv-thin", key="k-thin", name="thin", owner="session-a", draft_id=draft.id
    )

    resp = approval_client.post("/meta/versions/tv-thin/promote")

    assert resp.status_code == 422
    with db.meta_session() as session:
        assert session.get(models.TemplateVersion, "tv-thin").owner_session_id == "session-a"


def test_promoting_refuses_a_name_another_shared_template_already_holds(approval_client):
    draft = _seed_pending_review_draft(observation_id="obs-clash")
    _make_shareable(draft.id)
    _enabled_version(
        version_id="tv-own", key="k-own", name="clash", owner="session-a", draft_id=draft.id
    )
    _enabled_version(version_id="tv-shared", key="k-other", name="clash", owner=None)

    resp = approval_client.post("/meta/versions/tv-own/promote")

    assert resp.status_code == 409
    with db.meta_session() as session:
        assert session.get(models.TemplateVersion, "tv-own").owner_session_id == "session-a"


def test_promoting_an_already_shared_version_is_a_conflict(approval_client):
    _enabled_version(version_id="tv-shared", key="k-shared", name="already", owner=None)

    assert approval_client.post("/meta/versions/tv-shared/promote").status_code == 409


def test_promoting_an_unknown_version_is_not_found(approval_client):
    resp = approval_client.post("/meta/versions/nope/promote")

    assert resp.status_code == 404
    # Asserting the handler's own message, not just the status: an absent route
    # would 404 too, and this test would then pass without the route existing.
    assert "nope" in resp.json()["detail"]


def test_promoting_needs_the_reviewer_token(client_without_token):
    _enabled_version(version_id="tv-own", key="k-own", name="theirs", owner="session-a")

    assert client_without_token.post("/meta/versions/tv-own/promote").status_code == 401
