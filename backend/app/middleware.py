"""ASGI middleware — planting request-scoped context for downstream code.

Currently only sets the client-IP ContextVar consumed by
`app.quota.enforce_bedrock_quota` so that L2 (per-IP Bedrock cap) can
attribute calls to the caller behind nginx's `X-Forwarded-For`.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.quota import client_ip_var


class ClientIPMiddleware(BaseHTTPMiddleware):
    """Extract the caller IP and expose it via `client_ip_var`.

    Uses the left-most entry of `X-Forwarded-For` when nginx has set it
    (production topology), and falls back to `request.client.host` otherwise
    (local dev, direct hits). Only nginx is trusted to set XFF; the upstream
    LB/proxy chain is assumed to be one hop.
    """

    async def dispatch(self, request: Request, call_next):
        ip = _extract_client_ip(request)
        token = client_ip_var.set(ip)
        try:
            return await call_next(request)
        finally:
            client_ip_var.reset(token)


def _extract_client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    if request.client:
        return request.client.host
    return None
