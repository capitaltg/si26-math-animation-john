import json
from dataclasses import dataclass

import pytest

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.validation import compile_draft_documents, validate_fixture
from app.meta.versions import DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION


def _documents():
    params_document = ParamsDocument(
        params_version=1,
        fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[PositivePredicate(value=FieldRefNode(field="n"))],
    )
    answer_expression = FieldRefNode(field="n")
    teaching_plan_document = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Show one number and state its value.",
        "primary_visual": {"kind": "label", "ref": "number", "text": "n"},
        "strategy": "group_reveal",
        "beats": [
            {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "number"}], "intent": "show the number"},
            {"id": "focus", "kind": "focus", "targets": [{"visual_ref": "number"}], "intent": "identify the number"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "number"}], "intent": "state the answer"},
        ],
        "variation_seed": "validation-unit",
    })
    return params_document, guard_document, answer_expression, teaching_plan_document


def test_compile_draft_documents_succeeds_for_consistent_v3_documents():
    compiled = compile_draft_documents(*_documents())
    assert compiled.known_fields == frozenset({"n"})
    assert compiled.params_cls(n=5).guard_result().passed is True


def test_compile_draft_documents_raises_on_unknown_field_in_answer_expression():
    params_document, guard_document, _, teaching_plan_document = _documents()

    with pytest.raises(DslValidationError) as exc:
        compile_draft_documents(
            params_document,
            guard_document,
            FieldRefNode(field="ghost"),
            teaching_plan_document,
        )

    assert exc.value.code == "unknown_field"


@dataclass
class _Fixture:
    id: str
    params_json: str
    expected_outcome: str
    kind: str


def test_validate_fixture_accepts_matching_positive_fixture():
    compiled = compile_draft_documents(*_documents())
    fixture = _Fixture("fx-1", json.dumps({"n": 5}), "accept", "positive")

    result = validate_fixture(fixture, compiled, source_excerpt="there are 5 apples")

    assert result.passed is True


def test_validate_fixture_tracks_the_failed_guard_predicate_for_a_negative_fixture():
    compiled = compile_draft_documents(*_documents())
    fixture = _Fixture("fx-2", json.dumps({"n": -1}), "reject", "negative")

    result = validate_fixture(fixture, compiled, source_excerpt=None)

    assert result.passed is True
    assert result.failed_predicate_indexes == frozenset({0})


def test_older_runtime_versions_make_their_validation_reports_stale():
    stale_report = {"compiler_version": 3, "renderer_version": 3}

    assert (stale_report["compiler_version"], stale_report["renderer_version"]) != (
        DSL_COMPILER_VERSION,
        DYNAMIC_RENDERER_VERSION,
    )
    # Pinned so a compiler/renderer change cannot land without a deliberate bump.
    assert (DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION) == (8, 7)
