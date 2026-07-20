import json
from pathlib import Path

from app.pipeline.discovery import discover_candidates_for_document
from app.pipeline.parsing import extract_slide_texts

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def run_fixture(pptx_path: Path) -> dict:
    slide_texts = extract_slide_texts(pptx_path)
    candidates = discover_candidates_for_document(slide_texts)
    return {
        "fixture": pptx_path.name,
        "candidate_count": len(candidates),
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }


def main() -> None:
    report = [run_fixture(path) for path in sorted(FIXTURES_DIR.glob("*.pptx"))]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
