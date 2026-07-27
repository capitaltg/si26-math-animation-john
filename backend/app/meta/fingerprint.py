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


from datetime import datetime

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.meta.models import FingerprintTag
from app.pipeline.bedrock_client import call_with_tool

_TAGGER_SYSTEM_PROMPT = (
    "You tag a single K-8 math problem with a bounded structural fingerprint by "
    "calling the fingerprint tool. Choose the closest enum value for each field. "
    "Do not invent fields, do not return prose, and never emit code."
)


def tag_candidate(source_excerpt: str, grade_level: int) -> Fingerprint:
    _, raw = call_with_tool(
        system_prompt=_TAGGER_SYSTEM_PROMPT,
        user_message=f"grade_level={grade_level}\n\n{source_excerpt}",
        tools=[{"name": "fingerprint", "schema": FINGERPRINT_TOOL_SCHEMA}],
    )
    return Fingerprint.model_validate(raw)


def store_tag(
    session: Session,
    *,
    observation_id: str,
    fingerprint: "Fingerprint",
    tagger_model_id: str,
    tagger_prompt_version: str,
    new_id: str,
    created_at: datetime,
) -> FingerprintTag:
    session.execute(
        update(FingerprintTag)
        .where(FingerprintTag.observation_id == observation_id, FingerprintTag.is_current.is_(True))
        .values(is_current=False)
    )
    # Delete any existing tag with the same fingerprint_version to enforce unique constraint
    session.execute(
        delete(FingerprintTag).where(
            FingerprintTag.observation_id == observation_id,
            FingerprintTag.fingerprint_version == fingerprint.fingerprint_version,
        )
    )
    tag = FingerprintTag(
        id=new_id,
        observation_id=observation_id,
        fingerprint_version=fingerprint.fingerprint_version,
        fingerprint_json=fingerprint.model_dump_json(),
        fingerprint_key=canonical_fingerprint_key(fingerprint),
        tagger_model_id=tagger_model_id,
        tagger_prompt_version=tagger_prompt_version,
        is_current=True,
        created_at=created_at,
    )
    session.add(tag)
    return tag
