"""Recording the answers a draft's own expression already determines.

``persist_candidate_fixtures`` leaves ``expected_result_json`` NULL, and approval
precondition 8 requires it to be set. The admin panel fills it in one fixture at
a time -- but ``update_fixture`` recomputes the answer and rejects anything that
differs from it, so that step cannot carry human knowledge, only human typing.
This module derives the same values directly.
"""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.meta import db, models
from app.meta.dsl.expression import AddNode, FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: eng)
    db.create_all(eng)
    return eng


def _now():
    return datetime(2026, 8, 4, tzinfo=timezone.utc)


def _plan():
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Add two whole numbers.",
        "primary_visual": {"kind": "label", "ref": "total", "text": "value"},
        "strategy": "group_reveal",
        "beats": [
            {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "total"}],
             "intent": "show the parts"},
            {"id": "focus", "kind": "focus", "targets": [{"visual_ref": "total"}],
             "intent": "focus on the total"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "total"}],
             "intent": "state the total"},
        ],
        "variation_seed": "fixture-answers",
    })


def _seed_draft(*, fixtures):
    """A draft whose answer is a + b, plus the fixtures given."""
    params_document = ParamsDocument(
        params_version=1,
        fields=[
            IntegerFieldSpec(name="a", label="A", description="", minimum=1, maximum=50),
            IntegerFieldSpec(name="b", label="B", description="", minimum=1, maximum=50),
        ],
    )
    guard_document = GuardDocument(
        guard_version=1, predicates=[PositivePredicate(value=FieldRefNode(field="a"))]
    )
    answer_expression = AddNode(operands=[FieldRefNode(field="a"), FieldRefNode(field="b")])

    with db.meta_session() as session:
        job = models.GenerationJob(
            id="job-1", fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
            trigger_observation_ids="[]", status=models.JOB_SUCCEEDED,
            created_at=_now(), updated_at=_now(),
        )
        session.add(job)
        session.add(models.TemplateDraft(
            id="draft-1", job_id="job-1", fingerprint_key="k1", fingerprint_version=1,
            fingerprint_json="{}", revision=1,
            params_document_json=params_document.model_dump_json(),
            guard_document_json=guard_document.model_dump_json(),
            answer_expression_json=answer_expression.model_dump_json(),
            teaching_plan_json=_plan().model_dump_json(), scene_program_json="{}",
            quality_report_json='{"passed": true}', classifier_bullet="x",
            dsl_schema_versions_json="{}", artifact_hash="sha256:draft-1",
            status=models.DRAFT_PENDING_REVIEW, created_at=_now(), updated_at=_now(),
        ))
        session.flush()
        for index, fixture in enumerate(fixtures):
            observation_id = None
            if fixture.get("grounded", True):
                observation_id = f"obs-{index}"
                session.add(models.FallbackObservation(
                    id=observation_id, candidate_id=f"cand-{uuid4().hex}",
                    source_excerpt="8 and 3", grade_level=2,
                    observation_kind="unsupported_shape", excluded=False, created_at=_now(),
                ))
                session.flush()
            session.add(models.TemplateDraftFixture(
                id=f"fixture-{index}", draft_id="draft-1", observation_id=observation_id,
                kind=fixture.get("kind", "positive"),
                expected_outcome=fixture.get("expected_outcome", "accept"),
                generation_method="proposed",
                params_json=json.dumps(fixture["params"]),
                expected_result_json=fixture.get("expected_result_json"),
                structural_check_passed=fixture.get("structural_check_passed", True),
                created_at=_now(),
            ))


def test_records_the_answer_the_expression_determines(engine):
    from app.meta.fixture_answers import record_computed_answers

    _seed_draft(fixtures=[{"params": {"a": 8, "b": 3}}])

    with db.meta_session() as session:
        draft = session.get(models.TemplateDraft, "draft-1")
        assert record_computed_answers(session, draft) == 1

    with db.meta_session() as session:
        fixture = session.get(models.TemplateDraftFixture, "fixture-0")
        assert json.loads(fixture.expected_result_json) == {"answer": "11"}


def test_leaves_an_answer_that_is_already_recorded(engine):
    """Re-approving must not churn rows that already hold the same derived value."""
    from app.meta.fixture_answers import record_computed_answers

    _seed_draft(fixtures=[
        {"params": {"a": 8, "b": 3}, "expected_result_json": json.dumps({"answer": "11"})}
    ])

    with db.meta_session() as session:
        draft = session.get(models.TemplateDraft, "draft-1")
        assert record_computed_answers(session, draft) == 0


def test_ignores_guard_fixtures(engine):
    """A fixture that is supposed to be rejected has no answer to record."""
    from app.meta.fixture_answers import record_computed_answers

    _seed_draft(fixtures=[
        {"params": {"a": -1, "b": 3}, "kind": "negative", "expected_outcome": "reject"}
    ])

    with db.meta_session() as session:
        draft = session.get(models.TemplateDraft, "draft-1")
        assert record_computed_answers(session, draft) == 0

    with db.meta_session() as session:
        assert session.get(models.TemplateDraftFixture, "fixture-0").expected_result_json is None


def test_ignores_a_fixture_that_failed_its_structural_check(engine):
    from app.meta.fixture_answers import record_computed_answers

    _seed_draft(fixtures=[{"params": {"a": 8, "b": 3}, "structural_check_passed": False}])

    with db.meta_session() as session:
        draft = session.get(models.TemplateDraft, "draft-1")
        assert record_computed_answers(session, draft) == 0


def test_ignores_a_fixture_with_no_real_observation_behind_it(engine):
    """An ungrounded fixture can never count toward publication anyway."""
    from app.meta.fixture_answers import record_computed_answers

    _seed_draft(fixtures=[{"params": {"a": 8, "b": 3}, "grounded": False}])

    with db.meta_session() as session:
        draft = session.get(models.TemplateDraft, "draft-1")
        assert record_computed_answers(session, draft) == 0


def test_skips_a_fixture_whose_params_cannot_be_evaluated(engine):
    """One unevaluable fixture must not stop the others being recorded."""
    from app.meta.fixture_answers import record_computed_answers

    _seed_draft(fixtures=[
        {"params": {"a": 8}},                # missing b: fails params validation
        {"params": {"a": 8, "b": 3}},
    ])

    with db.meta_session() as session:
        draft = session.get(models.TemplateDraft, "draft-1")
        assert record_computed_answers(session, draft) == 1

    with db.meta_session() as session:
        assert session.get(models.TemplateDraftFixture, "fixture-0").expected_result_json is None
        assert json.loads(
            session.get(models.TemplateDraftFixture, "fixture-1").expected_result_json
        ) == {"answer": "11"}


def test_matches_what_the_admin_fixture_route_would_have_stored(engine):
    """The two paths must agree, or a draft's evidence would depend on who approved it.

    update_fixture stores str(computed_answer) for the same params; this asserts
    the derived value is identical rather than merely plausible.
    """
    from fractions import Fraction

    from app.meta.dsl.expression import compile_expression
    from app.meta.fixture_answers import record_computed_answers
    from app.meta.validation import compile_draft_documents
    from app.meta.dsl.guard import GuardDocument as _Guard
    from app.meta.dsl.params import ParamsDocument as _Params
    from app.meta.dsl.teaching_plan import TeachingPlanDocument as _Plan
    from pydantic import TypeAdapter
    from app.meta.dsl.expression import ExpressionNode

    _seed_draft(fixtures=[{"params": {"a": 8, "b": 3}}])

    with db.meta_session() as session:
        draft = session.get(models.TemplateDraft, "draft-1")
        record_computed_answers(session, draft)
        compiled = compile_draft_documents(
            _Params.model_validate_json(draft.params_document_json),
            _Guard.model_validate_json(draft.guard_document_json),
            TypeAdapter(ExpressionNode).validate_json(draft.answer_expression_json),
            _Plan.model_validate_json(draft.teaching_plan_json),
        )
        params = compiled.params_cls.model_validate({"a": 8, "b": 3})
        expected = compile_expression(
            TypeAdapter(ExpressionNode).validate_json(draft.answer_expression_json),
            compiled.field_contract,
        ).evaluate(params.model_dump())

    assert expected == Fraction(11)
    with db.meta_session() as session:
        stored = json.loads(
            session.get(models.TemplateDraftFixture, "fixture-0").expected_result_json
        )
    assert stored == {"answer": str(expected)}
