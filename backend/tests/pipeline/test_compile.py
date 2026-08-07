from app.models.scene import Scene, TemplateName
from app.pipeline.compile import compile_scene_program
from app.templates.registry import static_ref


def _scene(params: dict) -> Scene:
    return Scene(
        scene_id="s1",
        candidate_id="c1",
        template=static_ref(TemplateName.NUMBER_LINE),
        grade_level=2,
        params=params,
        status="pending_review",
    )


def test_compile_is_deterministic():
    params = {"start": 4, "steps": [{"operation": "add", "amount": 3}]}
    _, hash1, size1, _ = compile_scene_program(_scene(params))
    _, hash2, size2, _ = compile_scene_program(_scene(dict(params)))
    assert hash1 == hash2
    assert size1 == size2
    assert len(hash1) == 64


def test_compile_hash_changes_with_params():
    a = compile_scene_program(_scene({"start": 4, "steps": []}))
    b = compile_scene_program(_scene({"start": 5, "steps": []}))
    assert a[1] != b[1]


def test_compile_key_order_does_not_affect_hash():
    a = compile_scene_program(_scene({"start": 4, "steps": []}))
    b = compile_scene_program(_scene({"steps": [], "start": 4}))
    assert a[1] == b[1]


def test_compile_none_template_returns_none():
    scene = Scene(
        scene_id="s2",
        manual_source_text="freeform",
        template=None,
        grade_level=2,
    )
    program, digest, size, ms = compile_scene_program(scene)
    assert program is None
    assert digest is None
    assert size is None
    assert ms is None
