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
    assert "computed answer" in mock_call.call_args.kwargs["system_prompt"]


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_for_document_applies_global_slide_offset(mock_call):
    from app.pipeline.discovery import discover_candidates_for_document

    def fake_call_with_tool(*, system_prompt, user_message, tool_name, tool_schema):
        # The prompt numbers its first line "[slide N] ...". Echo N back as the
        # discovered candidate's slide_index, exactly as a real model would when
        # asked to report which numbered slide the excerpt came from. This means
        # the test genuinely exercises the prompt's numbering rather than
        # hardcoding an expected offset.
        first_line = user_message.splitlines()[0]
        slide_index = int(first_line.split("]")[0].removeprefix("[slide").strip())
        return {
            "candidates": [
                {
                    "source_excerpt": f"excerpt {slide_index}",
                    "slide_index": slide_index,
                    "one_line_summary": f"summary {slide_index}",
                }
            ]
        }

    mock_call.side_effect = fake_call_with_tool
    slide_texts = [f"slide {i}" for i in range(50)]

    candidates = discover_candidates_for_document(slide_texts, chunk_size=25)

    assert mock_call.call_count == 2
    # Chunk-local numbering (the bug) would report [0, 0] for both chunks since
    # discover_candidates always started counting at 0 within each chunk.
    # Correct global numbering must report the first slide of each chunk: 0 and 25.
    assert [c.slide_index for c in candidates] == [0, 25]
    assert candidates[1].slide_index >= 25
