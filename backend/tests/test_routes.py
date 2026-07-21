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
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
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


def test_unknown_clip_id_is_404():
    client = _client()
    resp = client.get("/clips/nope")
    assert resp.status_code == 404
