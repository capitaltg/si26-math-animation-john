from fractions import Fraction

import pytest
from pydantic import ValidationError

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import (
    AddNode,
    DivideNode,
    FieldRefNode,
    LiteralNode,
    FieldContract,
    MultiplyNode,
    _evaluate,
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


# --- array item addressing -------------------------------------------------
# `ArrayFieldSpec.item_fields` makes every array element an OBJECT, so
# `model_dump()` yields a list of dicts. `FieldRefNode` could reach `scores[0]`
# -- that dict -- but had no way to select a scalar inside it, so every
# expression over an array field died at evaluation with
# `unsupported_type: <class 'dict'>`, surfacing to an operator as a fixture that
# "expected accept, got reject". `compile_expression` could not catch it either:
# it received field NAMES with the types stripped.


def _array_contract():
    return FieldContract(
        scalars=frozenset({"target"}),
        arrays={"scores": frozenset({"value", "weight"})},
    )


def test_a_field_ref_reads_a_scalar_out_of_an_array_item():
    node = FieldRefNode(field="scores", index=1, item_field="value")
    compile_expression(node, _array_contract())

    result = _evaluate(node, {"scores": [{"value": 5}, {"value": 9}], "target": 2})

    assert result == Fraction(9)


def test_an_array_reference_without_an_item_field_is_rejected_at_compile_time():
    with pytest.raises(DslValidationError) as exc_info:
        compile_expression(FieldRefNode(field="scores", index=0), _array_contract())

    assert exc_info.value.code == "array_item_field_required"
    assert "scores" in str(exc_info.value)
    assert "value" in str(exc_info.value) and "weight" in str(exc_info.value)


def test_an_array_reference_without_an_index_is_rejected_at_compile_time():
    with pytest.raises(DslValidationError) as exc_info:
        compile_expression(
            FieldRefNode(field="scores", item_field="value"), _array_contract()
        )

    assert exc_info.value.code == "array_index_required"


def test_an_item_field_on_a_scalar_field_is_rejected_at_compile_time():
    with pytest.raises(DslValidationError) as exc_info:
        compile_expression(FieldRefNode(field="target", item_field="value"), _array_contract())

    assert exc_info.value.code == "unexpected_item_field"


def test_an_unknown_item_field_names_the_ones_the_array_declares():
    with pytest.raises(DslValidationError) as exc_info:
        compile_expression(
            FieldRefNode(field="scores", index=0, item_field="missing"), _array_contract()
        )

    assert exc_info.value.code == "unknown_item_field"
    assert "value" in str(exc_info.value) and "weight" in str(exc_info.value)


def test_a_bare_frozenset_of_names_still_compiles_scalar_references():
    """Every existing caller passes names only; those must keep working."""
    compile_expression(FieldRefNode(field="length"), frozenset({"length"}))
