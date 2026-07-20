import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.pipeline.discovery import discover_candidates_for_document  # noqa: E402
from app.pipeline.parsing import extract_slide_texts  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def run_fixture(pptx_path: Path) -> dict:
    slide_texts = extract_slide_texts(pptx_path)
    candidates = discover_candidates_for_document(slide_texts)
    return {
        "fixture": pptx_path.name,
        "candidate_count": len(candidates),
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }


def main() -> None:
    fixtures = sorted(FIXTURES_DIR.glob("*.pptx"))
    if not fixtures:
        raise RuntimeError(
            "No eval fixtures found; run `python eval/generate_fixtures.py` first"
        )
    print(json.dumps([run_fixture(path) for path in fixtures], indent=2))


if __name__ == "__main__":
    main()
