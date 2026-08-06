from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from fractions import Fraction
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.limits import MAX_EXPRESSION_DEPTH, MAX_EXPRESSION_OPERATIONS, MAX_NUMERIC_MAGNITUDE

_FIELD_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class LiteralNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: Literal["literal"] = "literal"
    value: float


class FieldRefNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: Literal["field_ref"] = "field_ref"
    field: str = Field(pattern=_FIELD_NAME_PATTERN)
    index: int | None = Field(default=None, ge=0, le=11)
    #: Scalar to read inside an array item. An `ArrayFieldSpec` item is an object,
    #: so `scores[0]` alone is a dict; `scores[0].value` is a number.
    item_field: str | None = Field(default=None, pattern=_FIELD_NAME_PATTERN)


class AddNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: Literal["add"] = "add"
    operands: list["ExpressionNode"] = Field(min_length=2, max_length=4)


class SubtractNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: Literal["subtract"] = "subtract"
    operands: list["ExpressionNode"] = Field(min_length=2, max_length=2)


class MultiplyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: Literal["multiply"] = "multiply"
    operands: list["ExpressionNode"] = Field(min_length=2, max_length=4)


class DivideNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: Literal["divide"] = "divide"
    operands: list["ExpressionNode"] = Field(min_length=2, max_length=2)


class FractionNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: Literal["fraction"] = "fraction"
    operands: list["ExpressionNode"] = Field(min_length=2, max_length=2)


ExpressionNode = Annotated[
    Union[LiteralNode, FieldRefNode, AddNode, SubtractNode, MultiplyNode, DivideNode, FractionNode],
    Field(discriminator="node"),
]

for _cls in (AddNode, SubtractNode, MultiplyNode, DivideNode, FractionNode):
    _cls.model_rebuild()


def _is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


@dataclass(frozen=True)
class CompiledExpression:
    root: "ExpressionNode"
    referenced_fields: frozenset[str]


@dataclass(frozen=True)
class FieldContract:
    """The fields an expression may read, and the shape of each.

    Compilation used to receive field NAMES with the types stripped, so it could
    not tell a scalar from an array of objects. An `ArrayFieldSpec` materialises
    as ``list[item_model]``, so a reference to one yields a dict that
    ``_to_fraction`` cannot convert -- and the only report of it was a runtime
    ``unsupported_type: <class 'dict'>`` raised deep inside params validation,
    reaching an operator as a fixture that "expected accept, got reject".
    """

    scalars: frozenset[str] = frozenset()
    arrays: Mapping[str, frozenset[str]] = dataclass_field(default_factory=dict)
    #: Minimum value each numeric scalar field can carry, keyed by field name.
    #: Only integer/decimal fields appear here; string/enum fields have no
    #: numeric minimum. Callers that hand compilation a bare set of names get
    #: an empty mapping, so a range check falls back to "unknown" rather than
    #: passing a field with an unknowable minimum.
    scalar_minimums: Mapping[str, Fraction] = dataclass_field(default_factory=dict)

    @classmethod
    def of(cls, fields) -> "FieldContract":
        """Accept a contract, or a bare set of names from a caller without types."""
        if isinstance(fields, FieldContract):
            return fields
        return cls(scalars=frozenset(fields), arrays={}, scalar_minimums={})

    @property
    def names(self) -> frozenset[str]:
        return self.scalars | frozenset(self.arrays)


def _validate_field_ref(current, contract: FieldContract) -> None:
    if current.field not in contract.names:
        raise DslValidationError("unknown_field", current.field)
    item_fields = contract.arrays.get(current.field)
    if item_fields is None:
        if current.item_field is not None:
            raise DslValidationError(
                "unexpected_item_field",
                f"{current.field} is not an array field, so it has no item field "
                f"{current.item_field!r}",
            )
        return
    legal = ", ".join(sorted(item_fields))
    if current.item_field is None:
        raise DslValidationError(
            "array_item_field_required",
            f"{current.field} is an array of items; name one of its item fields: {legal}",
        )
    if current.index is None:
        raise DslValidationError(
            "array_index_required",
            f"{current.field}.{current.item_field} needs the index of the item to read",
        )
    if current.item_field not in item_fields:
        raise DslValidationError(
            "unknown_item_field",
            f"{current.field} declares no item field {current.item_field!r}; "
            f"it declares: {legal}",
        )


def compile_expression(node, known_fields) -> CompiledExpression:
    contract = FieldContract.of(known_fields)
    referenced: set[str] = set()
    op_count = 0

    def walk(current, depth: int) -> None:
        nonlocal op_count
        if depth > MAX_EXPRESSION_DEPTH:
            raise DslValidationError(
                "expression_too_deep", f"max depth {MAX_EXPRESSION_DEPTH} exceeded"
            )
        if current.node == "literal":
            if not _is_finite(current.value):
                raise DslValidationError("non_finite_literal", f"{current.value} is not finite")
            return
        if current.node == "field_ref":
            _validate_field_ref(current, contract)
            referenced.add(current.field)
            return
        op_count += 1
        if op_count > MAX_EXPRESSION_OPERATIONS:
            raise DslValidationError(
                "too_many_operations", f"max {MAX_EXPRESSION_OPERATIONS} exceeded"
            )
        for operand in current.operands:
            walk(operand, depth + 1)

    walk(node, 0)
    return CompiledExpression(root=node, referenced_fields=frozenset(referenced))


def _to_fraction(value) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise DslValidationError("unsupported_type", "bool is not a numeric value")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if not _is_finite(value):
            raise DslValidationError("non_finite_value", f"{value} is not finite")
        return Fraction(value).limit_denominator(10**9)
    raise DslValidationError("unsupported_type", str(type(value)))


def _resolve_field(field_ref: "FieldRefNode", values: dict) -> Fraction:
    if field_ref.field not in values:
        raise DslValidationError("missing_value", field_ref.field)
    raw = values[field_ref.field]
    if field_ref.index is not None:
        if not isinstance(raw, (list, tuple)) or field_ref.index >= len(raw):
            raise DslValidationError("index_out_of_range", f"{field_ref.field}[{field_ref.index}]")
        raw = raw[field_ref.index]
    if field_ref.item_field is not None:
        # An array item is an object; read the named scalar out of it. Reached only
        # for a reference `compile_expression` accepted, so the shape is checked.
        if not isinstance(raw, Mapping) or field_ref.item_field not in raw:
            raise DslValidationError(
                "unknown_item_field",
                f"{field_ref.field}[{field_ref.index}].{field_ref.item_field}",
            )
        raw = raw[field_ref.item_field]
    return _check_magnitude(_to_fraction(raw))


def _check_magnitude(result: Fraction) -> Fraction:
    if abs(result) > MAX_NUMERIC_MAGNITUDE:
        raise DslValidationError("overflow", f"magnitude {result} exceeds {MAX_NUMERIC_MAGNITUDE}")
    return result


def _evaluate(node, values: dict) -> Fraction:
    if node.node == "literal":
        return _check_magnitude(_to_fraction(node.value))
    if node.node == "field_ref":
        return _resolve_field(node, values)
    operands = [_evaluate(operand, values) for operand in node.operands]
    if node.node == "add":
        result = sum(operands, Fraction(0))
    elif node.node == "subtract":
        result = operands[0] - operands[1]
    elif node.node == "multiply":
        result = Fraction(1)
        for operand in operands:
            result *= operand
    elif node.node in ("divide", "fraction"):
        if operands[1] == 0:
            raise DslValidationError("divide_by_zero", f"{operands[0]} / {operands[1]}")
        result = operands[0] / operands[1]
    else:
        raise DslValidationError("unknown_node", node.node)
    return _check_magnitude(result)


def _evaluate_expression(self: "CompiledExpression", values: dict) -> Fraction:
    return _evaluate(self.root, values)


CompiledExpression.evaluate = _evaluate_expression
