import json
from datetime import datetime, timezone
from unittest.mock import patch

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
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.drafts import create_generated_draft
from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.fingerprint import Fingerprint
from app.meta.generation_pipeline import run_generation_job
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
    import json
    return json.loads(proposal.model_dump_json())


def _sample_fingerprint_json():
    # The brief's test sketch used the literal placeholder "{}" here, but
    # run_generation_job parses job.fingerprint_json into a real Fingerprint
    # (all 7 fields required, extra="forbid") before the propose step even
    # runs, so "{}" fails ValidationError unconditionally -- independent of
    # what's being mocked. Use a valid Fingerprint payload instead (same fix
    # applied in tests/meta/test_generation_pipeline.py).
    return Fingerprint(
        fingerprint_version=1,
        operation_family="compare",
        representation_family="grid",
        number_domain="whole",
        operand_arity=1,
        step_count=1,
        grade_band="K-2",
    ).model_dump_json()


def _seed_pending_review_draft():
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
    ``tests/meta/test_approval.py``'s ``_seed_draft``)."""
    with db.meta_session() as session:
        job = models.GenerationJob(
            id=f"job-{draft_id}", fingerprint_key=fingerprint_key, fingerprint_version=1,
            fingerprint_json="{}", trigger_observation_ids="[]", status=models.JOB_SUCCEEDED,
            created_at=_now(), updated_at=_now(),
        )
        session.add(job)

        fixtures = []
        for i in range(positive_count):
            obs_id = f"obs-{draft_id}-{i}"
            session.add(models.FallbackObservation(
                id=obs_id, candidate_id=f"cand-{draft_id}-{i}",
                source_excerpt="there are 5 apples", grade_level=2,
                observation_kind="unsupported_shape", excluded=False, created_at=_now(),
            ))
            fixtures.append(ProposedFixture(
                kind="positive", expected_outcome="accept", observation_id=obs_id, params={"n": 5},
            ))
        fixtures.append(ProposedFixture(kind="negative", expected_outcome="reject", params={"n": -1}))
        session.flush()

        proposal = DraftProposal(
            params_document=ParamsDocument(
                params_version=1,
                fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
            ),
            guard_document=GuardDocument(
                guard_version=1, predicates=[PositivePredicate(value=FieldRefNode(field="n"))],
            ),
            answer_expression=FieldRefNode(field="n"),
            animation_document=AnimationDocument(root={"kind": "sequence", "steps": [
            {"kind": "label", "ref": "n_label", "text": "n"},
            {"kind": "appear", "target_ref": "n_label"},
            {"kind": "wait", "seconds": 1},
        ]}),
            classifier_bullet="use for X",
            fixtures=fixtures,
        )
        draft = create_generated_draft(session, new_id=draft_id, job=job, proposal=proposal, now=_now())

        for fx in session.query(models.TemplateDraftFixture).filter_by(draft_id=draft.id).all():
            if fx.kind == "positive":
                if set_expected_result:
                    fx.expected_result_json = json.dumps({"answer": "5"})
                fx.structural_check_passed = True
            else:
                fx.structural_check_passed = True

        draft.status = status
        draft.preview_artifact_hash = "preview-hash"
        cov = coverage if coverage is not None else [0]
        report = {
            "passed": passed,
            "compile_error": None,
            "fixture_results": [],
            "preview_ok": passed,
            "preview_error": None,
            "artifact_hash": report_hash if report_hash is not None else draft.artifact_hash,
            "compiler_version": DSL_COMPILER_VERSION,
            "renderer_version": DYNAMIC_RENDERER_VERSION,
            "negative_predicate_coverage": cov,
        }
        draft.validation_report_json = json.dumps(report)
        session.flush()
        return draft.id


def test_list_drafts_filters_by_status(client):
    draft = _seed_pending_review_draft()
    resp = client.get("/meta/drafts", params={"status": "pending_review"})
    assert resp.status_code == 200
    assert [d["id"] for d in resp.json()] == [draft.id]


def test_get_draft_detail_includes_fixtures_and_preview_url(client, monkeypatch):
    monkeypatch.setenv("META_REQUIRED_FIXTURE_COUNT", "1")
    get_settings.cache_clear()
    draft = _seed_pending_review_draft()
    resp = client.get(f"/meta/drafts/{draft.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["classifier_bullet"] == "use for X"
    assert len(body["fixtures"]) == 2
    assert body["preview_url"] == f"/meta/preview/{draft.preview_artifact_hash}"
    assert body["required_fixture_count"] == 1


def test_get_preview_serves_stored_artifact(client):
    draft = _seed_pending_review_draft()
    resp = client.get(f"/meta/preview/{draft.preview_artifact_hash}")
    assert resp.status_code == 200
    assert len(resp.content) > 0


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


def test_update_fixture_revalidates_and_refreshes_preview(client):
    draft = _seed_pending_review_draft()
    fixture_id = client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]["id"]
    with db.meta_session() as session:
        obs = session.get(models.FallbackObservation, "obs-1")
        obs.source_excerpt = "there are 5 or 6 apples"

    with patch("app.meta.validation_pipeline.render_and_store_preview") as mock_render:
        mock_render.return_value = "hash-after-edit"
        response = client.post(
            f"/meta/drafts/{draft.id}/fixtures/{fixture_id}",
            json={"params": {"n": 6}, "expected_result": {"answer": "6"}},
        )

    assert response.status_code == 200
    assert mock_render.called
    detail = client.get(f"/meta/drafts/{draft.id}").json()
    assert detail["status"] == "pending_review"
    assert detail["preview_url"] == "/meta/preview/hash-after-edit"
    assert detail["validation_report"]["artifact_hash"] == draft.artifact_hash
    assert detail["validation_report"]["passed"] is True


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
    fixture = client.get(f"/meta/drafts/{draft.id}").json()["fixtures"][0]
    assert fixture["params"] == {"n": 5}
    assert fixture["expected_result"] is None
    with db.meta_session() as session:
        stored = session.get(models.TemplateDraft, draft.id)
        assert stored.status == models.DRAFT_APPROVED


@patch("app.meta.draft_generation.call_with_tool")
def test_reject_draft_creates_new_revision(mock_call, client):
    draft = _seed_pending_review_draft()
    mock_call.return_value = ("propose_template_draft", _proposal_dict())
    resp = client.post(f"/meta/drafts/{draft.id}/reject", json={"feedback": "too loose"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_manual_authoring"] is False
    assert body["new_draft"]["revision"] == 2


@patch("app.meta.draft_generation.call_with_tool")
def test_reject_draft_restores_pending_review_when_refinement_fails(mock_call, client):
    draft = _seed_pending_review_draft()
    mock_call.side_effect = RuntimeError("bedrock unavailable")

    resp = client.post(f"/meta/drafts/{draft.id}/reject", json={"feedback": "too loose"})

    assert resp.status_code == 409
    assert "retried" in resp.json()["detail"]
    with db.meta_session() as session:
        original = session.get(models.TemplateDraft, draft.id)
        assert original.status == models.DRAFT_PENDING_REVIEW
        assert original.reviewer_feedback == "too loose"
        assert session.query(models.TemplateReview).filter_by(draft_id=draft.id).count() == 1


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
    with patch("app.meta.review_api.approve_draft_service", side_effect=exc_cls("boom")):
        resp = approval_client.post(
            "/meta/drafts/any-id/approve",
            json={"template_name": "apples", "math_semantics_confirmed": True},
        )
    assert resp.status_code == expected_status
    assert resp.json()["detail"] == "boom"


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
