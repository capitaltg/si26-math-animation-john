from unittest.mock import patch


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_wraps_bedrock_response_into_candidates(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = {
        "candidates": [
            {"source_excerpt": "4 + 3", "slide_index": 0, "one_line_summary": "Detected: 4 + 3"},
        ]
    }

    candidates = discover_candidates(["slide 0 text"])

    assert len(candidates) == 1
    assert candidates[0].source_excerpt == "4 + 3"
    assert candidates[0].slide_index == 0
    assert candidates[0].candidate_id


@patch("app.pipeline.discovery.discover_candidates")
def test_discover_candidates_for_document_merges_across_chunks(mock_discover):
    from app.models.candidate import Candidate
    from app.pipeline.discovery import discover_candidates_for_document

    mock_discover.side_effect = [
        [Candidate(candidate_id="a", source_excerpt="x", slide_index=0, one_line_summary="x")],
        [Candidate(candidate_id="b", source_excerpt="y", slide_index=30, one_line_summary="y")],
    ]
    slide_texts = [f"slide {i}" for i in range(50)]

    candidates = discover_candidates_for_document(slide_texts, chunk_size=25)

    assert mock_discover.call_count == 2
    assert [c.candidate_id for c in candidates] == ["a", "b"]
