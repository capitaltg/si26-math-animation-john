import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.meta import db, models
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.fingerprint import Fingerprint
from app.meta.generation_pipeline import run_generation_job
from app.meta.ingest import record_unsupported_shape
from app.models.scene import TemplateName
from app.pipeline.classification import ClassificationResult, TemplateOption


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    monkeypatch.setenv("FINGERPRINT_OBSERVATION_THRESHOLD", "1")
    get_settings.cache_clear()
    from app.main import create_app

    yield TestClient(create_app())
    get_settings.cache_clear()


def _fingerprint():
    return Fingerprint(
        fingerprint_version=1,
        operation_family="compose",
        representation_family="bar",
        number_domain="fraction",
        operand_arity=2,
        step_count=1,
        grade_band="3-5",
    )


def _proposal_dict(observation_id):
    proposal = DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[
                IntegerFieldSpec(
                    name="n", label="N", description="", minimum=1, maximum=10
                )
            ],
        ),
        guard_document=GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=FieldRefNode(field="n"))],
        ),
        answer_expression=FieldRefNode(field="n"),
        animation_document=AnimationDocument(root={"kind": "label", "text": "n"}),
        classifier_bullet="use for fraction-of-whole bars",
        fixtures=[
            ProposedFixture(
                kind="positive",
                expected_outcome="accept",
                observation_id=observation_id,
                params={"n": 5},
            ),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"n": -1}),
        ],
    )
    return json.loads(proposal.model_dump_json())


@patch("app.meta.draft_generation.call_with_tool")
@patch("app.meta.fingerprint.call_with_tool")
def test_full_flow_from_observation_to_reject_and_refine(
    mock_tag_call, mock_draft_call, client
):
    fingerprint = _fingerprint()
    mock_tag_call.return_value = ("fingerprint", fingerprint.model_dump())
    classification = ClassificationResult(
        grade_level=4,
        ambiguous=False,
        problem_kind="solvable",
        options=[
            TemplateOption(
                template=TemplateName.TEXT_CARD,
                rationale="no structural match",
            )
        ],
    )
    record_unsupported_shape(
        candidate_id="cand-1",
        source_excerpt="there are 5 apples in the bar",
        classification=classification,
        picked_template=TemplateName.TEXT_CARD,
        scene_status="pending_review",
    )

    with db.meta_session() as session:
        job = session.query(models.GenerationJob).one()
        assert job.status == models.JOB_QUEUED
        observation_id = session.query(models.FallbackObservation).one().id

    mock_draft_call.return_value = ("propose_template_draft", _proposal_dict(observation_id))
    draft = run_generation_job(owner="worker-1")
    assert draft.status == models.DRAFT_PENDING_REVIEW

    response = client.get("/meta/drafts", params={"status": "pending_review"})
    assert [draft_row["id"] for draft_row in response.json()] == [draft.id]

    mock_draft_call.return_value = ("propose_template_draft", _proposal_dict(observation_id))
    reject_response = client.post(
        f"/meta/drafts/{draft.id}/reject", json={"feedback": "tighten it up"}
    )
    assert reject_response.status_code == 200
    body = reject_response.json()
    assert body["needs_manual_authoring"] is False
    assert body["new_draft"]["revision"] == 2

    approve_response = client.post(
        f"/meta/drafts/{body['new_draft']['id']}/approve",
        json={"template_name": "fraction_bars", "math_semantics_confirmed": True},
    )
    assert approve_response.status_code == 409
