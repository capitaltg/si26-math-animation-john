from dataclasses import dataclass
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import ExpressionNode, compile_expression
from app.meta.dsl.limits import MAX_GUARD_PREDICATES, MAX_PREDICATE_TERMS


class RangePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: Literal["range"] = "range"
    value: ExpressionNode
    minimum: ExpressionNode
    maximum: ExpressionNode


class PositivePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: Literal["positive"] = "positive"
    value: ExpressionNode


class EqualsPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: Literal["equals"] = "equals"
    left: ExpressionNode
    right: ExpressionNode


class NotEqualsPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: Literal["not_equals"] = "not_equals"
    left: ExpressionNode
    right: ExpressionNode


class SumEqualsPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: Literal["sum_equals"] = "sum_equals"
    terms: list[ExpressionNode] = Field(min_length=2, max_length=MAX_PREDICATE_TERMS)
    total: ExpressionNode


class ProductEqualsPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: Literal["product_equals"] = "product_equals"
    factors: list[ExpressionNode] = Field(min_length=2, max_length=MAX_PREDICATE_TERMS)
    total: ExpressionNode


class DivisibleByPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: Literal["divisible_by"] = "divisible_by"
    value: ExpressionNode
    divisor: ExpressionNode


class OrderedPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predicate: Literal["ordered"] = "ordered"
    terms: list[ExpressionNode] = Field(min_length=2, max_length=MAX_PREDICATE_TERMS)
    direction: Literal[
        "strictly_increasing", "strictly_decreasing", "non_decreasing", "non_increasing"
    ]


GuardPredicate = Annotated[
    Union[
        RangePredicate,
        PositivePredicate,
        EqualsPredicate,
        NotEqualsPredicate,
        SumEqualsPredicate,
        ProductEqualsPredicate,
        DivisibleByPredicate,
        OrderedPredicate,
    ],
    Field(discriminator="predicate"),
]


class GuardDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guard_version: Literal[1] = 1
    predicates: list[GuardPredicate] = Field(min_length=1, max_length=MAX_GUARD_PREDICATES)


def predicate_expressions(predicate) -> list:
    kind = predicate.predicate
    if kind == "range":
        return [predicate.value, predicate.minimum, predicate.maximum]
    if kind == "positive":
        return [predicate.value]
    if kind in ("equals", "not_equals"):
        return [predicate.left, predicate.right]
    if kind == "sum_equals":
        return [*predicate.terms, predicate.total]
    if kind == "product_equals":
        return [*predicate.factors, predicate.total]
    if kind == "divisible_by":
        return [predicate.value, predicate.divisor]
    if kind == "ordered":
        return list(predicate.terms)
    raise DslValidationError("unknown_predicate", kind)


@dataclass(frozen=True)
class CompiledGuard:
    document: GuardDocument
    known_fields: frozenset[str]


def compile_guard(document: GuardDocument, known_fields: frozenset[str]) -> CompiledGuard:
    for predicate in document.predicates:
        for expression in predicate_expressions(predicate):
            compile_expression(expression, known_fields)
    return CompiledGuard(document=document, known_fields=known_fields)
