import json
import time
from pathlib import Path

from app.models.scene import TemplateName
from app.pipeline.extraction import extract_params
from app.render.full_render import render_scene_to_mp4
from app.templates.number_line.params import NumberLineParams

SCENES = [
    "Start at 4 apples, add 3 more apples, then give away 1 apple.",
    "Start at 10 stickers, give away 4 stickers, then receive 2 stickers.",
    "Start at 7 points, add 5 points, then subtract 2 points.",
]


def run_benchmark(output_dir: Path) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, source_text in enumerate(SCENES):
        t0 = time.perf_counter()
        params = extract_params(source_text, NumberLineParams)
        t1 = time.perf_counter()
        render_scene_to_mp4(TemplateName.NUMBER_LINE, params, output_dir / f"scene_{i}.mp4")
        t2 = time.perf_counter()

        results.append(
            {
                "scene": source_text,
                "extraction_seconds": round(t1 - t0, 2),
                "render_seconds": round(t2 - t1, 2),
                "total_seconds": round(t2 - t0, 2),
            }
        )

    return results


def main() -> None:
    output_dir = Path(__file__).parent / "_benchmark_output"
    print(json.dumps(run_benchmark(output_dir), indent=2))


if __name__ == "__main__":
    main()
