from dataclasses import dataclass
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


def compile_expression(node, known_fields: frozenset[str]) -> CompiledExpression:
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
            if current.field not in known_fields:
                raise DslValidationError("unknown_field", current.field)
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
    return _to_fraction(raw)


def _check_magnitude(result: Fraction) -> Fraction:
    if abs(result) > MAX_NUMERIC_MAGNITUDE:
        raise DslValidationError("overflow", f"magnitude {result} exceeds {MAX_NUMERIC_MAGNITUDE}")
    return result


def _evaluate(node, values: dict) -> Fraction:
    if node.node == "literal":
        return _to_fraction(node.value)
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
