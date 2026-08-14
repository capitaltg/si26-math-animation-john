"""The client-IP middleware, and the server flag its setting depends on.

`TRUST_FORWARDED_FOR=false` is only meaningful if `request.client.host` is the
real socket peer. uvicorn's `ProxyHeadersMiddleware` defaults ON and rewrites
`scope["client"]` from `X-Forwarded-For` before any app middleware runs, so
with it enabled the "untrusted" fallback returns the forwarded value and the
setting silently does nothing. Both halves are tested here: the middleware's
own contract, and the `--no-proxy-headers` flag that makes it reachable.
"""

from pathlib import Path

import pytest
from starlette.requests import Request

from app.config import get_settings
from app.middleware import _extract_client_ip

REPO_ROOT = Path(__file__).resolve().parents[2]

SPOOFED = "203.0.113.9"
REAL_PEER = "10.0.0.7"


def _request(*, peer: str | None, xff: str | None) -> Request:
    headers = [(b"host", b"localhost")]
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "http",
            "headers": headers,
            "client": (peer, 12345) if peer is not None else None,
        }
    )


def test_forwarded_for_names_the_client_when_trusted(monkeypatch):
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
    get_settings.cache_clear()
    assert _extract_client_ip(_request(peer=REAL_PEER, xff=SPOOFED)) == SPOOFED


def test_forwarded_for_is_ignored_when_not_trusted(monkeypatch):
    """The whole point of the setting: the header must not win."""
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "false")
    get_settings.cache_clear()
    assert _extract_client_ip(_request(peer=REAL_PEER, xff=SPOOFED)) == REAL_PEER


def test_socket_peer_is_used_when_no_forwarded_header_is_present(monkeypatch):
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
    get_settings.cache_clear()
    assert _extract_client_ip(_request(peer=REAL_PEER, xff=None)) == REAL_PEER


def test_a_blank_forwarded_header_falls_back_to_the_socket_peer(monkeypatch):
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
    get_settings.cache_clear()
    assert _extract_client_ip(_request(peer=REAL_PEER, xff="  ")) == REAL_PEER


def test_missing_client_yields_none(monkeypatch):
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "false")
    get_settings.cache_clear()
    assert _extract_client_ip(_request(peer=None, xff=SPOOFED)) is None


#: Every place this app is started with uvicorn. `--no-proxy-headers` has to be
#: on all of them, or `ClientIPMiddleware` is not the component that decides
#: whether `X-Forwarded-For` may name the client -- uvicorn is, before it runs.
_UVICORN_LAUNCH_SITES = (
    "Dockerfile.backend",
    "docker-compose.dev.yml",
    "scripts/run-backend.sh",
    "frontend/playwright.config.js",
)


@pytest.mark.skipif(
    not (REPO_ROOT / "Dockerfile.backend").exists(),
    reason="repo root not checked out (the backend image copies only backend/)",
)
@pytest.mark.parametrize("relative_path", _UVICORN_LAUNCH_SITES)
def test_uvicorn_is_launched_without_proxy_header_processing(relative_path):
    lines = (REPO_ROOT / relative_path).read_text(encoding="utf-8").splitlines()
    launches = [
        line for line in lines if "uvicorn" in line and "app.main:app" in line
    ]
    assert launches, f"no uvicorn launch line found in {relative_path}"
    for line in launches:
        assert "--no-proxy-headers" in line, (
            f"{relative_path} starts uvicorn without --no-proxy-headers, so "
            f"uvicorn rewrites scope['client'] from X-Forwarded-For before "
            f"ClientIPMiddleware runs and TRUST_FORWARDED_FOR=false cannot "
            f"take effect:\n    {line.strip()}"
        )
