"""Contract: every user-editable field on a scene revokes its approval.

An approved scene that changes underneath the approval must not render:
the approval was granted for a specific content revision, and any real
edit invalidates it. Per-field tests in tests/test_routes.py cover
individual cases (params change, grade_level change). What binds them is
a single-place spec: **every field on `SceneEditRequest`** — the surface
a browser can PATCH — must trigger revocation.

If a field is added to `SceneEditRequest` without adding a revocation
case here, the enumeration guard fails and the author has to decide.
"""

from unittest.mock import patch

import pytest

from app.routes import SceneEditRequest


# The single source of truth: the request model's field names. Adding a
# field to `SceneEditRequest` grows this set automatically and the
# enumeration guard trips until the parametrized cases below cover it.
USER_EDITABLE_FIELDS: frozenset[str] = frozenset(SceneEditRequest.model_fields)


# Per-field revocation cases. Each entry is (field_name, body, patches_needed).
# The body must actually differ from the seeded scene — a value equal to the
# current one is a no-op edit that (correctly) does NOT revoke.
REVOKING_EDITS: list[tuple[str, dict, list[str]]] = [
    (
        "params",
        {"params": {"start": 42, "steps": [{"operation": "add", "amount": 9}]}},
        # PATCH re-renders the thumbnail; patch it out so the test doesn't
        # require a real Manim install.
        ["app.routes.render_scene_thumbnail"],
    ),
    (
        "grade_level",
        {"grade_level": 5},  # seeded scene has grade_level=1
        [],
    ),
]


def test_every_editable_field_has_a_revocation_case():
    """Guard: every field on `SceneEditRequest` appears in `REVOKING_EDITS`.

    A new user-editable field added without a case here would silently
    escape revocation coverage. The test fails until the case is added.
    """
    covered = {field for field, _body, _patches in REVOKING_EDITS}
    missing = USER_EDITABLE_FIELDS - covered
    stray = covered - USER_EDITABLE_FIELDS

    assert not missing, (
        f"SceneEditRequest gained field(s) with no revocation case: {sorted(missing)}. "
        f"Add an entry to REVOKING_EDITS."
    )
    assert not stray, (
        f"REVOKING_EDITS covers field(s) that no longer exist on SceneEditRequest: "
        f"{sorted(stray)}. Remove them."
    )


@pytest.mark.parametrize(
    "field,body,patches",
    REVOKING_EDITS,
    ids=[case[0] for case in REVOKING_EDITS],
)
def test_editing_a_field_revokes_approval_and_blocks_render(tmp_path, field, body, patches):
    """Post-approval edit → status back to pending_review, render refuses.

    Verifies both halves of the revocation contract in one flow:
      1. PATCH marks the scene `pending_review` so the UI shows it as
         needing re-review.
      2. POST /render refuses because no scene is approved anymore
         (defense: /render short-circuits when there is nothing to render).
    """
    from tests.test_routes import (
        _client,
        _number_line_scene,
        _seed_scene,
        _upload_candidate,
    )

    client = _client()
    _upload_candidate(client)
    approved = _number_line_scene(tmp_path).model_copy(
        update={"status": "approved", "approved_revision": 0}
    )
    _seed_scene(client, approved)

    # Apply the field-specific patches (e.g. avoid a real thumbnail render).
    patchers = [patch(target) for target in patches]
    for p in patchers:
        p.start()
    try:
        resp = client.patch("/storyboard/s1", json=body)
    finally:
        for p in patchers:
            p.stop()

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["status"] == "pending_review", (
        f"Editing {field!r} must revoke approval, but status was {payload['status']!r}."
    )

    def _fake_render(_template, _params, out, **_kwargs):
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.render_scene_to_mp4", side_effect=_fake_render):
        render_resp = client.post("/render")

    assert render_resp.status_code == 400, (
        f"Editing {field!r} must leave nothing approved to render, but /render "
        f"returned {render_resp.status_code}: {render_resp.text}"
    )
