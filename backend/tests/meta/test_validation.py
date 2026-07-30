import json
from dataclasses import dataclass

import pytest

from app.meta.dsl.animation import (
    AnimationDocument,
    AppearNode,
    ColumnNode,
    ExpressionLabelNode,
    LabelNode,
    SequenceNode,
    WaitNode,
)
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


def _version_two_documents(animation_root):
    params_document, guard_document, answer_expression, _ = _documents()
    return (
        params_document,
        guard_document,
        answer_expression,
        AnimationDocument(animation_version=2, root=animation_root),
    )


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


def test_version_two_draft_rejects_missing_visible_answer():
    with pytest.raises(DslValidationError) as exc:
        compile_draft_documents(
            *_version_two_documents(LabelNode(text="Solve the problem"))
        )
    assert exc.value.code == "answer_not_displayed"


def test_version_two_draft_rejects_mismatched_visible_answer():
    with pytest.raises(DslValidationError) as exc:
        compile_draft_documents(
            *_version_two_documents(
                ExpressionLabelNode(
                    expression=LiteralNode(value=999),
                    role="answer",
                )
            )
        )
    assert exc.value.code == "answer_not_displayed"


def test_version_two_draft_rejects_matching_answer_that_never_appears():
    with pytest.raises(DslValidationError) as exc:
        compile_draft_documents(
            *_version_two_documents(
                SequenceNode(
                    steps=[
                        ExpressionLabelNode(
                            ref="answer",
                            expression=FieldRefNode(field="n"),
                            role="answer",
                        ),
                        LabelNode(ref="prompt", text="Solve the problem"),
                        AppearNode(target_ref="prompt"),
                        WaitNode(seconds=1),
                    ]
                )
            )
        )
    assert exc.value.code == "answer_not_displayed"


def test_version_two_draft_rejects_answer_appeared_before_it_is_built():
    with pytest.raises(DslValidationError) as exc:
        compile_draft_documents(
            *_version_two_documents(
                SequenceNode(
                    steps=[
                        AppearNode(target_ref="answer"),
                        ExpressionLabelNode(
                            ref="answer",
                            expression=FieldRefNode(field="n"),
                            role="answer",
                        ),
                        WaitNode(seconds=1),
                    ]
                )
            )
        )
    assert exc.value.code == "answer_not_displayed"


def test_version_two_draft_accepts_matching_visible_answer():
    compiled = compile_draft_documents(
        *_version_two_documents(
            SequenceNode(
                steps=[
                    ExpressionLabelNode(
                        ref="answer",
                        expression=FieldRefNode(field="n"),
                        prefix="Answer: ",
                        role="answer",
                    ),
                    AppearNode(target_ref="answer"),
                    WaitNode(seconds=1),
                ]
            )
        )
    )
    assert compiled.compiled_animation.answer_expressions == (
        FieldRefNode(field="n"),
    )
    assert compiled.compiled_animation.visible_answer_expressions == (
        FieldRefNode(field="n"),
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
