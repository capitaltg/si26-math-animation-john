import json
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from app.meta.artifacts import artifact_exists, load_artifact
from app.meta.dsl.animation import AnimationDocument, compile_animation_document
from app.meta.preview_render import render_and_store_preview
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.v3.compiler import compile_teaching_plan
from app.render.full_render import BACKEND_ROOT


def _compiled():
    # A renderable animation must actually display something: build a visual, then
    # `appear` it and hold with a `wait`. A bare layout/label without an appear
    # renders an all-black frame (see test_blank_frame_raises below).
    document = AnimationDocument(root={
        "kind": "sequence",
        "steps": [
            {"kind": "label", "ref": "lbl", "text": "hello"},
            {"kind": "appear", "target_ref": "lbl"},
            {"kind": "wait", "seconds": 1},
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
            "kind": "sequence",
            "steps": [
                {
                    "kind": "grid", "ref": "g",
                    "rows": {"node": "field_ref", "field": "rows"},
                    "cols": {"node": "literal", "value": 2},
                },
                {"kind": "appear", "target_ref": "g"},
                {"kind": "wait", "seconds": 1},
            ],
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


def test_render_and_store_preview_rejects_blank_frame(tmp_path):
    # An animation that only *builds* a visual but never `appear`s it renders an
    # all-black frame; a full MP4 of the same scene would produce no video at all.
    # persist_validation relies on this raising so such a draft fails validation
    # and can never be approved and shipped to the end-user render path.
    blank = compile_animation_document(
        AnimationDocument(root={"kind": "row", "children": [{"kind": "label", "text": "hi"}]}),
        known_fields=frozenset(),
    )
    with pytest.raises(RuntimeError, match="blank frame"):
        render_and_store_preview(blank, frozenset(), {}, tmp_path)


@patch("app.meta.preview_render.subprocess.run")
def test_render_and_store_preview_raises_on_subprocess_failure(mock_run, tmp_path):
    mock_run.return_value = CompletedProcess(args=[], returncode=1, stdout="", stderr="manim failed")
    compiled = _compiled()
    with pytest.raises(RuntimeError, match="Preview render failed"):
        render_and_store_preview(compiled, frozenset(), {}, tmp_path)


def test_worker_probe_mode_writes_final_frame_and_manifest(tmp_path):
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Identify the middle value in an ordered odd-sized set.",
        "primary_visual": {
            "kind": "ordered_values", "ref": "values",
            "values": [{"node": "field_ref", "field": f"v{index}"} for index in range(1, 8)],
        },
        "strategy": "pair_elimination",
        "beats": [
            {"id": "reveal_values", "kind": "reveal", "targets": [{"visual_ref": "values"}],
             "intent": "show the ordered values together"},
            {"id": "organize_pairs", "kind": "organize", "targets": [{"visual_ref": "values"}],
             "intent": "pair values from the outside inward"},
            {"id": "focus_middle", "kind": "focus",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "identify the unpaired middle value"},
            {"id": "show_answer", "kind": "conclude",
             "targets": [{"visual_ref": "values", "part": "item", "index": 3}],
             "intent": "state the median"},
        ],
        "variation_seed": "worker-probe",
    })
    program = compile_teaching_plan(
        plan, FieldRefNode(field="v4"), frozenset(f"v{index}" for index in range(1, 8)),
        CompileContext(concept_family="measurement", grade_band="3-5"),
    )
    program_path = tmp_path / "scene.json"
    fields_path = tmp_path / "fields.json"
    values_path = tmp_path / "values.json"
    output_path = tmp_path / "probe-final.png"
    program_path.write_text(program.model_dump_json())
    fields_path.write_text(json.dumps([f"v{index}" for index in range(1, 8)]))
    values_path.write_text(json.dumps({f"v{index}": index for index in range(1, 8)}))

    result = subprocess.run(
        [
            sys.executable, "-m", "app.render.dynamic_render_worker", str(program_path),
            str(fields_path), str(values_path), str(output_path), "probe", str(tmp_path),
        ],
        capture_output=True, text=True, cwd=BACKEND_ROOT, timeout=120,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output_path.with_suffix(".json").read_text())
    assert output_path.read_bytes()
    assert [frame["beat_id"] for frame in manifest["frames"]] == [
        "reveal_values", "organize_pairs", "focus_middle", "show_answer",
    ]
    assert manifest["relations"]["median_callout"]["target_anchor"] == "values.item[3].bottom"
    assert {"target": "values.item[3]", "role": "focus"} in manifest["declared_state_events"]
    assert any(
        event["target"] == "values.item[3]" and event["role"] == "focus"
        for event in manifest["state_events"]
    )
    assert manifest["final_answer_visible"] is True
