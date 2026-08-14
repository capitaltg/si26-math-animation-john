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

    # Optional Postgres/SQLite DSN. When unset, falls back to sqlite at
    # `meta_db_path` so local dev keeps working without Docker.
    database_url: str | None = None
    # Redis DSN. When unset, Bedrock rate limiting degrades to no-op so local
    # dev / tests without Redis still function; the demo compose always sets it.
    redis_url: str | None = None

    # Bedrock spend guards. See app/pipeline/bedrock_client.py.
    #: Master kill switch. Any Bedrock call raises BedrockDisabled when true.
    bedrock_disabled: bool = False
    #: Global calls per UTC day allowed before returning 429. 0 disables L3.
    bedrock_daily_call_cap: int = 0
    #: Per-client-IP calls per rolling hour. 0 disables L2.
    bedrock_per_ip_hourly_cap: int = 0

    # Media volume ceiling — sum of all clips + thumbnails across sessions.
    # 0 disables. Sweep runs on startup and every `media_sweep_interval_seconds`.
    media_max_bytes: int = 0
    media_sweep_interval_seconds: int = 300

    # Comma-separated CORS origins. Local dev default keeps Vite on :5173.
    # In prod, same-origin via nginx means CORS is optional; leave narrow.
    # `*` is rejected — see `reject_wildcard_cors_origin`.
    cors_allow_origins: str = "http://localhost:5173"

    #: Whether an inbound `X-Forwarded-For` may name the client. True suits the
    #: shipped topology, where nginx (and Caddy in the TLS overlay) overwrite
    #: the header with the connecting peer, so a client-supplied value never
    #: survives to the app. Set false when the backend is reachable without
    #: that edge in front, so `enforce_bedrock_quota` keys the per-IP cap off
    #: the real socket instead of a header the caller controls.
    #:
    #: Depends on uvicorn running with `--no-proxy-headers`; see
    #: `app.middleware.ClientIPMiddleware`.
    trust_forwarded_for: bool = True

    # Meta-template generation is opt-in.
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
    #: Whether a teacher approving their own draft publishes it to every
    #: session on this box (ownerless row) or only to their own.
    #:
    #: True is the demo behaviour: the approved template survives the
    #: approver's session being evicted and is visible to anyone else on the
    #: box. It also means a caller holding nothing but an anonymous session
    #: cookie reaches the same shared publication that every route in
    #: `review_api` gates behind `meta_reviewer_token`. Set false to keep
    #: teacher approvals private to the approving session; the token-gated
    #: `POST /meta/versions/{id}/promote` is then the only way to share one.
    meta_teacher_publish_shared: bool = True

    @field_validator("cors_allow_origins", mode="after")
    @classmethod
    def reject_wildcard_cors_origin(cls, value: str) -> str:
        # CORSMiddleware is mounted with allow_credentials=True (app/main.py),
        # and Starlette answers a credentialed request under a "*" allow-list
        # by reflecting the caller's own Origin back. That would let any site
        # read this API with the visitor's session cookie attached, which is
        # exactly what the narrow list exists to prevent. Fail at boot with a
        # readable message rather than serve that combination.
        if any(origin.strip() == "*" for origin in value.split(",")):
            raise ValueError(
                "CORS_ALLOW_ORIGINS cannot contain '*' because the API allows "
                "credentials; list the exact origins instead"
            )
        return value

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
