import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName
from app.pipeline.classification import ClassificationResult, TemplateOption
from app.render.full_render import RenderTimeout
from app.routes import store
from app.templates.registry import static_ref


def _new_client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _session_for(client: TestClient):
    candidate = Candidate(
        candidate_id="c1",
        source_excerpt="Sarah has 4 apples and buys 3 more.",
        slide_index=0,
        one_line_summary="4 + 3",
    )
    session = store.create([candidate])
    session.options[candidate.candidate_id] = ClassificationResult(
        options=[
            TemplateOption(
                template=TemplateName.NUMBER_LINE,
                rationale="jump",
                version_id=static_ref(TemplateName.NUMBER_LINE).version_id,
            )
        ],
        grade_level=1,
        ambiguous=False,
    )
    client.cookies.set("session_id", session.session_id)
    return session


def _approved_scene(scene_id: str) -> Scene:
    return Scene(
        scene_id=scene_id,
        candidate_id="c1",
        template=static_ref(TemplateName.NUMBER_LINE),
        grade_level=1,
        params={"start": 4, "steps": [{"operation": "add", "amount": 3}]},
        status="approved",
    )


def _fake_render_ok(template, params, out):
    out.write_bytes(b"mp4")
    return out


def test_render_rejects_oversized_batch():
    client = _new_client()
    session = _session_for(client)
    for i in range(15):
        scene = _approved_scene(f"s{i}")
        session.scenes[scene.scene_id] = scene
        session.scene_order.append(scene.scene_id)

    with patch("app.routes.MAX_RENDER_BATCH", 12):
        resp = client.post("/render")

    assert resp.status_code == 400
    assert "cap of 12" in resp.json()["detail"]


def test_render_respects_whole_job_deadline():
    client = _new_client()
    session = _session_for(client)
    for i in range(3):
        scene = _approved_scene(f"s{i}")
        session.scenes[scene.scene_id] = scene
        session.scene_order.append(scene.scene_id)

    call_count = {"n": 0}

    def slow_render(template, params, out, **_):
        call_count["n"] += 1
        time.sleep(0.15)  # blow through the 0.1s budget mid-batch
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.RENDER_JOB_DEADLINE_SECONDS", 0.1), patch(
        "app.routes.render_scene_to_mp4", side_effect=slow_render
    ):
        resp = client.post("/render")

    assert resp.status_code == 200
    statuses = [c["status"] for c in resp.json()["clips"]]
    assert statuses[0] == "approved"
    assert statuses[1:] == ["timeout", "timeout"]
    assert call_count["n"] == 1


def test_render_dedupes_concurrent_scene():
    client = _new_client()
    session = _session_for(client)
    scene = _approved_scene("s1")
    session.scenes[scene.scene_id] = scene
    session.scene_order.append(scene.scene_id)
    session.rendering_scene_ids.add("s1")  # simulate an in-flight render

    resp = client.post("/render")

    assert resp.status_code == 409
    assert "s1" in resp.json()["detail"]


def test_render_timeout_maps_to_timeout_status():
    client = _new_client()
    session = _session_for(client)
    scene = _approved_scene("s1")
    session.scenes[scene.scene_id] = scene
    session.scene_order.append(scene.scene_id)

    def timeout_render(template, params, out, **_):
        raise RenderTimeout("simulated")

    with patch("app.routes.render_scene_to_mp4", side_effect=timeout_render):
        resp = client.post("/render")

    assert resp.status_code == 200
    clip = resp.json()["clips"][0]
    assert clip["status"] == "timeout"
    assert clip["clip_url"] is None


def test_render_reuses_cached_clip_on_identical_params():
    client = _new_client()
    session = _session_for(client)
    scene = _approved_scene("s1")
    session.scenes[scene.scene_id] = scene
    session.scene_order.append(scene.scene_id)

    calls = {"n": 0}

    def counting_render(template, params, out, **_):
        calls["n"] += 1
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.render_scene_to_mp4", side_effect=counting_render):
        first = client.post("/render")
        second = client.post("/render")

    assert first.status_code == 200 and second.status_code == 200
    assert calls["n"] == 1  # second call short-circuited via hash reuse
    assert first.json()["clips"][0]["clip_url"] == second.json()["clips"][0]["clip_url"]


def test_render_drops_clip_when_scene_edited_mid_render():
    """A render that finishes after an edit lands must NOT publish its clip.

    The scene's revision has advanced past what we captured at snapshot,
    so returning "approved" for the just-finished (now-stale) params would
    hand the teacher back a clip that no longer matches the storyboard.
    """
    client = _new_client()
    session = _session_for(client)
    scene = _approved_scene("s1")
    session.scenes[scene.scene_id] = scene
    session.scene_order.append(scene.scene_id)

    def race_render(template, params, out, **_):
        # Simulate an edit that landed while the render was running: bump the
        # revision so approved_revision no longer matches, moving the scene
        # out of the `_is_render_ready` state.
        current = session.scenes["s1"]
        session.scenes["s1"] = current.model_copy(
            update={"revision": current.revision + 1}
        )
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.render_scene_to_mp4", side_effect=race_render):
        resp = client.post("/render")

    assert resp.status_code == 200
    clip = resp.json()["clips"][0]
    assert clip["status"] == "error"
    assert clip["clip_url"] is None
    # No cached clip should be recorded for a discarded render.
    assert "s1" not in session.scene_clip_id
    assert session.scenes["s1"].rendered_params_hash is None


def test_render_drops_clip_when_scene_rejected_mid_render():
    client = _new_client()
    session = _session_for(client)
    scene = _approved_scene("s1")
    session.scenes[scene.scene_id] = scene
    session.scene_order.append(scene.scene_id)

    def reject_mid_render(template, params, out, **_):
        current = session.scenes["s1"]
        session.scenes["s1"] = current.model_copy(update={"status": "rejected"})
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.render_scene_to_mp4", side_effect=reject_mid_render):
        resp = client.post("/render")

    assert resp.status_code == 200
    clip = resp.json()["clips"][0]
    assert clip["status"] == "error"
    assert clip["clip_url"] is None


def test_render_bypasses_cache_when_params_change():
    client = _new_client()
    session = _session_for(client)
    scene = _approved_scene("s1")
    session.scenes[scene.scene_id] = scene
    session.scene_order.append(scene.scene_id)

    calls = {"n": 0}

    def counting_render(template, params, out, **_):
        calls["n"] += 1
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.render_scene_to_mp4", side_effect=counting_render):
        client.post("/render")
        # Rewrite params in place (simulates an edit that landed and got re-approved
        # to the same revision the render captured; hash must still bust the cache).
        updated = session.scenes["s1"].model_copy(
            update={"params": {"start": 9, "steps": [{"operation": "add", "amount": 1}]}}
        )
        session.scenes["s1"] = updated
        client.post("/render")

    assert calls["n"] == 2
