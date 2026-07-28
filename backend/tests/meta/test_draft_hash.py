from app.meta.draft_hash import compute_artifact_hash


def _base_kwargs(**overrides):
    kwargs = dict(
        params_document={"params_version": 1, "fields": []},
        guard_document={"guard_version": 1, "predicates": []},
        answer_expression={"node": "literal", "value": 1},
        animation_document={"animation_version": 1, "root": {"kind": "label", "text": "x"}},
        classifier_bullet="use for X",
        dsl_schema_versions={"params_version": 1, "guard_version": 1, "animation_version": 1},
        compiler_version=1,
        renderer_version=1,
    )
    kwargs.update(overrides)
    return kwargs


def test_hash_is_stable_for_identical_input():
    a = compute_artifact_hash(**_base_kwargs())
    b = compute_artifact_hash(**_base_kwargs())
    assert a == b
    assert a.startswith("sha256:")
    assert len(a) == len("sha256:") + 64


def test_hash_changes_when_classifier_bullet_changes():
    a = compute_artifact_hash(**_base_kwargs())
    b = compute_artifact_hash(**_base_kwargs(classifier_bullet="use for Y"))
    assert a != b


def test_hash_is_key_order_independent():
    doc_a = {"params_version": 1, "fields": [{"name": "x", "type": "integer"}]}
    doc_b = {"fields": [{"type": "integer", "name": "x"}], "params_version": 1}
    a = compute_artifact_hash(**_base_kwargs(params_document=doc_a))
    b = compute_artifact_hash(**_base_kwargs(params_document=doc_b))
    assert a == b


def test_hash_changes_when_compiler_version_changes():
    a = compute_artifact_hash(**_base_kwargs())
    b = compute_artifact_hash(**_base_kwargs(compiler_version=2))
    assert a != b
