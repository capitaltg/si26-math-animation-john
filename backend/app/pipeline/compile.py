"""Deterministic params → scene-program compile step.

Surfaces the boundary between LLM-generated params and the pure function that
turns them into an executable scene program. Same (template, params) in → same
hash out; audiences can rerun and confirm.
"""

from __future__ import annotations

import hashlib
import json
import time

from app.models.scene import Scene


def canonical_program(scene: Scene) -> dict | None:
    if scene.template is None:
        return None
    return {
        "template": scene.template.model_dump(mode="json"),
        "params": scene.params,
    }


def compile_scene_program(
    scene: Scene,
) -> tuple[dict | None, str | None, int | None, float | None]:
    """Return (program, sha256_hex, size_bytes, compile_ms).

    Pure: identical (template, params) always produce the same hash.
    """
    program = canonical_program(scene)
    if program is None:
        return None, None, None, None
    start = time.perf_counter()
    serialized = json.dumps(program, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest = hashlib.sha256(serialized).hexdigest()
    ms = (time.perf_counter() - start) * 1000.0
    return program, digest, len(serialized), ms
