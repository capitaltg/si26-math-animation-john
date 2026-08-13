"""Bedrock rate-limit + cost guard primitives.

Three-layer defense for the public demo:

* L1 lives in nginx (per-IP HTTP `limit_req`); no code here.
* L2 caps Bedrock calls per client IP per rolling hour.
* L3 caps Bedrock calls globally per UTC day.

Both L2 and L3 are Redis-backed counters that TTL themselves. When
`REDIS_URL` is unset (local dev, tests) the checks degrade to no-ops so the
same code path works with or without Redis. `BEDROCK_DISABLED=1` short-circuits
every call regardless of Redis state.

The client IP is threaded from the request layer through a `ContextVar` so
that background tasks and worker jobs — which invoke Bedrock outside a
request scope — count against the global budget without needing an IP.
"""

from __future__ import annotations

import contextvars
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

#: Set by the FastAPI middleware. `None` for background workers / tests.
client_ip_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "client_ip", default=None
)


class BedrockDisabled(RuntimeError):
    """Master kill switch is on."""


@dataclass
class BedrockQuotaExceeded(RuntimeError):
    """A quota window has been exhausted."""

    scope: str            # "global" | "ip"
    limit: int
    retry_after_seconds: int

    def __str__(self) -> str:  # noqa: D401
        return (
            f"Bedrock {self.scope} quota exhausted "
            f"(limit={self.limit}, retry_after={self.retry_after_seconds}s)"
        )


@lru_cache
def _redis_client():
    settings = get_settings()
    if not settings.redis_url:
        return None
    try:
        import redis  # imported lazily so local dev without the wheel still works

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:
        logger.exception("Redis unavailable; Bedrock rate limits disabled")
        return None


def _incr_with_ttl(key: str, ttl_seconds: int) -> int:
    """Atomic INCR + EXPIRE. Returns new counter value, or 0 if Redis is off."""
    client = _redis_client()
    if client is None:
        return 0
    try:
        pipe = client.pipeline()
        pipe.incr(key, 1)
        pipe.expire(key, ttl_seconds, nx=True)
        count, _ = pipe.execute()
        return int(count)
    except Exception:
        logger.exception("Redis INCR failed for %s; skipping guard", key)
        return 0


def _seconds_until_utc_day_end() -> int:
    now = int(time.time())
    return 86_400 - (now % 86_400)


def _seconds_until_hour_end() -> int:
    now = int(time.time())
    return 3600 - (now % 3600)


def enforce_bedrock_quota() -> None:
    """Run all three code-level guards. Raises on breach.

    Must be called at the single Bedrock choke point (see
    `app.pipeline.bedrock_client.call_with_tool`).
    """
    settings = get_settings()

    # L0 — kill switch.
    if settings.bedrock_disabled:
        raise BedrockDisabled("Bedrock calls are administratively disabled")

    # L3 — global daily cap.
    if settings.bedrock_daily_call_cap > 0:
        day_bucket = time.strftime("%Y-%m-%d", time.gmtime())
        key = f"bedrock:global:{day_bucket}"
        count = _incr_with_ttl(key, _seconds_until_utc_day_end() + 60)
        if count and count > settings.bedrock_daily_call_cap:
            raise BedrockQuotaExceeded(
                scope="global",
                limit=settings.bedrock_daily_call_cap,
                retry_after_seconds=_seconds_until_utc_day_end(),
            )

    # L2 — per-IP hourly cap. Only enforced when the request layer supplied an IP.
    if settings.bedrock_per_ip_hourly_cap > 0:
        ip = client_ip_var.get()
        if ip:
            hour_bucket = time.strftime("%Y-%m-%dT%H", time.gmtime())
            key = f"bedrock:ip:{ip}:{hour_bucket}"
            count = _incr_with_ttl(key, _seconds_until_hour_end() + 60)
            if count and count > settings.bedrock_per_ip_hourly_cap:
                raise BedrockQuotaExceeded(
                    scope="ip",
                    limit=settings.bedrock_per_ip_hourly_cap,
                    retry_after_seconds=_seconds_until_hour_end(),
                )
