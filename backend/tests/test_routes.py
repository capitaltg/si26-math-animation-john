# backend/tests/test_routes.py
import io
from unittest.mock import patch

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


def test_render_returns_clip_url_for_a_rendered_scene(tmp_path):
    from app.models.scene import Scene, TemplateName

    clip_file = tmp_path / "c1.mp4"
    clip_file.write_bytes(b"fake mp4")

    def fake_process_scene(candidate, output_dir, *, template, grade):
        assert template == TemplateName.NUMBER_LINE
        assert grade == 1
        return Scene(
            scene_id="s1",
            candidate_id=candidate.candidate_id,
            template=template,
            grade_level=grade,
            status="approved",
            render_path=clip_file,
        )

    client = _client()
    _upload_candidate(client)
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})
    with patch("app.routes.process_scene", side_effect=fake_process_scene):
        resp = client.post(
            "/render",
            json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
        )

    assert resp.status_code == 200
    clip = resp.json()["clips"][0]
    assert clip["status"] == "approved"
    assert clip["clip_url"].startswith("/clips/")

    download = client.get(clip["clip_url"])
    assert download.status_code == 200
    assert download.content == b"fake mp4"


def test_render_reports_fallback_reason_without_clip():
    from app.models.scene import Scene, TemplateName

    def fake_process_scene(candidate, output_dir, *, template, grade):
        return Scene(
            scene_id="s1",
            candidate_id=candidate.candidate_id,
            template=template,
            grade_level=grade,
            status="fallback",
            fallback_reason="Classification ambiguous or unsupported: no template confidently fits this problem.",
            render_path=None,
        )

    client = _client()
    _upload_candidate(client)
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})
    with patch("app.routes.process_scene", side_effect=fake_process_scene):
        resp = client.post(
            "/render",
            json={"picks": [{"candidate_id": "c1", "template": "text_card"}]},
        )

    clip = resp.json()["clips"][0]
    assert clip["status"] == "fallback"
    assert clip["clip_url"] is None
    assert "ambiguous" in clip["fallback_reason"]


def test_render_unknown_candidate_is_404():
    client = _client()
    _upload_candidate(client)
    resp = client.post(
        "/render",
        json={
            "picks": [
                {"candidate_id": "does-not-exist", "template": "text_card"}
            ]
        },
    )
    assert resp.status_code == 404


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


def test_render_rejects_template_that_was_not_offered():
    client = _client()
    _upload_candidate(client)
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})

    resp = client.post(
        "/render",
        json={"picks": [{"candidate_id": "c1", "template": "array_grid"}]},
    )

    assert resp.status_code == 400
    assert "not offered" in resp.json()["detail"]


def test_render_rejects_pick_before_options_are_cached():
    client = _client()
    _upload_candidate(client)

    resp = client.post(
        "/render",
        json={"picks": [{"candidate_id": "c1", "template": "number_line"}]},
    )

    assert resp.status_code == 400
    assert "options" in resp.json()["detail"].lower()


def test_render_rejects_unknown_template_name_as_bad_request():
    client = _client()
    _upload_candidate(client)
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})

    resp = client.post(
        "/render",
        json={"picks": [{"candidate_id": "c1", "template": "hologram"}]},
    )

    assert resp.status_code == 400
    assert "not offered" in resp.json()["detail"]


def test_render_preflights_entire_batch_before_rendering(tmp_path):
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidates(client, [_candidate("c1"), _candidate("c2")])
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1", "c2"]})

    rendered_scene = Scene(
        scene_id="s1",
        candidate_id="c1",
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        status="approved",
        render_path=tmp_path / "render.mp4",
    )
    with patch("app.routes.process_scene", return_value=rendered_scene) as process:
        resp = client.post(
            "/render",
            json={
                "picks": [
                    {"candidate_id": "c1", "template": "number_line"},
                    {"candidate_id": "c2", "template": "array_grid"},
                ]
            },
        )

    assert resp.status_code == 400
    process.assert_not_called()


def test_render_rejects_duplicate_candidates_before_rendering():
    from app.models.scene import Scene, TemplateName

    client = _client()
    _upload_candidate(client)
    with patch("app.routes.classify_candidate", return_value=_classification()):
        client.post("/options", json={"candidate_ids": ["c1"]})

    rendered_scene = Scene(
        scene_id="s1",
        candidate_id="c1",
        template=TemplateName.NUMBER_LINE,
        grade_level=1,
        status="approved",
    )
    with patch("app.routes.process_scene", return_value=rendered_scene) as process:
        resp = client.post(
            "/render",
            json={
                "picks": [
                    {"candidate_id": "c1", "template": "number_line"},
                    {"candidate_id": "c1", "template": "text_card"},
                ]
            },
        )

    assert resp.status_code == 400
    assert "duplicate" in resp.json()["detail"].lower()
    process.assert_not_called()


def test_render_rejects_more_than_50_picks_before_rendering():
    client = _client()
    _upload_candidate(client)

    with patch("app.routes.process_scene") as process:
        resp = client.post(
            "/render",
            json={
                "picks": [
                    {"candidate_id": f"c{i}", "template": "text_card"}
                    for i in range(51)
                ]
            },
        )

    assert resp.status_code == 422
    process.assert_not_called()


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
