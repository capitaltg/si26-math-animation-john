from dataclasses import dataclass
from fractions import Fraction
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import (
    ExpressionNode,
    compile_expression,
    _evaluate,
    _to_fraction,
)
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


@dataclass(frozen=True)
class PredicateResult:
    index: int
    predicate_type: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GuardResult:
    passed: bool
    predicate_results: list[PredicateResult]


_ORDER_CHECKS = {
    "strictly_increasing": lambda a, b: a < b,
    "strictly_decreasing": lambda a, b: a > b,
    "non_decreasing": lambda a, b: a <= b,
    "non_increasing": lambda a, b: a >= b,
}


def _check_single_predicate(predicate, values: dict) -> tuple[bool, str]:
    kind = predicate.predicate
    if kind == "range":
        value = _evaluate(predicate.value, values)
        minimum = _evaluate(predicate.minimum, values)
        maximum = _evaluate(predicate.maximum, values)
        return (minimum <= value <= maximum, f"{value} in [{minimum}, {maximum}]")
    if kind == "positive":
        value = _evaluate(predicate.value, values)
        return (value > 0, f"{value} > 0")
    if kind == "equals":
        left, right = _evaluate(predicate.left, values), _evaluate(predicate.right, values)
        return (left == right, f"{left} == {right}")
    if kind == "not_equals":
        left, right = _evaluate(predicate.left, values), _evaluate(predicate.right, values)
        return (left != right, f"{left} != {right}")
    if kind == "sum_equals":
        terms = [_evaluate(term, values) for term in predicate.terms]
        total = _evaluate(predicate.total, values)
        return (sum(terms, Fraction(0)) == total, f"sum({terms}) == {total}")
    if kind == "product_equals":
        factors = [_evaluate(factor, values) for factor in predicate.factors]
        total = _evaluate(predicate.total, values)
        product = Fraction(1)
        for factor in factors:
            product *= factor
        return (product == total, f"product({factors}) == {total}")
    if kind == "divisible_by":
        value = _evaluate(predicate.value, values)
        divisor = _evaluate(predicate.divisor, values)
        if divisor == 0:
            raise DslValidationError("divide_by_zero", f"{value} % {divisor}")
        return (value % divisor == 0, f"{value} % {divisor} == 0")
    if kind == "ordered":
        terms = [_evaluate(term, values) for term in predicate.terms]
        check = _ORDER_CHECKS[predicate.direction]
        ok = all(check(a, b) for a, b in zip(terms, terms[1:]))
        return (ok, f"{terms} {predicate.direction}")
    raise DslValidationError("unknown_predicate", kind)


def _check_guard(self: CompiledGuard, values: dict) -> GuardResult:
    results = []
    for index, predicate in enumerate(self.document.predicates):
        passed, detail = _check_single_predicate(predicate, values)
        results.append(PredicateResult(index, predicate.predicate, passed, detail))
    return GuardResult(passed=all(r.passed for r in results), predicate_results=results)


CompiledGuard.check = _check_guard


def derive_literal_operands(document: GuardDocument) -> set[Fraction]:
    literals: set[Fraction] = set()

    def walk(node) -> None:
        if node.node == "literal":
            literals.add(_to_fraction(node.value))
            return
        if node.node == "field_ref":
            return
        for operand in node.operands:
            walk(operand)

    for predicate in document.predicates:
        for expression in predicate_expressions(predicate):
            walk(expression)
    return literals


def derive_permitted_derived_totals(document: GuardDocument, values: dict) -> set[Fraction]:
    totals: set[Fraction] = set()
    for predicate in document.predicates:
        if predicate.predicate in ("sum_equals", "product_equals"):
            totals.add(_evaluate(predicate.total, values))
    return totals
