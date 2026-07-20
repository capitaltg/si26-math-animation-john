from unittest.mock import patch

import pytest


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_wraps_bedrock_response_into_candidates(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = {
        "candidates": [
            {"source_excerpt": "4 + 3", "slide_index": 0, "one_line_summary": "Detected: 4 + 3"},
        ]
    }

    candidates = discover_candidates(["The problem is 4 + 3."])

    assert len(candidates) == 1
    assert candidates[0].source_excerpt == "4 + 3"
    assert candidates[0].slide_index == 0
    assert candidates[0].candidate_id
    assert "computed answer" in mock_call.call_args.kwargs["system_prompt"]
    assert "verbatim" in mock_call.call_args.kwargs["system_prompt"]


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_drops_out_of_chunk_slide_index(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = {
        "candidates": [
            {
                "source_excerpt": "4 + 3",
                "slide_index": 999,
                "one_line_summary": "Detected: 4 + 3",
            }
        ]
    }

    assert discover_candidates(["The problem is 4 + 3."]) == []


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_drops_excerpt_not_on_reported_slide(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = {
        "candidates": [
            {
                "source_excerpt": "9 times 9",
                "slide_index": 0,
                "one_line_summary": "Detected: 9 times 9",
            }
        ]
    }

    assert discover_candidates(["The problem is 4 + 3."]) == []


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_normalizes_whitespace_when_grounding(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = {
        "candidates": [
            {
                "source_excerpt": "Sarah has 4 apples and buys 3 more.",
                "slide_index": 25,
                "one_line_summary": "Detected: 4 + 3",
            }
        ]
    }

    candidates = discover_candidates(
        ["Sarah has 4 apples\nand buys 3 more."], start_index=25
    )

    assert len(candidates) == 1


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
                    "source_excerpt": f"slide {slide_index}",
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


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_accepts_ordered_noncontiguous_slide_tokens(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = {
        "candidates": [
            {
                "source_excerpt": (
                    "A recipe says that 6 spring rolls will serve 3 people. "
                    "Complete the table.\n"
                    "number of spring rolls | number of people\n"
                    "6 | 3\n30 | [blank]\n[blank] | 40\n28 | [blank]"
                ),
                "slide_index": 0,
                "one_line_summary": "Complete the proportional table",
            }
        ]
    }
    slide_text = (
        "ACTIVITY 1\n"
        "A recipe says that 6 spring rolls will serve 3 people. Complete the table.\n"
        "Source: page 2 of 5.\n"
        "number of spring rolls\nnumber of people\n6\n3\n30\n40\n28"
    )

    candidates = discover_candidates([slide_text])

    assert len(candidates) == 1


@pytest.mark.parametrize(
    ("slide_text", "source_excerpt"),
    [
        ("Use 10 + 2 = 12.", "Use 10 - 2 = 12."),
        ("Mary swims 1/8 mile each day for 12 days.", "Mary swims 1/8 mile each day for 13 days."),
        ("6 spring rolls will serve 3 people.", "3 people will serve 6 spring rolls."),
        ("Complete the table with 6 and 3.", "[blank] | [blank]"),
    ],
    ids=["changed-operator", "changed-number", "reordered", "placeholder-only"],
)
def test_grounding_rejects_changed_reordered_or_empty_content(
    slide_text, source_excerpt
):
    from app.pipeline.discovery import _DiscoveredItem, _is_grounded

    item = _DiscoveredItem(
        source_excerpt=source_excerpt,
        slide_index=0,
        one_line_summary="summary",
    )

    assert not _is_grounded(item, [slide_text], start_index=0)
