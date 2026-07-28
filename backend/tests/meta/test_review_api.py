import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

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
def client(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
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
        animation_document=AnimationDocument(root={"kind": "label", "text": "n"}),
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


def test_list_drafts_filters_by_status(client):
    draft = _seed_pending_review_draft()
    resp = client.get("/meta/drafts", params={"status": "pending_review"})
    assert resp.status_code == 200
    assert [d["id"] for d in resp.json()] == [draft.id]


def test_get_draft_detail_includes_fixtures_and_preview_url(client):
    draft = _seed_pending_review_draft()
    resp = client.get(f"/meta/drafts/{draft.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["classifier_bullet"] == "use for X"
    assert len(body["fixtures"]) == 2
    assert body["preview_url"] == f"/meta/preview/{draft.preview_artifact_hash}"


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


def test_approve_draft_is_disabled(client):
    draft = _seed_pending_review_draft()
    resp = client.post(f"/meta/drafts/{draft.id}/approve")
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
    get_settings.cache_clear()
