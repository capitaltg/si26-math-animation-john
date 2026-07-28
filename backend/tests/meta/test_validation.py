import json
from dataclasses import dataclass

import pytest

from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import FieldRefNode, LiteralNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate, RangePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.validation import compile_draft_documents, validate_fixture


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
    animation_document = AnimationDocument(root={"kind": "label", "text": "n"})
    return params_document, guard_document, answer_expression, animation_document


def test_compile_draft_documents_succeeds_for_consistent_documents():
    compiled = compile_draft_documents(*_documents())
    assert compiled.known_fields == frozenset({"n"})
    instance = compiled.params_cls(n=5)
    assert instance.guard_result().passed is True


def test_compile_draft_documents_raises_on_unknown_field_in_answer_expression():
    params_document, guard_document, _, animation_document = _documents()
    with pytest.raises(DslValidationError):
        compile_draft_documents(
            params_document, guard_document, FieldRefNode(field="ghost"), animation_document
        )


@dataclass
class _Fixture:
    id: str
    params_json: str
    expected_outcome: str
    kind: str


def test_validate_fixture_accepts_matching_positive_fixture():
    compiled = compile_draft_documents(*_documents())
    fixture = _Fixture(id="fx-1", params_json=json.dumps({"n": 5}), expected_outcome="accept", kind="positive")
    result = validate_fixture(fixture, compiled, source_excerpt="there are 5 apples")
    assert result.passed is True


def test_validate_fixture_fails_when_positive_fixture_is_not_grounded():
    compiled = compile_draft_documents(*_documents())
    fixture = _Fixture(id="fx-1", params_json=json.dumps({"n": 5}), expected_outcome="accept", kind="positive")
    result = validate_fixture(fixture, compiled, source_excerpt="there are seven oranges")
    assert result.passed is False
    assert "not grounded" in result.detail


def test_validate_fixture_accepts_matching_negative_fixture():
    compiled = compile_draft_documents(*_documents())
    fixture = _Fixture(id="fx-2", params_json=json.dumps({"n": -1}), expected_outcome="reject", kind="negative")
    result = validate_fixture(fixture, compiled, source_excerpt=None)
    assert result.passed is True


def test_validate_fixture_fails_when_declared_outcome_does_not_match_reality():
    compiled = compile_draft_documents(*_documents())
    fixture = _Fixture(id="fx-3", params_json=json.dumps({"n": 5}), expected_outcome="reject", kind="negative")
    result = validate_fixture(fixture, compiled, source_excerpt=None)
    assert result.passed is False
    assert "expected reject, got accept" in result.detail
