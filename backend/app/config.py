from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", extra="ignore")

    aws_region: str = "us-east-1"
    bedrock_model_id: str = "global.anthropic.claude-sonnet-4-6"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    session_cookie_secure: bool = False

    # meta-template system (Phase 1) — all disabled by default
    meta_templates_enabled: bool = False
    meta_codegen_enabled: bool = False
    meta_db_path: Path = BACKEND_ROOT / "var" / "meta.db"
    fingerprint_observation_threshold: int = 5
    meta_required_fixture_count: int = Field(default=5, ge=1)
    fingerprint_tagger_prompt_version: str = "v1"
    fingerprint_tagger_max_attempts: int = 2
    fingerprint_tagger_backoff_seconds: float = 1.0
    job_lease_seconds: int = 300
    job_backoff_base_seconds: int = 60
    job_max_attempts: int = 5
    meta_artifact_root: Path = BACKEND_ROOT / "var" / "meta_artifacts"
    meta_draft_generation_max_attempts: int = Field(default=3, ge=1)
    meta_draft_max_refinements: int = 5
    meta_approval_enabled: bool = False
    meta_dynamic_classifier_enabled: bool = False
    meta_reviewer_token: str | None = None

    @field_validator("meta_db_path", mode="after")
    @classmethod
    def resolve_meta_db_path(cls, value: Path) -> Path:
        path = value.expanduser()
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path.resolve()

    @field_validator("meta_artifact_root", mode="after")
    @classmethod
    def resolve_meta_artifact_root(cls, value: Path) -> Path:
        path = value.expanduser()
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
