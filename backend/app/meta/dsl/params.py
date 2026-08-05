from fractions import Fraction
from itertools import product
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import FieldContract, _evaluate
from app.meta.dsl.guard import CompiledGuard, GuardResult, predicate_expressions
from app.meta.dsl.limits import MAX_ARRAY_ITEMS, MAX_ENUM_CHOICES, MAX_PARAMS_FIELDS, MAX_STRING_LENGTH
from app.pipeline.grounding import default_number_tokens

_FIELD_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class IntegerFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["integer"] = "integer"
    name: str = Field(pattern=_FIELD_NAME_PATTERN)
    label: str = Field(max_length=MAX_STRING_LENGTH)
    description: str = Field(max_length=MAX_STRING_LENGTH)
    required: bool = True
    default: int | None = None
    minimum: int
    maximum: int

    @model_validator(mode="after")
    def _min_le_max(self):
        if self.minimum > self.maximum:
            raise ValueError(f"minimum ({self.minimum}) must be <= maximum ({self.maximum})")
        return self

    @model_validator(mode="after")
    def _default_within_bounds(self):
        if self.default is not None and not (self.minimum <= self.default <= self.maximum):
            raise ValueError(
                f"default ({self.default}) must be within [{self.minimum}, {self.maximum}]"
            )
        return self


class DecimalFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["decimal"] = "decimal"
    name: str = Field(pattern=_FIELD_NAME_PATTERN)
    label: str = Field(max_length=MAX_STRING_LENGTH)
    description: str = Field(max_length=MAX_STRING_LENGTH)
    required: bool = True
    default: float | None = None
    minimum: float
    maximum: float

    @model_validator(mode="after")
    def _min_le_max(self):
        if self.minimum > self.maximum:
            raise ValueError(f"minimum ({self.minimum}) must be <= maximum ({self.maximum})")
        return self

    @model_validator(mode="after")
    def _default_within_bounds(self):
        if self.default is not None and not (self.minimum <= self.default <= self.maximum):
            raise ValueError(
                f"default ({self.default}) must be within [{self.minimum}, {self.maximum}]"
            )
        return self


class StringFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["string"] = "string"
    name: str = Field(pattern=_FIELD_NAME_PATTERN)
    label: str = Field(max_length=MAX_STRING_LENGTH)
    description: str = Field(max_length=MAX_STRING_LENGTH)
    required: bool = True
    default: str | None = Field(default=None, max_length=MAX_STRING_LENGTH)
    max_length: int = Field(gt=0, le=MAX_STRING_LENGTH)

    @model_validator(mode="after")
    def _default_within_max_length(self):
        if self.default is not None and len(self.default) > self.max_length:
            raise ValueError(
                f"default length ({len(self.default)}) must be <= max_length ({self.max_length})"
            )
        return self


class EnumFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["enum"] = "enum"
    name: str = Field(pattern=_FIELD_NAME_PATTERN)
    label: str = Field(max_length=MAX_STRING_LENGTH)
    description: str = Field(max_length=MAX_STRING_LENGTH)
    required: bool = True
    default: str | None = None
    choices: list[str] = Field(min_length=2, max_length=MAX_ENUM_CHOICES)

    @model_validator(mode="after")
    def _default_in_choices(self):
        if self.default is not None and self.default not in self.choices:
            raise ValueError(f"default ({self.default!r}) must be one of choices ({self.choices})")
        return self


NonArrayFieldSpec = Annotated[
    Union[IntegerFieldSpec, DecimalFieldSpec, StringFieldSpec, EnumFieldSpec],
    Field(discriminator="type"),
]


class ArrayFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["array"] = "array"
    name: str = Field(pattern=_FIELD_NAME_PATTERN)
    label: str = Field(max_length=MAX_STRING_LENGTH)
    description: str = Field(max_length=MAX_STRING_LENGTH)
    required: bool = True
    min_items: int = Field(ge=0, le=MAX_ARRAY_ITEMS)
    max_items: int = Field(gt=0, le=MAX_ARRAY_ITEMS)
    item_fields: list[NonArrayFieldSpec] = Field(min_length=1, max_length=MAX_PARAMS_FIELDS)

    @model_validator(mode="after")
    def _min_items_le_max_items(self):
        if self.min_items > self.max_items:
            raise ValueError(f"min_items ({self.min_items}) must be <= max_items ({self.max_items})")
        return self

    @model_validator(mode="after")
    def _no_duplicate_item_field_names(self):
        names = [item.name for item in self.item_fields]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate field names in array item_fields: {names}")
        return self

    @model_validator(mode="after")
    def _optional_default_within_bounds(self):
        # Optional arrays always fall back to an implicit `[]` default (see
        # _field_definition's default_factory=list), so an optional array
        # with min_items > 0 could never be validly omitted.
        if not self.required and self.min_items > 0:
            raise ValueError(
                "an optional array field (required=False) cannot have min_items > 0, "
                f"since its implicit default [] would violate min_items ({self.min_items})"
            )
        return self


ParamsFieldSpec = Annotated[
    Union[IntegerFieldSpec, DecimalFieldSpec, StringFieldSpec, EnumFieldSpec, ArrayFieldSpec],
    Field(discriminator="type"),
]


class ParamsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    params_version: Literal[1] = 1
    fields: list[ParamsFieldSpec] = Field(min_length=1, max_length=MAX_PARAMS_FIELDS)

    @model_validator(mode="after")
    def _no_duplicate_names(self):
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate field names in params document: {names}")
        return self


class TemplateParamsBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def guard_result(self) -> GuardResult:
        raise NotImplementedError("guard_result is set on the compiled subclass")


def _field_definition(spec) -> tuple[type, object]:
    # The spec's `description` rides along into the JSON schema. It is the only
    # thing that says what a field HOLDS: extraction hands the schema to a model,
    # and a bare name like `object_name` reads as "some object", so the model
    # guessed and declined a problem it could have extracted. Pydantic derives a
    # `title` from the name, which carries no such information.
    described = {"description": spec.description}
    if spec.type == "integer":
        py_type = int
        default_kwargs = {} if spec.required else {"default": spec.default}
        field = Field(ge=spec.minimum, le=spec.maximum, **described, **default_kwargs)
    elif spec.type == "decimal":
        py_type = float
        default_kwargs = {} if spec.required else {"default": spec.default}
        field = Field(ge=spec.minimum, le=spec.maximum, **described, **default_kwargs)
    elif spec.type == "string":
        py_type = str
        default_kwargs = {} if spec.required else {"default": spec.default}
        field = Field(max_length=spec.max_length, **described, **default_kwargs)
    elif spec.type == "enum":
        py_type = Literal[tuple(spec.choices)]
        default_kwargs = {} if spec.required else {"default": spec.default}
        field = Field(**described, **default_kwargs)
    elif spec.type == "array":
        item_model = create_model(
            f"_{spec.name}_Item",
            __config__=ConfigDict(extra="forbid"),
            **{item.name: _field_definition(item) for item in spec.item_fields},
        )
        py_type = list[item_model]
        default_kwargs = {} if spec.required else {"default_factory": list}
        field = Field(
            min_length=spec.min_items, max_length=spec.max_items, **described, **default_kwargs
        )
    else:
        raise ValueError(f"unknown field type: {spec.type}")
    if not spec.required and spec.type != "array":
        py_type = py_type | None
    return (py_type, field)


def _format_fraction_component(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def compile_template_params(document: ParamsDocument, compiled_guard: CompiledGuard) -> type[TemplateParamsBase]:
    field_definitions = {spec.name: _field_definition(spec) for spec in document.fields}
    decimal_field_names = frozenset(spec.name for spec in document.fields if spec.type == "decimal")
    dynamic_base = create_model(
        "_DynamicTemplateParamsBase",
        __base__=TemplateParamsBase,
        **field_definitions,
    )

    class DynamicTemplateParams(dynamic_base):
        @model_validator(mode="after")
        def _check_guard(self):
            try:
                result = compiled_guard.check(self.model_dump())
            except DslValidationError as exc:
                raise ValueError(f"guard evaluation error: {exc}") from exc
            if not result.passed:
                failed = next(r for r in result.predicate_results if not r.passed)
                raise ValueError(
                    f"guard predicate failed: {failed.predicate_type} ({failed.detail})"
                )
            self.__dict__["_guard_result"] = result
            return self

        def guard_result(self) -> GuardResult:
            return self.__dict__["_guard_result"]

        def grounding_number_tokens(self) -> list[str]:
            tokens = default_number_tokens(self)
            values = self.model_dump()
            for predicate in compiled_guard.document.predicates:
                for expression in predicate_expressions(predicate):
                    if (
                        getattr(expression, "node", None) == "fraction"
                        and all(
                            getattr(operand, "node", None) == "field_ref"
                            for operand in expression.operands
                        )
                    ):
                        numerator, denominator = (
                            _evaluate(operand, values) for operand in expression.operands
                        )
                        tokens.append(
                            f"{_format_fraction_component(numerator)}/{_format_fraction_component(denominator)}"
                        )
            return tokens

        def grounding_derived_totals(self) -> list[tuple[str, list[str]]]:
            values = self.model_dump()

            def format_component(node) -> str:
                # A field_ref into a decimal field must stringify exactly like
                # default_number_tokens does for that same field (plain
                # str(value), e.g. "7.5" or "7.0") so the derived-total token
                # can actually match the token default_number_tokens produces
                # for it. Fraction-based formatting (used for everything else)
                # would instead emit "15/2" or drop a whole-number's trailing
                # ".0", which can never match.
                if (
                    getattr(node, "node", None) == "field_ref"
                    and node.index is None
                    and node.field in decimal_field_names
                ):
                    return str(values[node.field])
                # A fixed decimal constant baked directly into the guard (not a
                # field reference) needs the same plain-decimal stringification:
                # a non-integral literal like 2.5 must format as "2.5", not the
                # fraction formatter's "5/2". An integral literal (e.g. 3.0) is
                # left on the fraction path, which already renders it as the
                # bare "3" that whole-number source text uses.
                if getattr(node, "node", None) == "literal" and not node.value.is_integer():
                    return str(node.value)
                return _format_fraction_component(_evaluate(node, values))

            def component_variants(node) -> tuple[str, ...]:
                primary = format_component(node)
                if getattr(node, "node", None) != "literal" or node.value.is_integer():
                    return (primary,)
                fraction = _format_fraction_component(_evaluate(node, values))
                return (primary,) if fraction == primary else (primary, fraction)

            derived: list[tuple[str, list[str]]] = []
            for predicate in compiled_guard.document.predicates:
                if predicate.predicate == "sum_equals":
                    terms, total = predicate.terms, predicate.total
                    operation = "sum"
                elif predicate.predicate == "product_equals":
                    terms, total = predicate.factors, predicate.total
                    operation = "product"
                else:
                    continue
                if getattr(total, "node", None) not in ("literal", "field_ref"):
                    continue
                if not all(getattr(term, "node", None) in ("literal", "field_ref") for term in terms):
                    continue
                total_token = format_component(total)
                for component_tokens in product(*(component_variants(term) for term in terms)):
                    if operation == "sum":
                        derived.append((total_token, list(component_tokens)))
                    else:
                        derived.append((total_token, list(component_tokens), operation))
            return derived

    return DynamicTemplateParams


def field_contract_for(document: ParamsDocument) -> FieldContract:
    """The expression-visible shape of a params document.

    An `ArrayFieldSpec` materialises as ``list[item_model]``, so an expression
    reading one needs both an index and the name of a scalar inside the item.
    Handing compilation only the field names left it unable to require either.
    """
    return FieldContract(
        scalars=frozenset(
            spec.name for spec in document.fields if spec.type != "array"
        ),
        arrays={
            spec.name: frozenset(item.name for item in spec.item_fields)
            for spec in document.fields if spec.type == "array"
        },
        scalar_minimums={
            spec.name: Fraction(spec.minimum).limit_denominator(10**9)
            for spec in document.fields if spec.type in ("integer", "decimal")
        },
    )
