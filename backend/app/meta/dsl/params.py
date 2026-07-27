from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from app.meta.dsl.guard import CompiledGuard, GuardResult
from app.meta.dsl.limits import MAX_ARRAY_ITEMS, MAX_ENUM_CHOICES, MAX_PARAMS_FIELDS, MAX_STRING_LENGTH

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


class StringFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["string"] = "string"
    name: str = Field(pattern=_FIELD_NAME_PATTERN)
    label: str = Field(max_length=MAX_STRING_LENGTH)
    description: str = Field(max_length=MAX_STRING_LENGTH)
    required: bool = True
    default: str | None = Field(default=None, max_length=MAX_STRING_LENGTH)
    max_length: int = Field(gt=0, le=MAX_STRING_LENGTH)


class EnumFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["enum"] = "enum"
    name: str = Field(pattern=_FIELD_NAME_PATTERN)
    label: str = Field(max_length=MAX_STRING_LENGTH)
    description: str = Field(max_length=MAX_STRING_LENGTH)
    required: bool = True
    default: str | None = None
    choices: list[str] = Field(min_length=2, max_length=MAX_ENUM_CHOICES)


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
    if spec.type == "integer":
        py_type = int
        field = Field(default=spec.default, ge=spec.minimum, le=spec.maximum)
    elif spec.type == "decimal":
        py_type = float
        field = Field(default=spec.default, ge=spec.minimum, le=spec.maximum)
    elif spec.type == "string":
        py_type = str
        field = Field(default=spec.default, max_length=spec.max_length)
    elif spec.type == "enum":
        py_type = Literal[tuple(spec.choices)]
        field = Field(default=spec.default)
    elif spec.type == "array":
        item_model = create_model(
            f"_{spec.name}_Item",
            __config__=ConfigDict(extra="forbid"),
            **{item.name: _field_definition(item) for item in spec.item_fields},
        )
        py_type = list[item_model]
        field = Field(default_factory=list, min_length=spec.min_items, max_length=spec.max_items)
    else:
        raise ValueError(f"unknown field type: {spec.type}")
    if not spec.required and spec.type != "array":
        py_type = py_type | None
    return (py_type, field)


def compile_template_params(document: ParamsDocument, compiled_guard: CompiledGuard) -> type[TemplateParamsBase]:
    field_definitions = {spec.name: _field_definition(spec) for spec in document.fields}
    dynamic_base = create_model(
        "_DynamicTemplateParamsBase",
        __base__=TemplateParamsBase,
        **field_definitions,
    )

    class DynamicTemplateParams(dynamic_base):
        @model_validator(mode="after")
        def _check_guard(self):
            result = compiled_guard.check(self.model_dump())
            if not result.passed:
                failed = next(r for r in result.predicate_results if not r.passed)
                raise ValueError(
                    f"guard predicate failed: {failed.predicate_type} ({failed.detail})"
                )
            self.__dict__["_guard_result"] = result
            return self

        def guard_result(self) -> GuardResult:
            return self.__dict__["_guard_result"]

    DynamicTemplateParams.__name__ = "DynamicTemplateParams"
    return DynamicTemplateParams
