from dataclasses import dataclass
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.limits import MAX_EXPRESSION_DEPTH, MAX_EXPRESSION_OPERATIONS

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
