import pytest
from pydantic import ValidationError

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import (
    AddNode,
    DivideNode,
    FieldRefNode,
    LiteralNode,
    MultiplyNode,
    compile_expression,
)


def test_literal_and_field_ref_compile():
    node = AddNode(operands=[LiteralNode(value=2), FieldRefNode(field="a")])
    compiled = compile_expression(node, known_fields=frozenset({"a"}))
    assert compiled.referenced_fields == {"a"}


def test_unknown_field_rejected():
    node = FieldRefNode(field="ghost")
    with pytest.raises(DslValidationError) as exc:
        compile_expression(node, known_fields=frozenset({"a"}))
    assert exc.value.code == "unknown_field"


def test_extra_key_rejected_by_schema():
    with pytest.raises(ValidationError):
        LiteralNode.model_validate({"node": "literal", "value": 1, "sneaky": "x"})


def test_operand_arity_enforced():
    with pytest.raises(ValidationError):
        DivideNode(operands=[LiteralNode(value=1)])
    with pytest.raises(ValidationError):
        MultiplyNode(operands=[LiteralNode(value=1)])


def test_non_finite_literal_rejected():
    node = LiteralNode(value=float("inf"))
    with pytest.raises(DslValidationError) as exc:
        compile_expression(node, known_fields=frozenset())
    assert exc.value.code == "non_finite_literal"


def test_depth_limit_enforced():
    node = LiteralNode(value=1)
    for _ in range(10):
        node = AddNode(operands=[node, LiteralNode(value=1)])
    with pytest.raises(DslValidationError) as exc:
        compile_expression(node, known_fields=frozenset())
    assert exc.value.code == "expression_too_deep"


def test_operation_count_limit_enforced():
    node = LiteralNode(value=1)
    for _ in range(25):
        node = AddNode(operands=[node, LiteralNode(value=1)])
    with pytest.raises(DslValidationError) as exc:
        compile_expression(node, known_fields=frozenset())
    assert exc.value.code in ("too_many_operations", "expression_too_deep")
