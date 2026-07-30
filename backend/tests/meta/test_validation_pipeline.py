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
from app.meta.v3.errors import V3ValidationError
from app.meta.v3.quality import QualityCheck, QualityReport


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


def _plan():
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement",
            "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"},
            "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal_rectangle", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}],
             "intent": "show the measured rectangle"},
            {"id": "trace_boundary", "kind": "derive", "targets": [{"visual_ref": "rectangle"}],
             "intent": "trace every edge of the boundary"},
            {"id": "show_perimeter", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}],
             "intent": "state the perimeter"},
        ],
        "variation_seed": "validation-pipeline",
    })


def _proposal(observation_id="obs-1"):
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
            predicates=[
                PositivePredicate(value=FieldRefNode(field="length")),
                PositivePredicate(value=FieldRefNode(field="width")),
            ],
        ),
        answer_expression=AddNode(operands=[
            MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="length")]),
            MultiplyNode(operands=[FieldRefNode(field="width"), FieldRefNode(field="width")]),
        ]),
        teaching_plan_document=_plan(),
        classifier_bullet="Use for rectangle perimeter lessons.",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", observation_id=observation_id, params={"length": 8, "width": 3}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"length": -1, "width": 3}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"length": 8, "width": -1}),
        ],
    )


def _observation():
    return models.FallbackObservation(
        id="obs-1",
        candidate_id="candidate-1",
        source_excerpt="The rectangle is 8 cm long and 3 cm wide.",
        grade_level=6,
        observation_kind="unsupported_shape",
        excluded=False,
        created_at=_now(),
    )


@pytest.fixture
def passing_render_probe(monkeypatch):
    monkeypatch.setattr(
        "app.meta.validation_pipeline.render_preview_and_probe",
        lambda *args, **kwargs: ("sha256:preview", {"probe": "complete"}),
    )
    monkeypatch.setattr(
        "app.meta.validation_pipeline.validate_rendered_quality",
        lambda probe: QualityReport(True, [
            QualityCheck("render_probe_complete", True, "probe", "passed"),
        ]),
    )


def test_validate_candidate_builds_a_passing_in_memory_v3_candidate(tmp_path, passing_render_probe):
    from app.meta.validation_pipeline import validate_candidate

    observation = _observation()
    candidate = validate_candidate(
        _proposal(observation.id),
        observations_by_id={observation.id: observation},
        artifact_root=tmp_path / "artifacts",
        compile_context=CompileContext(concept_family="measure_shape", grade_band="6-8"),
    )

    assert candidate.preview_artifact_hash == "sha256:preview"
    assert candidate.validation_report["passed"] is True
    assert candidate.validation_report["negative_predicate_coverage"] == [0, 1]
    assert candidate.validation_report["preview_ok"] is True
    assert candidate.quality_report["passed"] is True
    assert candidate.quality_report["artifact_hash"].startswith("sha256:")
    assert len(candidate.fixture_results) == 3


def test_invalid_candidate_creates_no_draft(session, tmp_path, passing_render_probe):
    from app.meta.validation_pipeline import validate_candidate

    proposal = _proposal(None).model_copy(
        update={"answer_expression": FieldRefNode(field="unknown_field")}
    )

    with pytest.raises(V3ValidationError):
        validate_candidate(
            proposal,
            observations_by_id={},
            artifact_root=tmp_path / "artifacts",
            compile_context=CompileContext(concept_family="measure_shape", grade_band="6-8"),
        )

    assert session.query(models.TemplateDraft).count() == 0
