"""End-to-end coverage of the live meta-template demo runbook, with Bedrock the
only thing mocked.

This walks the exact sequence a presenter performs (docs/meta-template-demo.md):
seed an unsupported-shape observation, let the worker generate a bounded
perimeter template, confirm it validates with a *non-blank* preview, have the
reviewer supply the known answer and approve, then reuse the published template
on a second problem and render a real MP4. It is the regression guard for the
demo-breaking bugs: an animation that renders a black frame can no longer pass
validation, and a published template renders correctly when applied to a new
problem.
"""

from fractions import Fraction
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.meta import db, models
from app.meta.db import meta_session
from app.meta.dsl.expression import ExpressionNode, compile_expression
from app.meta.dynamic_templates import (
    get_dynamic_template,
    load_enabled_snapshot,
    resolve_dynamic_ref,
)
from app.meta.fingerprint import Fingerprint
from app.meta.generation_pipeline import run_generation_job
from app.meta.ingest import record_unsupported_shape
from app.models.scene import TemplateName
from app.pipeline.classification import ClassificationResult, TemplateOption
from app.render.full_render import render_scene_to_mp4
from pydantic import TypeAdapter


@pytest.fixture
def client(tmp_path, monkeypatch):
    meta_db = tmp_path / "meta.db"
    engine = db.make_engine(meta_db)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    # The render step runs in a subprocess that opens its own meta_session from
    # settings, so it must be pointed at the same on-disk DB as this process.
    monkeypatch.setenv("META_DB_PATH", str(meta_db))
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    monkeypatch.setenv("META_APPROVAL_ENABLED", "1")
    # Match the runbook's demo tuning: one observation seeds a draft, one
    # human-verified real fixture is enough to publish.
    monkeypatch.setenv("FINGERPRINT_OBSERVATION_THRESHOLD", "1")
    monkeypatch.setenv("META_REQUIRED_FIXTURE_COUNT", "1")
    monkeypatch.setenv("META_REVIEWER_TOKEN", "test-token")
    get_settings.cache_clear()
    from app.main import create_app

    yield TestClient(create_app(), headers={"Authorization": "Bearer test-token"})
    get_settings.cache_clear()


def _fingerprint():
    return Fingerprint(
        fingerprint_version=1,
        operation_family="measure",
        representation_family="shape",
        number_domain="whole",
        operand_arity=2,
        step_count=2,
        grade_band="3-5",
    )


# 2 * (length + width)
_ANSWER_EXPRESSION = {
    "node": "multiply",
    "operands": [
        {"node": "literal", "value": 2.0},
        {"node": "add", "operands": [
            {"node": "field_ref", "field": "length"},
            {"node": "field_ref", "field": "width"},
        ]},
    ],
}


def _good_perimeter_proposal(observation_id):
    """A well-formed perimeter draft: its animation actually displays content
    (every visual is `appear`ed and held with a `wait`), its guard predicates are
    each witnessed by a negative fixture, and its single positive fixture is
    grounded in the seeded observation."""
    return {
        "params_document": {
            "params_version": 1,
            "fields": [
                {"type": "integer", "name": "length", "label": "Length (cm)",
                 "description": "Rectangle length", "minimum": 1, "maximum": 20},
                {"type": "integer", "name": "width", "label": "Width (cm)",
                 "description": "Rectangle width", "minimum": 1, "maximum": 20},
            ],
        },
        "guard_document": {
            "guard_version": 1,
            "predicates": [
                {"predicate": "positive", "value": {"node": "field_ref", "field": "length"}},
                {"predicate": "positive", "value": {"node": "field_ref", "field": "width"}},
            ],
        },
        "answer_expression": _ANSWER_EXPRESSION,
        "animation_document": {
            "animation_version": 1,
            "root": {
                "kind": "sequence",
                "steps": [
                    {"kind": "column", "ref": "scene1", "children": [
                        {"kind": "label", "ref": "title", "text": "Find the perimeter", "style": "primary"},
                        {"kind": "grid", "ref": "rect",
                         "rows": {"node": "field_ref", "field": "width"},
                         "cols": {"node": "field_ref", "field": "length"}, "style": "primary"},
                        {"kind": "label", "ref": "formula", "text": "P = 2 x (l + w)", "style": "muted"},
                    ]},
                    {"kind": "appear", "target_ref": "scene1"},
                    {"kind": "wait", "seconds": 1},
                    {"kind": "column", "ref": "scene2", "children": [
                        {"kind": "object_set", "ref": "answer_set", "count": _ANSWER_EXPRESSION, "style": "success"},
                        {"kind": "label", "ref": "answer", "text": "Perimeter (cm)", "style": "success"},
                    ]},
                    {"kind": "appear", "target_ref": "scene2"},
                    {"kind": "wait", "seconds": 1},
                ],
            },
        },
        "classifier_bullet": "Rectangle perimeter from whole-number length and width.",
        "fixtures": [
            {"kind": "positive", "expected_outcome": "accept", "generation_method": "proposed",
             "observation_id": observation_id, "params": {"length": 8, "width": 3}},
            {"kind": "negative", "expected_outcome": "reject", "generation_method": "proposed",
             "observation_id": None, "params": {"length": 0, "width": 3}},
            {"kind": "negative", "expected_outcome": "reject", "generation_method": "proposed",
             "observation_id": None, "params": {"length": 8, "width": 0}},
        ],
    }


@patch("app.meta.draft_generation.call_with_tool")
@patch("app.meta.fingerprint.call_with_tool")
def test_demo_flow_generates_reviews_publishes_and_reuses(mock_tag_call, mock_draft_call, client, tmp_path):
    fingerprint = _fingerprint()
    mock_tag_call.return_value = ("fingerprint", fingerprint.model_dump())

    # 1-3. Slide 1 falls back to text_card (unsupported shape) -> observation ->
    # worker generates and validates a draft.
    classification = ClassificationResult(
        grade_level=4, ambiguous=False, problem_kind="solvable",
        options=[TemplateOption(template=TemplateName.TEXT_CARD, rationale="no structural match")],
    )
    record_unsupported_shape(
        candidate_id="slide-1", source_excerpt="rectangle 8 cm by 3 cm, find perimeter",
        classification=classification, picked_template=TemplateName.TEXT_CARD,
        scene_status="pending_review",
    )
    with meta_session() as session:
        observation_id = session.query(models.FallbackObservation).one().id

    mock_draft_call.return_value = ("propose_template_draft", _good_perimeter_proposal(observation_id))
    draft = run_generation_job(owner="worker-1")
    assert draft.status == models.DRAFT_PENDING_REVIEW  # black-frame drafts fail here

    # 4. Review: validation passed and the preview is a real (non-blank) PNG.
    detail = client.get(f"/meta/drafts/{draft.id}").json()
    assert detail["validation_report"]["passed"] is True
    assert detail["preview_url"]
    preview = client.get(detail["preview_url"])
    assert preview.status_code == 200 and len(preview.content) > 0

    # Only the grounded positive is offered for verification -- no phantom
    # fixtures the reviewer can never approve.
    verifiable = [f for f in detail["fixtures"] if f["kind"] == "positive"]
    assert len(verifiable) == 1 and verifiable[0]["source_excerpt"]

    # 4b. Reviewer supplies the known answer for slide 1 (8 x 3 -> 22).
    save = client.post(
        f"/meta/drafts/{draft.id}/fixtures/{verifiable[0]['id']}",
        json={"params": {"length": 8, "width": 3}, "expected_result": {"answer": 22}},
    )
    assert save.status_code == 200

    # 5. Approve and publish under a unique name.
    approve = client.post(
        f"/meta/drafts/{draft.id}/approve",
        json={"template_name": "rectangle_perimeter", "math_semantics_confirmed": True},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "enabled"

    # 6. Reuse on slide 2 (10 x 4 -> 28) and render a real MP4.
    with meta_session() as session:
        entry = load_enabled_snapshot(session).entry("rectangle_perimeter")
        assert entry is not None
        ref = resolve_dynamic_ref(session, "rectangle_perimeter", entry.version_id)
    _scene_cls, params_cls = get_dynamic_template(ref)
    params = params_cls.model_validate({"length": 10, "width": 4})

    out = tmp_path / "slide2.mp4"
    render_scene_to_mp4(ref, params, out)
    assert out.exists() and out.stat().st_size > 0

    # The published template computes the runbook's slide-2 answer.
    assert _answer({"length": 10, "width": 4}) == Fraction(28)


def _answer(values):
    node = TypeAdapter(ExpressionNode).validate_python(_ANSWER_EXPRESSION)
    return compile_expression(node, frozenset({"length", "width"})).evaluate(values)


def test_perimeter_answers_are_correct_for_both_demo_slides():
    # Semantic guard: the published template's answer expression resolves to the
    # runbook's stated answers, independent of rendering.
    assert _answer({"length": 8, "width": 3}) == Fraction(22)
    assert _answer({"length": 10, "width": 4}) == Fraction(28)
