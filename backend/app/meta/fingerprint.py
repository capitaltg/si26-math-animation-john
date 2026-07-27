from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FINGERPRINT_VERSION = 1

_KEY_FIELD_ORDER = (
    "fingerprint_version",
    "operation_family",
    "representation_family",
    "number_domain",
    "operand_arity",
    "step_count",
    "grade_band",
)


class Fingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint_version: Literal[1]
    operation_family: Literal[
        "compare", "compose", "decompose", "transform", "measure", "pattern", "other"
    ]
    representation_family: Literal[
        "grid", "bar", "set", "shape", "table", "clock", "money", "coordinate", "other"
    ]
    number_domain: Literal["whole", "integer", "decimal", "fraction", "mixed"]
    operand_arity: int = Field(ge=1, le=10)
    step_count: int = Field(ge=1, le=10)
    grade_band: Literal["K-2", "3-5", "6-8"]


FINGERPRINT_TOOL_SCHEMA: dict = Fingerprint.model_json_schema()


def canonical_fingerprint_key(fp: Fingerprint) -> str:
    data = fp.model_dump()
    return "|".join(f"{field}={data[field]}" for field in _KEY_FIELD_ORDER)
