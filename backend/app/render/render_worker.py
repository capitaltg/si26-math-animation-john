import json
import sys
from pathlib import Path

from app.templates.registry import get_template

VALID_MODES = {"full", "thumbnail"}


def main() -> None:
    template_name, params_json_path, output_path_str, mode, scratch_dir_str = sys.argv[1:6]
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown render mode {mode!r}; expected one of {sorted(VALID_MODES)}")

    params_data = json.loads(Path(params_json_path).read_text())
    scene_cls, params_cls = get_template(template_name)
    params = params_cls.model_validate(params_data)

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
        scene = scene_cls()
        scene.params = params
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
