from pathlib import Path

from app.meta.artifacts import store_artifact
from app.meta.dsl.scene_program import SceneProgramDocument
from app.meta.v3.render_probe import ProbeRequest, run_probe_subprocess, validate_rendered_quality


def render_preview_and_probe(
    scene_program: SceneProgramDocument,
    known_fields,
    values: dict,
    artifact_root: Path,
):
    request = ProbeRequest(
        scene_program=scene_program,
        known_fields=sorted(known_fields),
        field_values=values,
    )
    output = run_probe_subprocess(request)
    validate_rendered_quality(output.manifest).require_passed()
    artifact_hash = store_artifact(artifact_root, output.final_frame_bytes)
    return artifact_hash, output.manifest
