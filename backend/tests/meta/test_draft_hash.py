from app.meta.draft_hash import compute_artifact_hash


def _base_kwargs(**overrides):
    kwargs = dict(
        params_document={"params_version": 1, "fields": []},
        guard_document={"guard_version": 1, "predicates": []},
        answer_expression={"node": "literal", "value": 1},
        teaching_plan_document={
            "plan_version": 3,
            "beats": [{"id": "reveal", "kind": "reveal", "intent": "show values"}],
        },
        scene_program_document={
            "scene_version": 3,
            "timeline": [{"beat_id": "reveal", "action": {"kind": "reveal"}}],
        },
        classifier_bullet="use for X",
        dsl_schema_versions={
            "params_version": 1,
            "guard_version": 1,
            "teaching_plan_version": 3,
            "scene_version": 3,
        },
        compiler_version=3,
        renderer_version=3,
    )
    kwargs.update(overrides)
    return kwargs


def test_hash_is_stable_for_identical_input():
    a = compute_artifact_hash(**_base_kwargs())
    b = compute_artifact_hash(**_base_kwargs())
    assert a == b
    assert a.startswith("sha256:")
    assert len(a) == len("sha256:") + 64


def test_hash_changes_when_teaching_plan_beat_changes():
    original = compute_artifact_hash(**_base_kwargs())
    changed = compute_artifact_hash(**_base_kwargs(teaching_plan_document={
        "plan_version": 3,
        "beats": [{"id": "reveal", "kind": "focus", "intent": "emphasize values"}],
    }))
    assert changed != original


def test_hash_changes_when_compiled_scene_program_changes():
    original = compute_artifact_hash(**_base_kwargs())
    changed = compute_artifact_hash(**_base_kwargs(scene_program_document={
        "scene_version": 3,
        "timeline": [{"beat_id": "reveal", "action": {"kind": "set_role", "role": "focus"}}],
    }))
    assert changed != original


def test_hash_is_key_order_independent():
    doc_a = {"params_version": 1, "fields": [{"name": "x", "type": "integer"}]}
    doc_b = {"fields": [{"type": "integer", "name": "x"}], "params_version": 1}
    assert compute_artifact_hash(**_base_kwargs(params_document=doc_a)) == compute_artifact_hash(
        **_base_kwargs(params_document=doc_b)
    )
