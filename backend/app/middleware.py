"""ASGI middleware — planting request-scoped context for downstream code.

Currently only sets the client-IP ContextVar consumed by
`app.quota.enforce_bedrock_quota` so that L2 (per-IP Bedrock cap) can
attribute calls to the caller behind nginx's `X-Forwarded-For`.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import get_settings
from app.quota import client_ip_var


class ClientIPMiddleware(BaseHTTPMiddleware):
    """Extract the caller IP and expose it via `client_ip_var`.

    Uses the left-most entry of `X-Forwarded-For` when nginx has set it
    (production topology), and falls back to `request.client.host` otherwise
    (local dev, direct hits). Only nginx is trusted to set XFF; the upstream
    LB/proxy chain is assumed to be one hop.

    That trust is what `settings.trust_forwarded_for` makes explicit. It holds
    for the shipped topology because nginx sets `X-Forwarded-For $remote_addr`
    (not `$proxy_add_x_forwarded_for`) and Caddy overwrites it with
    `{remote_host}`, so a client-supplied header never reaches here. Deploy the
    backend without that edge and the header is caller-controlled: turn the
    setting off so the socket peer is used instead.

    Turning it off only works because uvicorn is started with
    `--no-proxy-headers` at every launch site (Dockerfile.backend,
    docker-compose.dev.yml, scripts/run-backend.sh, playwright.config.js).
    uvicorn's own ProxyHeadersMiddleware defaults ON and rewrites
    `scope["client"]` from `X-Forwarded-For` before this middleware runs
    whenever the peer is in `forwarded_allow_ips` (default 127.0.0.1) -- which
    would make the `request.client.host` fallback below return the forwarded
    value, silently defeating the setting. `tests/test_middleware.py` guards
    the flag.
    """

    async def dispatch(self, request: Request, call_next):
        ip = _extract_client_ip(request)
        token = client_ip_var.set(ip)
        try:
            return await call_next(request)
        finally:
            client_ip_var.reset(token)


def _extract_client_ip(request: Request) -> str | None:
    if get_settings().trust_forwarded_for:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",", 1)[0].strip()
            if first:
                return first
    if request.client:
        return request.client.host
    return None
