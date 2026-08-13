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

Order matters: L2 (per-IP) is checked and incremented BEFORE L3 (global) so
that a caller rejected by their per-IP quota does not also consume from the
global daily budget.

Fail-closed policy: when any cap is configured (> 0) and Redis is unreachable,
`enforce_bedrock_quota` raises `BedrockGuardUnavailable`. Silently letting
calls through when the guard is down would defeat the whole point in
production. Local dev / tests configure both caps to 0 (the default), which
keeps behavior fail-open.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

#: Set by the FastAPI middleware. `None` for background workers / tests.
client_ip_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "client_ip", default=None
)


class BedrockDisabled(RuntimeError):
    """Master kill switch is on."""


class BedrockGuardUnavailable(RuntimeError):
    """Redis-backed guard cannot reach Redis and a cap is configured."""


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


# Redis client cache with a retry-on-failure lifecycle. Unlike lru_cache we
# never lock in a `None` result: a transient Redis outage during boot must not
# permanently disable both cost guards until the process is restarted.
_redis_lock = threading.Lock()
_redis_state: dict = {"url": None, "client": None}


def _redis_client():
    settings = get_settings()
    if not settings.redis_url:
        return None
    with _redis_lock:
        # Rebuild if the URL changed (mainly a test-time concern).
        if _redis_state["url"] != settings.redis_url:
            _redis_state.update(url=settings.redis_url, client=None)
        if _redis_state["client"] is not None:
            return _redis_state["client"]
        try:
            import redis  # imported lazily so local dev without the wheel still works

            client = redis.Redis.from_url(
                settings.redis_url, decode_responses=True, socket_timeout=2
            )
            client.ping()
            _redis_state["client"] = client
            return client
        except Exception:
            logger.exception("Redis unavailable; will retry on next check")
            return None


def _incr_with_ttl(key: str, ttl_seconds: int) -> Optional[int]:
    """Atomic INCR + EXPIRE. Returns new counter value, or None if Redis is down."""
    client = _redis_client()
    if client is None:
        return None
    try:
        pipe = client.pipeline()
        pipe.incr(key, 1)
        pipe.expire(key, ttl_seconds, nx=True)
        count, _ = pipe.execute()
        return int(count)
    except Exception:
        logger.exception("Redis INCR failed for %s", key)
        with _redis_lock:
            _redis_state["client"] = None  # force reconnect on next attempt
        return None


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

    ip_cap = settings.bedrock_per_ip_hourly_cap
    global_cap = settings.bedrock_daily_call_cap
    any_cap_configured = ip_cap > 0 or global_cap > 0

    # L2 — per-IP hourly cap. Runs FIRST so an IP-rejected call does not
    # consume the global bucket. Only enforced when the request layer supplied
    # an IP (background workers count only against the global cap).
    if ip_cap > 0:
        ip = client_ip_var.get()
        if ip:
            hour_bucket = time.strftime("%Y-%m-%dT%H", time.gmtime())
            key = f"bedrock:ip:{ip}:{hour_bucket}"
            count = _incr_with_ttl(key, _seconds_until_hour_end() + 60)
            if count is None:
                raise BedrockGuardUnavailable(
                    "Rate-limit backend unreachable; refusing Bedrock call"
                )
            if count > ip_cap:
                raise BedrockQuotaExceeded(
                    scope="ip",
                    limit=ip_cap,
                    retry_after_seconds=_seconds_until_hour_end(),
                )

    # L3 — global daily cap. Runs AFTER L2 so per-IP rejects don't burn budget.
    if global_cap > 0:
        day_bucket = time.strftime("%Y-%m-%d", time.gmtime())
        key = f"bedrock:global:{day_bucket}"
        count = _incr_with_ttl(key, _seconds_until_utc_day_end() + 60)
        if count is None:
            raise BedrockGuardUnavailable(
                "Rate-limit backend unreachable; refusing Bedrock call"
            )
        if count > global_cap:
            raise BedrockQuotaExceeded(
                scope="global",
                limit=global_cap,
                retry_after_seconds=_seconds_until_utc_day_end(),
            )

    # Any-cap sentinel: if the operator set neither cap, the guard is entirely
    # opt-out and we don't need Redis. That's fine — nothing else to do.
    _ = any_cap_configured
