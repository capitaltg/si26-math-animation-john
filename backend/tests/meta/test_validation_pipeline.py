from datetime import datetime, timezone
from types import SimpleNamespace

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
    """Stub out BOTH halves of the rendered-quality step, not just the renderer.

    `render_preview_and_probe` is replaced to avoid the expensive manim probe
    subprocess, and it returns the sentinel manifest `{"probe": "complete"}`.
    `validate_rendered_quality` must therefore be stubbed too: that sentinel is
    not real probe output and would fail `check_manifest_contract` outright, so
    the second stub is load-bearing rather than belt-and-braces.

    Consequence: tests using this fixture do NOT cover the rendered-quality
    gate -- they cover everything around it (compilation, fixture validation,
    report assembly, artifact hashing). The gate's own coverage is
    `tests/meta/v3/test_render_probe.py`, plus `test_demo_end_to_end.py` and
    `test_v3_demo_quality.py`, which run a real probe subprocess.
    """
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
    # Defect A: approval precondition 4 (app/meta/approval.py) compares
    # validation_report["artifact_hash"] to draft.artifact_hash, which is
    # populated from quality_report["artifact_hash"] (drafts.py:65). If the
    # production builder ever stops writing this key -- or writes a second,
    # independently-computed hash -- every real draft becomes unapprovable
    # even though both reports passed. This must be the *same* hash, not
    # merely present.
    assert candidate.validation_report["artifact_hash"] == candidate.quality_report["artifact_hash"]


def test_build_validation_report_embeds_the_supplied_artifact_hash():
    # Direct unit test of the production report builder (not a hand-built
    # report literal): if `artifact_hash` were ever dropped from the return
    # value, approval precondition 4 would 422 every real draft with
    # "Validation report is stale: artifact hash mismatch".
    from app.meta.validation_pipeline import build_validation_report
    from app.meta.validation import FixtureCheckResult

    compiled = SimpleNamespace(known_fields=frozenset({"length", "width"}))
    fixture_results = [
        FixtureCheckResult("fixture-0", True, "accepted"),
        FixtureCheckResult("fixture-1", True, "rejected", frozenset({0})),
    ]

    report = build_validation_report(
        compiled=compiled,
        fixture_results=fixture_results,
        preview_artifact_hash="sha256:preview",
        artifact_hash="sha256:candidate",
    )

    assert report["artifact_hash"] == "sha256:candidate"


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
