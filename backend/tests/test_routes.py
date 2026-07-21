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


def test_upload_returns_candidates_and_sets_cookie():
    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
        resp = client.post(
            "/upload",
            files={"file": ("deck.pptx", _pptx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["candidate_id"] == "c1"
    assert "session_id" in resp.cookies


def test_render_returns_clip_url_for_a_rendered_scene(tmp_path):
    from app.models.scene import Scene, TemplateName

    clip_file = tmp_path / "c1.mp4"
    clip_file.write_bytes(b"fake mp4")

    def fake_process_scene(candidate, output_dir):
        return Scene(
            scene_id="s1",
            candidate_id=candidate.candidate_id,
            template=TemplateName.NUMBER_LINE,
            grade_level=2,
            status="approved",
            render_path=clip_file,
        )

    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
        client.post(
            "/upload",
            files={"file": ("deck.pptx", _pptx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    with patch("app.routes.process_scene", side_effect=fake_process_scene):
        resp = client.post("/render", json={"candidate_ids": ["c1"]})

    assert resp.status_code == 200
    clip = resp.json()["clips"][0]
    assert clip["status"] == "approved"
    assert clip["clip_url"].startswith("/clips/")

    download = client.get(clip["clip_url"])
    assert download.status_code == 200
    assert download.content == b"fake mp4"


def test_render_reports_fallback_reason_without_clip():
    from app.models.scene import Scene, TemplateName

    def fake_process_scene(candidate, output_dir):
        return Scene(
            scene_id="s1",
            candidate_id=candidate.candidate_id,
            template=TemplateName.TEXT_CARD,
            grade_level=0,
            status="fallback",
            fallback_reason="Classification ambiguous or unsupported: no template confidently fits this problem.",
            render_path=None,
        )

    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
        client.post(
            "/upload",
            files={"file": ("deck.pptx", _pptx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    with patch("app.routes.process_scene", side_effect=fake_process_scene):
        resp = client.post("/render", json={"candidate_ids": ["c1"]})

    clip = resp.json()["clips"][0]
    assert clip["status"] == "fallback"
    assert clip["clip_url"] is None
    assert "ambiguous" in clip["fallback_reason"]


def test_render_unknown_candidate_is_404():
    client = _client()
    with patch("app.routes.discover_candidates_for_document", return_value=[_candidate()]):
        client.post(
            "/upload",
            files={"file": ("deck.pptx", _pptx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    resp = client.post("/render", json={"candidate_ids": ["does-not-exist"]})
    assert resp.status_code == 404


def test_render_without_session_is_400():
    client = _client()
    resp = client.post("/render", json={"candidate_ids": ["c1"]})
    assert resp.status_code == 400


def test_unknown_clip_id_is_404():
    client = _client()
    resp = client.get("/clips/nope")
    assert resp.status_code == 404
