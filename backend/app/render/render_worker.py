import json
import sys
from pathlib import Path

from app.templates.registry import get_template


def main() -> None:
    template_name, params_json_path, output_path_str, mode = sys.argv[1:5]
    params_data = json.loads(Path(params_json_path).read_text())
    scene_cls, params_cls = get_template(template_name)
    params = params_cls.model_validate(params_data)

    from manim import tempconfig

    output_path = Path(output_path_str)
    overrides = {
        "media_dir": str(output_path.parent),
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
    matches = list(output_path.parent.rglob(f"{output_path.stem}.{ext}"))
    if not matches:
        raise RuntimeError(f"Manim did not produce the expected {ext} file for {output_path.stem}")
    matches[0].replace(output_path)


if __name__ == "__main__":
    main()
