"""The client-IP middleware, and the server flag its setting depends on.

`TRUST_FORWARDED_FOR=false` is only meaningful if `request.client.host` is the
real socket peer. uvicorn's `ProxyHeadersMiddleware` defaults ON and rewrites
`scope["client"]` from `X-Forwarded-For` before any app middleware runs, so
with it enabled the "untrusted" fallback returns the forwarded value and the
setting silently does nothing. Both halves are tested here: the middleware's
own contract, and the `--no-proxy-headers` flag that makes it reachable.
"""

import os
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


# --------------------------------------------------------------------------
# `--no-proxy-headers` must be on EVERY uvicorn launch command in the repo --
# scripts, compose files, the Dockerfile, and any doc a developer copies from.
# Miss one and `ClientIPMiddleware` is not the component deciding whether
# `X-Forwarded-For` may name the client; uvicorn is, before it ever runs.
#
# Deliberately a repo scan rather than a list of known files. A list is an
# inclusion filter: it fails open for the next launch site someone adds, which
# is exactly how the README command was missed. Scanning defaults to deny, so a
# new one has to opt IN to being correct.

#: Pruned during the walk. Build output, dependencies and VCS internals hold no
#: launch command anyone runs, and node_modules alone makes an unpruned walk
#: take orders of magnitude longer.
_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".worktrees", ".vite", "dist", "build", "htmlcov", "media", "var",
    "playwright-report", "test-results", "blob-report", ".impeccable",
})

#: Binary assets: reading them wastes time and can only produce mojibake.
_SKIP_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".woff", ".woff2",
    ".ttf", ".otf", ".pptx", ".pdf", ".pyc", ".db", ".sqlite", ".ico", ".zip",
})

_THIS_FILE = Path(__file__).resolve()


def _uvicorn_launch_lines() -> list[tuple[str, int, str]]:
    """Every line in the repo that starts this app under uvicorn."""
    found: list[tuple[str, int, str]] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() in _SKIP_SUFFIXES:
                continue
            if path.resolve() == _THIS_FILE:
                # This file spells out the pattern it searches for, so it would
                # match itself on every run.
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if "uvicorn" in line and "app.main:app" in line:
                    relative = path.relative_to(REPO_ROOT).as_posix()
                    found.append((relative, number, line.strip()))
    return found


requires_repo_root = pytest.mark.skipif(
    not (REPO_ROOT / "Dockerfile.backend").exists(),
    reason="repo root not checked out (the backend image copies only backend/)",
)


@requires_repo_root
def test_the_scan_actually_finds_launch_commands():
    """Guards the guard.

    If the walk breaks -- wrong root, over-eager prune, changed invocation
    style -- the check below would find nothing to object to and pass forever.
    """
    assert _uvicorn_launch_lines(), (
        "found no uvicorn launch command anywhere in the repo; the scan in "
        "this module is broken, not the repo"
    )


@requires_repo_root
def test_every_uvicorn_launch_site_disables_proxy_header_processing():
    offenders = [
        f"  {relative}:{number}\n      {line}"
        for relative, number, line in _uvicorn_launch_lines()
        if "--no-proxy-headers" not in line
    ]
    assert not offenders, (
        "these start uvicorn without --no-proxy-headers, so uvicorn rewrites "
        "scope['client'] from X-Forwarded-For before ClientIPMiddleware runs "
        "and TRUST_FORWARDED_FOR=false cannot take effect:\n"
        + "\n".join(offenders)
    )
