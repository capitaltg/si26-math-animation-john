import json
import sys
from pathlib import Path

from app.meta.dsl.animation import AnimationDocument, compile_animation_document
from app.meta.dynamic_scene import DynamicTemplateScene

VALID_MODES = {"full", "thumbnail"}


def main() -> None:
    anim_path, known_fields_path, values_path, output_path_str, mode, scratch_dir_str = sys.argv[1:7]
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown render mode {mode!r}; expected one of {sorted(VALID_MODES)}")

    animation_document = AnimationDocument.model_validate_json(Path(anim_path).read_text())
    known_fields = frozenset(json.loads(Path(known_fields_path).read_text()))
    field_values = json.loads(Path(values_path).read_text())
    compiled = compile_animation_document(animation_document, known_fields)

    from manim import tempconfig

    output_path = Path(output_path_str)
    overrides = {
        "media_dir": scratch_dir_str,
        "output_file": output_path.stem,
        "disable_caching": True,
    }
    if mode == "thumbnail":
        overrides["save_last_frame"] = True
        overrides["quality"] = "low_quality"
    else:
        overrides["quality"] = "medium_quality"

    with tempconfig(overrides):
        scene = DynamicTemplateScene()
        scene.compiled_animation = compiled
        scene.field_values = field_values
        scene.render()

    ext = "png" if mode == "thumbnail" else "mp4"
    destination = output_path.resolve()
    matches = [
        path
        for path in Path(scratch_dir_str).rglob(f"{output_path.stem}.{ext}")
        if path.resolve() != destination
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly 1 {ext} file for {output_path.stem}, found {len(matches)}: {matches}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    matches[0].replace(output_path)


if __name__ == "__main__":
    main()
