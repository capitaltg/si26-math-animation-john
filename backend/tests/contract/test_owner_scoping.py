"""Contract: every registered route is categorized as owner-scoped or not.

Per-endpoint behavior tests live with each router (see
tests/meta/test_teacher_api.py for the meta draft owner checks). What binds
them together is a single-place spec that names which routes access shared
per-owner state. A route added later that touches such state without being
added here trips the guard — the author has to decide.

Two tables cover the split:

- OWNER_SCOPED_ROUTES: reads or mutates state stored in a registry or db
  table that is keyed by owner, and where the owner check is the only thing
  keeping one session out of another's data. These must 404 for the wrong
  owner (never 200, never 403 — 403 leaks existence).
- NOT_OWNER_SCOPED_ROUTES: everything else. Includes routes that use the
  caller's own session dict as the boundary (segregation is architectural,
  cross-session access is impossible by construction), routes authenticated
  by the admin reviewer bearer token instead of the session cookie, and
  session-bootstrap / stateless routes.

Adding a route means picking one table. Leaving it out fails the test.
"""

import pytest
from fastapi.routing import APIRoute

# --- The spec ---------------------------------------------------------------

OWNER_SCOPED_ROUTES: frozenset[tuple[str, str]] = frozenset({
    # Meta teacher drafts — job.owner_session_id gates access via _owned_draft.
    ("GET",  "/meta/my/drafts/{draft_id}"),
    ("GET",  "/meta/my/drafts/{draft_id}/preview"),
    ("POST", "/meta/my/drafts/{draft_id}/approve"),
    ("POST", "/meta/my/drafts/{draft_id}/reject"),
    # Artifact registries — clip/thumbnail entries carry a session_id and
    # store.get_clip / store.get_thumbnail refuse when it doesn't match.
    # Currently landing on fix/artifact-owner-check (PR pending merge for
    # issue #149); the entry stays here so that once merged, the actual
    # cross-session behavior can be locked in with a follow-up behavioral
    # smoke without renegotiating the contract.
    ("GET",  "/clips/{clip_id}"),
    ("GET",  "/thumbnails/{thumb_id}"),
})

NOT_OWNER_SCOPED_ROUTES: frozenset[tuple[str, str]] = frozenset({
    # Liveness probe for docker HEALTHCHECK / nginx depends_on. Constant
    # response, no state.
    ("GET", "/healthz"),
    # Session bootstrap or session-agnostic.
    ("POST", "/upload"),
    ("POST", "/options"),
    ("POST", "/render"),
    ("POST", "/storyboard"),
    ("POST", "/storyboard/chain"),
    # Storyboard scene mutations look up the scene via `session.scenes.get`,
    # a per-session dict. Cross-session access is impossible by construction:
    # session B's dict does not contain session A's scene_id, so the lookup
    # returns None and the handler 404s before any check runs.
    ("PATCH", "/storyboard/{scene_id}"),
    ("POST",  "/storyboard/{scene_id}/approve"),
    ("POST",  "/storyboard/{scene_id}/acknowledge-mismatch"),
    ("POST",  "/storyboard/{scene_id}/reject"),
    ("POST",  "/storyboard/{scene_id}/retry"),
    ("POST",  "/storyboard/{scene_id}/ungroup"),
    # Meta teacher — session-dict-scoped (`session.template_requests`).
    ("GET",    "/meta/my/capabilities"),
    ("POST",   "/meta/my/builds"),
    ("GET",    "/meta/my/builds"),
    ("DELETE", "/meta/my/builds/{candidate_id}"),
    # Meta admin — authenticated by META_REVIEWER_TOKEN, not the session
    # cookie. Owner-scoping is not the boundary here.
    ("GET",  "/meta/drafts"),
    ("GET",  "/meta/drafts/rejected_count"),
    ("GET",  "/meta/drafts/{draft_id}"),
    ("POST", "/meta/drafts/{draft_id}/approve"),
    ("POST", "/meta/drafts/{draft_id}/fixtures/{fixture_id}"),
    ("POST", "/meta/drafts/{draft_id}/reject"),
    ("POST", "/meta/drafts/{draft_id}/revalidate"),
    ("GET",  "/meta/jobs/{job_id}"),
    ("GET",  "/meta/preview/{artifact_hash}"),
    ("GET",  "/meta/versions"),
    ("POST", "/meta/versions/{version_id}/promote"),
})


# --- Enumeration ------------------------------------------------------------


def _walk(routes):
    """FastAPI `include_router` wraps its children in `_IncludedRouter`; the
    original nested `APIRoute`s live under `original_router.routes`. Fallback
    to `.routes` for anything else that exposes it."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes)
        elif hasattr(route, "routes"):
            yield from _walk(route.routes)


def _registered_routes(app) -> frozenset[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    for route in _walk(app.routes):
        for method in route.methods - {"HEAD", "OPTIONS"}:
            seen.add((method, route.path))
    return frozenset(seen)


# --- Fixture ----------------------------------------------------------------


@pytest.fixture
def enabled_app(tmp_path, monkeypatch):
    """Real app with every meta feature flag on so all meta routes register.

    Without the flags, `create_app` skips including the meta teacher and
    review routers — the contract test would then miss any meta routes and
    silently pass. Enabling everything is the safe default here.
    """
    from app.config import get_settings
    from app.meta import db

    engine = db.make_engine(tmp_path / "meta.db")
    db.create_all(engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    monkeypatch.setenv("META_APPROVAL_ENABLED", "1")
    monkeypatch.setenv("META_DYNAMIC_CLASSIFIER_ENABLED", "1")
    monkeypatch.setenv("META_REVIEWER_TOKEN", "test-token")
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    from app.main import create_app

    yield create_app()
    get_settings.cache_clear()


# --- The contract -----------------------------------------------------------


def test_every_registered_route_is_categorized(enabled_app):
    """A route must appear in exactly one of the two tables.

    Uncategorized route → someone added an endpoint and did not decide
    whether it touches per-owner shared state. Fail loudly so they do.

    Stale entry → route was removed or renamed and the spec here drifted.
    Fail so the spec stays a live document, not a dead artifact.
    """
    registered = _registered_routes(enabled_app)
    categorized = OWNER_SCOPED_ROUTES | NOT_OWNER_SCOPED_ROUTES

    uncategorized = registered - categorized
    stale = categorized - registered
    overlap = OWNER_SCOPED_ROUTES & NOT_OWNER_SCOPED_ROUTES

    assert not overlap, (
        "Routes listed in both OWNER_SCOPED_ROUTES and NOT_OWNER_SCOPED_ROUTES:\n"
        + "\n".join(f"  {method} {path}" for method, path in sorted(overlap))
    )
    assert not uncategorized, (
        "Routes registered but not categorized in this file:\n"
        + "\n".join(f"  {method} {path}" for method, path in sorted(uncategorized))
        + "\nAdd each to OWNER_SCOPED_ROUTES if it accesses per-owner shared\n"
        "state (e.g. a db row keyed by owner, or a shared registry), or to\n"
        "NOT_OWNER_SCOPED_ROUTES if it uses a session-dict, admin bearer\n"
        "token, or no per-owner state at all."
    )
    assert not stale, (
        "Routes in the contract tables but no longer registered:\n"
        + "\n".join(f"  {method} {path}" for method, path in sorted(stale))
        + "\nRemove or rename the entries in this file."
    )
