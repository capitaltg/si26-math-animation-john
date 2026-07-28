import hashlib
import json


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def compute_artifact_hash(
    *,
    params_document: dict,
    guard_document: dict,
    answer_expression: dict,
    animation_document: dict,
    classifier_bullet: str,
    dsl_schema_versions: dict,
    compiler_version: int,
    renderer_version: int,
) -> str:
    payload = {
        "params_document": params_document,
        "guard_document": guard_document,
        "answer_expression": answer_expression,
        "animation_document": animation_document,
        "classifier_bullet": classifier_bullet,
        "dsl_schema_versions": dsl_schema_versions,
        "compiler_version": compiler_version,
        "renderer_version": renderer_version,
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
