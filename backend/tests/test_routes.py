# backend/tests/test_routes.py
import io
from unittest.mock import patch

from botocore.exceptions import NoCredentialsError
from fastapi.testclient import TestClient
from pptx import Presentation


def _pptx_bytes(slide_count: int = 1) -> bytes:
    presentation = Presentation()
    layout = presentation.slide_layouts[1]
    for i in range(slide_count):
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = f"Slide {i}"
        slide.placeholders[1].text = "Sarah has 4 apples and buys 3 more."
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _client():
    from app.main import create_app

    return TestClient(create_app())


def _candidate(cid="c1"):
    from app.models.candidate import Candidate

    return Candidate(
        candidate_id=cid,
        source_excerpt="Sarah has 4 apples and buys 3 more.",
        slide_index=0,
        one_line_summary="Detected: 4 + 3",
    )


def _classification():
    from app.models.scene import TemplateName
    from app.pipeline.classification import ClassificationResult, TemplateOption

    return ClassificationResult(
        options=[
            TemplateOption(
                template=TemplateName.BALANCE_SCALE,
                rationale="shows the equation as a balance",
            ),
            TemplateOption(
                template=TemplateName.NUMBER_LINE,
                rationale="shows one forward jump",
            ),
            TemplateOption(
                template=TemplateName.TEXT_CARD,
                rationale="always-compatible fallback",
            ),
        ],
        grade_level=1,
        ambiguous=False,
    )


def _upload_candidate(client):
    return _upload_candidates(client, [_candidate()])


def _upload_candidates(client, candidates):
    with patch("app.routes.discover_candidates_for_document", return_value=candidates):
        return client.post(
            "/upload",
            files={
                "file": (
                    "deck.pptx",
                    _pptx_bytes(),
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        )


def _options_then(client):
    """Upload one candidate and cache its options; return the client."""
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})
    return client


def test_upload_rejects_non_pptx():
    client = _client()
    resp = client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert resp.status_code == 400


def test_upload_rejects_document_over_slide_cap():
    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[]):
        resp = client.post(
            "/upload",
            files={"file": ("big.pptx", _pptx_bytes(slide_count=51), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert resp.status_code == 400


def test_upload_rejects_oversized_file():
    from app.routes import MAX_UPLOAD_BYTES

    client = _client()
    oversized = b"\x00" * (MAX_UPLOAD_BYTES + 1)
    resp = client.post(
        "/upload",
        files={"file": ("big.pptx", oversized, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    assert resp.status_code == 400


def test_upload_rejects_corrupt_pptx():
    client = _client()
    resp = client.post(
        "/upload",
        files={"file": ("broken.pptx", b"not a real pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    assert resp.status_code == 400


def test_upload_returns_candidates_and_sets_cookie():
    client = _client()
    resp = _upload_candidate(client)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["candidate_id"] == "c1"
    assert "session_id" in resp.cookies


def test_upload_reports_missing_aws_credentials():
    client = _client()
    with patch(
        "app.routes.discover_candidates_for_document",
        side_effect=NoCredentialsError(),
    ):
        resp = client.post(
            "/upload",
            files={
                "file": (
                    "deck.pptx",
                    _pptx_bytes(),
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        )

    assert resp.status_code == 503
    assert resp.json() == {
        "detail": "Document analysis is unavailable because AWS credentials are not configured"
    }


def test_upload_sets_secure_cookie_when_configured():
    from app.config import Settings

    client = _client()
    with patch(
        "app.routes.get_settings",
        return_value=Settings(session_cookie_secure=True),
    ):
        resp = _upload_candidate(client)

    assert resp.status_code == 200
    assert "secure" in resp.headers["set-cookie"].lower()


def test_upload_cookie_is_not_secure_by_default():
    client = _client()
    resp = _upload_candidate(client)

    assert resp.status_code == 200
    assert "secure" not in resp.headers["set-cookie"].lower()


def test_render_without_session_is_400():
    client = _client()
    resp = client.post(
        "/render",
        json={"picks": [{"candidate_id": "c1", "template": "text_card"}]},
    )
    assert resp.status_code == 400


def test_options_returns_ranked_templates_and_caches_result():
    from app.routes import store

    client = _client()
    upload = _upload_candidate(client)

    with patch("app.routes.classify_candidate", return_value=_classification()) as classify:
        resp = client.post("/options", json={"candidate_ids": ["c1"]})

    assert resp.status_code == 200
    item = resp.json()["options"][0]
    assert item == {
        "candidate_id": "c1",
        "grade_level": 1,
        "ambiguous": False,
        "templates": [
            {
                "template": "balance_scale",
                "rationale": "shows the equation as a balance",
            },
            {"template": "number_line", "rationale": "shows one forward jump"},
            {"template": "text_card", "rationale": "always-compatible fallback"},
        ],
    }
    session = store.get(upload.json()["session_id"])
    assert session.options["c1"] == _classification()
    classify.assert_called_once_with(_candidate().source_excerpt)


def test_options_unknown_candidate_is_404():
    client = _client()
    _upload_candidate(client)

    resp = client.post("/options", json={"candidate_ids": ["does-not-exist"]})

    assert resp.status_code == 404


def test_options_without_session_is_400():
    client = _client()

    resp = client.post("/options", json={"candidate_ids": ["c1"]})

    assert resp.status_code == 400


def test_options_rejects_duplicate_candidates_before_classification():
    client = _client()
    _upload_candidate(client)

    with patch("app.routes.classify_candidate", return_value=_classification()) as classify:
        resp = client.post("/options", json={"candidate_ids": ["c1", "c1"]})

    assert resp.status_code == 400
    assert "duplicate" in resp.json()["detail"].lower()
    classify.assert_not_called()


def test_options_rejects_more_than_50_candidates_before_classification():
    client = _client()
    _upload_candidate(client)

    with patch("app.routes.classify_candidate") as classify:
        resp = client.post(
            "/options",
            json={"candidate_ids": [f"c{i}" for i in range(51)]},
        )

    assert resp.status_code == 422
    classify.assert_not_called()


def test_unknown_clip_id_is_404():
    client = _client()
    resp = client.get("/clips/nope")
    assert resp.status_code == 404


def test_storyboard_builds_scenes_with_schema_and_thumbnail_url(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidate(client)
    _options_then(client)

    thumb = tmp_path / "t.png"
    thumb.write_bytes(b"png")
    fake = Scene(
        scene_id="s1",
        candidate_id="c1",
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        params={"start": 4, "steps": [{"operation": "add", "amount": 3}]},
        status="pending_review",
        thumbnail_path=thumb,
    )

    with patch("app.routes.assemble_scene", return_value=fake):
        resp = client.post(
            "/storyboard",
            json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
        )

    assert resp.status_code == 200
    scene = resp.json()["scenes"][0]
    assert scene["scene_id"] == "s1"
    assert scene["status"] == "pending_review"
    assert scene["thumbnail_url"].startswith("/thumbnails/")
    assert scene["source_excerpt"]
    assert scene["detected_summary"] == "Detected: 4 + 3"
    assert scene["params_schema"]["properties"]["start"]["type"] == "integer"


def test_thumbnail_endpoint_serves_png(tmp_path):
    from app.routes import store

    client = _client()
    png = tmp_path / "t.png"
    png.write_bytes(b"\x89PNG\r\n")
    thumb_id = store.register_thumbnail(png)

    resp = client.get(f"/thumbnails/{thumb_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_thumbnail_unknown_id_is_404():
    client = _client()
    assert client.get("/thumbnails/nope").status_code == 404


def test_storyboard_rejects_pick_before_options_cached():
    client = _client()
    _upload_candidate(client)
    resp = client.post(
        "/storyboard",
        json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
    )
    assert resp.status_code == 400


def test_storyboard_without_session_is_400():
    client = _client()
    resp = client.post(
        "/storyboard",
        json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
    )
    assert resp.status_code == 400


def _seed_scene(client, scene, template=None):
    """Attach `scene` to the client's current session (in the module-level store)."""
    from app.models.scene import TemplateName
    from app.routes import store

    session_id = client.cookies.get("session_id")
    session = store.get(session_id)
    session.scenes[scene.scene_id] = scene
    session.scene_order.append(scene.scene_id)
    if template is not None:
        session.scene_requested_template[scene.scene_id] = TemplateName(template)
    return session


def _number_line_scene(tmp_path):
    from app.models.scene import Scene, TemplateName

    thumb = tmp_path / "t.png"
    thumb.write_bytes(b"png")
    return Scene(
        scene_id="s1",
        candidate_id="c1",
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        params={"start": 4, "steps": [{"operation": "add", "amount": 3}]},
        status="pending_review",
        thumbnail_path=thumb,
    )


def test_render_renders_only_approved_from_stored_params(tmp_path):
    client = _client()
    _upload_candidate(client)
    approved = _number_line_scene(tmp_path)
    approved = approved.model_copy(update={"status": "approved"})
    _seed_scene(client, approved)

    def fake_render(template, params, out):
        out.write_bytes(b"mp4")
        return out

    # Bedrock extraction must NOT be called at render time.
    with patch("app.routes.render_scene_to_mp4", side_effect=fake_render), patch(
        "app.pipeline.process_scene.extract_params"
    ) as extract:
        resp = client.post("/render")

    assert resp.status_code == 200
    clips = resp.json()["clips"]
    assert len(clips) == 1
    assert clips[0]["scene_id"] == "s1"
    assert clips[0]["clip_url"].startswith("/clips/")
    extract.assert_not_called()


def test_render_returns_manual_scene_results(tmp_path):
    from app.main import create_app
    from app.models.scene import Scene, TemplateName

    client = TestClient(create_app(), raise_server_exceptions=False)
    _upload_candidate(client)
    manual = Scene(
        scene_id="manual-1",
        manual_source_text="Show 3 + 4 on a number line.",
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        params={"start": 3, "steps": [{"operation": "add", "amount": 4}]},
        status="approved",
    )
    _seed_scene(client, manual)

    def fake_render(template, params, out):
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.render_scene_to_mp4", side_effect=fake_render):
        resp = client.post("/render")

    assert resp.status_code == 200
    assert resp.json()["clips"] == [{
        "scene_id": "manual-1",
        "candidate_id": None,
        "status": "approved",
        "clip_url": resp.json()["clips"][0]["clip_url"],
        "fallback_reason": None,
    }]


def test_render_skips_rejected_scenes(tmp_path):
    client = _client()
    _upload_candidate(client)
    rejected = _number_line_scene(tmp_path).model_copy(update={"status": "rejected"})
    _seed_scene(client, rejected)
    resp = client.post("/render")
    assert resp.status_code == 400  # nothing approved


def test_render_one_failure_does_not_sink_batch(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidate(client)
    good = _number_line_scene(tmp_path).model_copy(
        update={"scene_id": "sg", "status": "approved"}
    )
    bad = _number_line_scene(tmp_path).model_copy(
        update={"scene_id": "sb", "status": "approved"}
    )
    _seed_scene(client, good)
    _seed_scene(client, bad)

    calls = {"n": 0}

    def render_side_effect(template, params, out):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.render_scene_to_mp4", side_effect=render_side_effect):
        resp = client.post("/render")

    assert resp.status_code == 200
    statuses = {c["status"] for c in resp.json()["clips"]}
    assert "error" in statuses
    assert len(resp.json()["clips"]) == 2


def test_render_stored_param_validation_failure_does_not_sink_batch(tmp_path):
    good = _number_line_scene(tmp_path).model_copy(
        update={"scene_id": "sg", "status": "approved"}
    )
    bad = _number_line_scene(tmp_path).model_copy(
        update={
            "scene_id": "sb",
            "status": "approved",
            # Guard-invalid: running total goes negative (1 - 5 = -4).
            "params": {"start": 1, "steps": [{"operation": "subtract", "amount": 5}]},
        }
    )

    client = _client()
    _upload_candidate(client)
    _seed_scene(client, good)
    _seed_scene(client, bad)

    def fake_render(template, params, out):
        out.write_bytes(b"mp4")
        return out

    with patch("app.routes.render_scene_to_mp4", side_effect=fake_render):
        resp = client.post("/render")

    assert resp.status_code == 200
    clips = resp.json()["clips"]
    assert len(clips) == 2
    # Scenes render in scene_order (good seeded first, bad second).
    statuses = [c["status"] for c in clips]
    assert statuses == ["approved", "error"]
    assert clips[1]["clip_url"] is None


def test_patch_valid_params_re_renders_thumbnail(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))

    with patch("app.routes.render_scene_thumbnail") as thumb:
        resp = client.patch(
            "/storyboard/s1",
            json={"params": {"start": 10, "steps": [{"operation": "subtract", "amount": 2}]}},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["params"]["start"] == 10
    assert body["status"] == "pending_review"
    thumb.assert_called_once()


def test_patch_invalid_params_returns_422_and_keeps_scene(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))

    # start=1 then subtract 5 -> running total goes negative -> guard rejects.
    with patch("app.routes.render_scene_thumbnail") as thumb:
        resp = client.patch(
            "/storyboard/s1",
            json={"params": {"start": 1, "steps": [{"operation": "subtract", "amount": 5}]}},
        )

    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"]
    thumb.assert_not_called()


def test_patch_grade_sets_overridden(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))

    resp = client.patch("/storyboard/s1", json={"grade_level": 5})
    assert resp.status_code == 200
    assert resp.json()["grade_level"] == 5
    assert resp.json()["grade_overridden"] is True


def test_patch_out_of_range_grade_returns_field_errors_shape(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))

    with patch("app.routes.render_scene_thumbnail") as thumb:
        resp = client.patch("/storyboard/s1", json={"grade_level": 100})

    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert errors
    assert "loc" in errors[0]
    assert "msg" in errors[0]
    thumb.assert_not_called()


def test_patch_unknown_scene_is_404():
    client = _client()
    _upload_candidate(client)
    resp = client.patch("/storyboard/nope", json={"grade_level": 3})
    assert resp.status_code == 404


def test_retry_reextracts_same_template_and_keeps_scene_id(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path), template="number_line")

    fresh = Scene(
        scene_id="ignored-new-id",
        candidate_id="c1",
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        params={"start": 4, "steps": [{"operation": "add", "amount": 3}]},
        status="pending_review",
        thumbnail_path=(tmp_path / "t.png"),
    )

    with patch("app.routes.assemble_scene", return_value=fresh) as assemble:
        resp = client.post("/storyboard/s1/retry")

    assert resp.status_code == 200
    assert resp.json()["scene_id"] == "s1"  # replaced in place
    # retried on the originally-picked template
    assert assemble.call_args.kwargs["template"] == TemplateName.NUMBER_LINE


def test_retry_unknown_scene_is_404():
    client = _client()
    _upload_candidate(client)
    assert client.post("/storyboard/nope/retry").status_code == 404


def test_approve_sets_status(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))
    resp = client.post("/storyboard/s1/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_reject_sets_status(tmp_path):
    client = _client()
    _upload_candidate(client)
    _seed_scene(client, _number_line_scene(tmp_path))
    resp = client.post("/storyboard/s1/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_approve_fallback_scene_keeps_reason(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidate(client)
    fallback = Scene(
        scene_id="s2",
        candidate_id="c1",
        template=TemplateName.TEXT_CARD,
        grade_level=1,
        params={"headline": "x", "lines": ["y"]},
        status="fallback",
        fallback_reason="did not fit the chosen template",
        thumbnail_path=(tmp_path / "t.png"),
    )
    (tmp_path / "t.png").write_bytes(b"png")
    _seed_scene(client, fallback)

    resp = client.post("/storyboard/s2/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["fallback_reason"] == "did not fit the chosen template"


def test_approve_unknown_scene_is_404():
    client = _client()
    _upload_candidate(client)
    assert client.post("/storyboard/nope/approve").status_code == 404


def test_approve_chained_scene_returns_candidate_ids_and_joined_text(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidates(client, [_candidate("c1"), _candidate("c2")])
    thumb = tmp_path / "t.png"
    thumb.write_bytes(b"png")
    chained = Scene(
        scene_id="s1",
        candidate_ids=["c1", "c2"],
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        params={"items": [
            {"start": 4, "steps": [{"operation": "add", "amount": 3}]},
            {"start": 4, "steps": [{"operation": "add", "amount": 3}]},
        ]},
        status="pending_review",
        thumbnail_path=thumb,
    )
    _seed_scene(client, chained)

    resp = client.post("/storyboard/s1/approve")

    assert resp.status_code == 200
    body = resp.json()
    assert body["candidate_ids"] == ["c1", "c2"]
    assert body["candidate_id"] is None
    assert body["source_excerpt"] == (
        "Sarah has 4 apples and buys 3 more. / Sarah has 4 apples and buys 3 more."
    )
    assert body["detected_summary"] == "Detected: 4 + 3 / Detected: 4 + 3"
    assert body["params_schema"]["properties"]["items"]["type"] == "array"
