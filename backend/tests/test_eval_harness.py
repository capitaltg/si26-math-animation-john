import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_fixture_builders_write_all_three_decks(tmp_path):
    from eval.generate_fixtures import (
        build_ambiguous_phrasing_deck,
        build_distractor_heavy_deck,
        build_zero_candidate_deck,
    )

    builders = [
        build_zero_candidate_deck,
        build_distractor_heavy_deck,
        build_ambiguous_phrasing_deck,
    ]
    paths = [tmp_path / f"fixture_{index}.pptx" for index in range(3)]

    for builder, path in zip(builders, paths):
        builder(path)

    assert all(path.exists() and path.stat().st_size > 0 for path in paths)


@patch("eval.run_eval.discover_candidates_for_document", return_value=[])
def test_run_fixture_reports_zero_candidates(mock_discover, tmp_path):
    from eval.generate_fixtures import build_zero_candidate_deck
    from eval.run_eval import run_fixture

    pptx_path = tmp_path / "zero_candidate_deck.pptx"
    build_zero_candidate_deck(pptx_path)

    report = run_fixture(pptx_path)

    assert report == {
        "fixture": "zero_candidate_deck.pptx",
        "candidate_count": 0,
        "candidates": [],
    }
    mock_discover.assert_called_once()
