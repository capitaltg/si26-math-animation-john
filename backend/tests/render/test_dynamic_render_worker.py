from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from app.meta.artifacts import artifact_exists, load_artifact
from app.meta.dsl.animation import AnimationDocument, compile_animation_document
from app.meta.preview_render import render_and_store_preview


def _compiled():
    document = AnimationDocument(root={
        "kind": "row",
        "children": [
            {"kind": "label", "ref": "lbl", "text": "hello"},
        ],
    })
    return compile_animation_document(document, known_fields=frozenset())


def test_render_and_store_preview_produces_a_stored_png(tmp_path):
    compiled = _compiled()
    digest = render_and_store_preview(compiled, frozenset(), {}, tmp_path)
    assert artifact_exists(tmp_path, digest)
    assert len(load_artifact(tmp_path, digest)) > 0


def test_render_and_store_preview_uses_field_values():
    compiled_with_expr = compile_animation_document(
        AnimationDocument(root={
            "kind": "grid",
            "rows": {"node": "field_ref", "field": "rows"},
            "cols": {"node": "literal", "value": 2},
        }),
        known_fields=frozenset({"rows"}),
    )
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        digest = render_and_store_preview(
            compiled_with_expr, frozenset({"rows"}), {"rows": 3}, Path(tmp)
        )
        assert digest


@patch("app.meta.preview_render.subprocess.run")
def test_render_and_store_preview_raises_on_subprocess_failure(mock_run, tmp_path):
    mock_run.return_value = CompletedProcess(args=[], returncode=1, stdout="", stderr="manim failed")
    compiled = _compiled()
    with pytest.raises(RuntimeError, match="Preview render failed"):
        render_and_store_preview(compiled, frozenset(), {}, tmp_path)
