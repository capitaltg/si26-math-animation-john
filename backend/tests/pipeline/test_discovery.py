from unittest.mock import patch

import pytest

from app.pipeline.parsing import Block


def _text_blocks(texts: list[str]) -> list[list[Block]]:
    return [[Block(kind="text", table_ord=None, text=text)] for text in texts]


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_wraps_bedrock_response_into_candidates(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {"source_excerpt": "4 + 3", "slide_index": 0, "one_line_summary": "Detected: 4 + 3"},
            ]
        },
    )

    candidates = discover_candidates(_text_blocks(["The problem is 4 + 3."]))

    assert len(candidates) == 1
    assert candidates[0].source_excerpt == "4 + 3"
    assert candidates[0].slide_index == 0
    assert candidates[0].candidate_id
    assert "computed answer" in mock_call.call_args.kwargs["system_prompt"]
    assert "verbatim" in mock_call.call_args.kwargs["system_prompt"]


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_drops_out_of_chunk_slide_index(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": "4 + 3",
                    "slide_index": 999,
                    "one_line_summary": "Detected: 4 + 3",
                }
            ]
        },
    )

    assert discover_candidates(_text_blocks(["The problem is 4 + 3."])) == []


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_drops_excerpt_not_on_reported_slide(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": "9 times 9",
                    "slide_index": 0,
                    "one_line_summary": "Detected: 9 times 9",
                }
            ]
        },
    )

    assert discover_candidates(_text_blocks(["The problem is 4 + 3."])) == []


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_normalizes_whitespace_when_grounding(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": "Sarah has 4 apples and buys 3 more.",
                    "slide_index": 25,
                    "one_line_summary": "Detected: 4 + 3",
                }
            ]
        },
    )

    candidates = discover_candidates(
        _text_blocks(["Sarah has 4 apples\nand buys 3 more."]), start_index=25
    )

    assert len(candidates) == 1


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_for_document_applies_global_slide_offset(mock_call):
    from app.pipeline.discovery import discover_candidates_for_document

    def fake_call_with_tool(*, system_prompt, user_message, tools):
        # The prompt numbers its first line "[slide N] ...". Echo N back as the
        # discovered candidate's slide_index, exactly as a real model would when
        # asked to report which numbered slide the excerpt came from. This means
        # the test genuinely exercises the prompt's numbering rather than
        # hardcoding an expected offset.
        first_line = user_message.splitlines()[0]
        slide_index = int(first_line.split("]")[0].removeprefix("[slide").strip())
        return (
            "report_candidates",
            {
                "candidates": [
                    {
                        "source_excerpt": f"slide {slide_index}",
                        "slide_index": slide_index,
                        "one_line_summary": f"summary {slide_index}",
                    }
                ]
            },
        )

    mock_call.side_effect = fake_call_with_tool
    slide_blocks = _text_blocks([f"slide {i}" for i in range(50)])

    candidates = discover_candidates_for_document(slide_blocks, chunk_size=25)

    assert mock_call.call_count == 2
    # Chunk-local numbering (a past bug) would report [0, 0] for both chunks.
    # Correct global numbering must report the first slide of each chunk: 0 and 25.
    assert [c.slide_index for c in candidates] == [0, 25]
    assert candidates[1].slide_index >= 25


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_accepts_table_completion_with_header_and_data_cells(mock_call):
    """The legitimate noncontiguous case: a table's cells get flattened onto
    separate lines by parsing, but a reformatted "6 | 3"-style excerpt that
    reassembles header + data cells from that one table must still ground.
    """
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
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
        },
    )
    slide_blocks = [[
        Block(kind="text", table_ord=None, text="ACTIVITY 1"),
        Block(
            kind="text",
            table_ord=None,
            text="A recipe says that 6 spring rolls will serve 3 people. Complete the table.",
        ),
        Block(kind="text", table_ord=None, text="Source: page 2 of 5."),
        Block(kind="cell", table_ord=0, text="number of spring rolls"),
        Block(kind="cell", table_ord=0, text="number of people"),
        Block(kind="cell", table_ord=0, text="6"),
        Block(kind="cell", table_ord=0, text="3"),
        Block(kind="cell", table_ord=0, text="30"),
        Block(kind="cell", table_ord=0, text=""),
        Block(kind="cell", table_ord=0, text=""),
        Block(kind="cell", table_ord=0, text="40"),
        Block(kind="cell", table_ord=0, text="28"),
        Block(kind="cell", table_ord=0, text=""),
    ]]

    candidates = discover_candidates(slide_blocks)

    assert len(candidates) == 1


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_rejects_cross_sentence_splice_without_table(mock_call):
    """The reported P0: a candidate excerpt stitched from two unrelated
    sentences, using real tokens from both, must not ground just because the
    tokens appear in the same relative order somewhere on the slide.
    """
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": "Mia has 3 oranges.",
                    "slide_index": 0,
                    "one_line_summary": "Mia's oranges",
                }
            ]
        },
    )

    candidates = discover_candidates(
        _text_blocks(["Mia has 3 apples. The class takes a break. Noah has 5 oranges."])
    )

    assert candidates == []


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_rejects_cross_sentence_splice_with_unrelated_table_present(
    mock_call,
):
    """Same splice as above, but the slide also has an unrelated table. The
    word "oranges" must not be able to ride the table-suffix allowance just
    because a table exists somewhere on the slide.
    """
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": "Mia has 3 oranges.",
                    "slide_index": 0,
                    "one_line_summary": "Mia's oranges",
                }
            ]
        },
    )
    slide_blocks = [[
        Block(
            kind="text",
            table_ord=None,
            text="Mia has 3 apples. The class takes a break. Noah has 5 oranges.",
        ),
        Block(kind="cell", table_ord=0, text="width"),
        Block(kind="cell", table_ord=0, text="4"),
        Block(kind="cell", table_ord=0, text="height"),
        Block(kind="cell", table_ord=0, text="6"),
    ]]

    candidates = discover_candidates(slide_blocks)

    assert candidates == []


def test_grounding_rejects_number_spliced_across_two_tables():
    """Two tables on one slide; a suffix built from one table's number plus
    another table's number must not ground by treating both tables as one
    merged pool of tokens.
    """
    from app.pipeline.discovery import _DiscoveredItem, _is_grounded

    item = _DiscoveredItem(
        source_excerpt="6 20",
        slide_index=0,
        one_line_summary="summary",
    )
    slide_blocks = [[
        Block(kind="cell", table_ord=0, text="6"),
        Block(kind="cell", table_ord=0, text="3"),
        Block(kind="cell", table_ord=1, text="10"),
        Block(kind="cell", table_ord=1, text="20"),
    ]]

    assert not _is_grounded(item, slide_blocks, start_index=0)


def test_grounding_accepts_table_suffix_requiring_skip_not_greedy_match():
    """Regression guard for _suffix_from_whole_cells: a greedy leftmost-match
    (consume the first cell that matches at the current position, then
    never reconsider it) would wrongly fail here. A text-block prefix
    forces the excerpt through the split-loop's suffix-DP path rather than
    the whole-excerpt-in-one-cell shortcut (the excerpt doesn't fit inside
    either single cell, so that shortcut doesn't fire). The suffix "width
    value" is directly matched by the second cell alone — a greedy walker
    that commits to the first cell ("width") because it matches at
    position 0 would advance past it and then fail to match the remaining
    one-token gap against the two-token second cell, wrongly rejecting.
    The DP must keep position 0 reachable (the option of not consuming the
    first cell) so the second cell can still match there.
    """
    from app.pipeline.discovery import _DiscoveredItem, _is_grounded

    item = _DiscoveredItem(
        source_excerpt="Find the width value.",
        slide_index=0,
        one_line_summary="summary",
    )
    slide_blocks = [[
        Block(kind="text", table_ord=None, text="Find the"),
        Block(kind="cell", table_ord=0, text="width"),
        Block(kind="cell", table_ord=0, text="width value"),
    ]]

    assert _is_grounded(item, slide_blocks, start_index=0)


def test_grounding_rejects_splice_built_from_two_cells_in_same_table():
    """Regression guard for the table-cell variant of the P0 splice: prose
    living in two cells of one table, spliced the same way as the
    text-block P0, must not ground just because both real words appear
    somewhere in that table's pooled cell tokens.
    """
    from app.pipeline.discovery import _DiscoveredItem, _is_grounded

    item = _DiscoveredItem(
        source_excerpt="Mia has 3 oranges.",
        slide_index=0,
        one_line_summary="Mia's oranges",
    )
    slide_blocks = [[
        Block(kind="cell", table_ord=0, text="Mia has 3 apples."),
        Block(kind="cell", table_ord=0, text="Noah has 5 oranges."),
    ]]

    assert not _is_grounded(item, slide_blocks, start_index=0)


@pytest.mark.parametrize(
    ("slide_text", "source_excerpt"),
    [
        ("Use 10 + 2 = 12.", "Use 10 - 2 = 12."),
        ("Mary swims 1/8 mile each day for 12 days.", "Mary swims 1/8 mile each day for 13 days."),
        ("Measure 3.25 cups of flour.", "Measure 3.15 cups of flour."),
        ("6 spring rolls will serve 3 people.", "3 people will serve 6 spring rolls."),
        ("Complete the table with 6 and 3.", "[blank] | [blank]"),
    ],
    ids=[
        "changed-operator",
        "changed-integer",
        "changed-conventional-decimal",
        "reordered",
        "placeholder-only",
    ],
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

    assert not _is_grounded(item, _text_blocks([slide_text]), start_index=0)


def test_grounding_accepts_unspaced_letter_hyphen_digit_against_spaced_excerpt():
    """Regression guard for the shared _GROUNDING_TOKEN_RE: a slide that
    renders "x-5" unspaced must still ground an excerpt that spells the same
    expression with spaces ("x - 5"), since a narrower lookbehind on the
    negative-number branch could tokenize "x-5" as ['x', '-5'] (letter
    swallowed into the operand) instead of ['x', '-', '5'], breaking the
    contiguous match here in discovery.py.
    """
    from app.pipeline.discovery import _DiscoveredItem, _is_grounded

    item = _DiscoveredItem(
        source_excerpt="Solve x - 5 = 12.",
        slide_index=0,
        one_line_summary="Solve for x",
    )

    assert _is_grounded(item, _text_blocks(["Solve x-5=12."]), start_index=0)


def test_grounding_rejects_omitted_standalone_division_operator():
    from app.pipeline.discovery import _DiscoveredItem, _is_grounded

    item = _DiscoveredItem(
        source_excerpt="Use 6 / 3 = 2.",
        slide_index=0,
        one_line_summary="summary",
    )

    assert not _is_grounded(item, _text_blocks(["Use 6 3 = 2."]), start_index=0)


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_rejects_omitted_standalone_multiplication_operator(
    mock_call,
):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": "Use 6 * 3 = 18.",
                    "slide_index": 0,
                    "one_line_summary": "Multiply 6 by 3",
                }
            ]
        },
    )

    assert discover_candidates(_text_blocks(["Use 6 3 = 18."])) == []


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_rejects_omitted_exponentiation_symbol(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": "Use 2 ^ 3 = 8.",
                    "slide_index": 0,
                    "one_line_summary": "Cube 2",
                }
            ]
        },
    )

    assert discover_candidates(_text_blocks(["Use 2 3 = 8."])) == []


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_rejects_omitted_percent_symbol(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": "Find 50% of 20.",
                    "slide_index": 0,
                    "one_line_summary": "Find the percentage",
                }
            ]
        },
    )

    assert discover_candidates(_text_blocks(["Find 50 of 20."])) == []


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_rejects_omitted_grouping_symbol(mock_call):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": "Use (2 + 3) * 4.",
                    "slide_index": 0,
                    "one_line_summary": "Multiply a grouped sum",
                }
            ]
        },
    )

    assert discover_candidates(_text_blocks(["Use 2 + 3 * 4."])) == []


@pytest.mark.parametrize(
    "slide_text",
    ["Use 5 cup of sugar.", "Use .6 cup of sugar."],
    ids=["integer-five", "leading-dot-six"],
)
def test_grounding_rejects_changed_leading_dot_decimal(slide_text):
    from app.pipeline.discovery import _DiscoveredItem, _is_grounded

    item = _DiscoveredItem(
        source_excerpt="Use .5 cup of sugar.",
        slide_index=0,
        one_line_summary="Measure sugar",
    )

    assert not _is_grounded(item, _text_blocks([slide_text]), start_index=0)


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_filters_malformed_item_without_dropping_valid_item(
    mock_call,
):
    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {"source_excerpt": "4 + 3", "slide_index": 0},
                {
                    "source_excerpt": "4 + 3",
                    "slide_index": 0,
                    "one_line_summary": "Add 4 and 3",
                },
            ]
        },
    )

    candidates = discover_candidates(_text_blocks(["The problem is 4 + 3."]))

    assert [candidate.source_excerpt for candidate in candidates] == ["4 + 3"]
    candidate_schema = mock_call.call_args.kwargs["tools"][0]["schema"]["$defs"][
        "_DiscoveredItem"
    ]
    assert set(candidate_schema["required"]) == {
        "source_excerpt",
        "slide_index",
        "one_line_summary",
    }


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_rejects_malformed_top_level_envelope(mock_call):
    from pydantic import ValidationError

    from app.pipeline.discovery import discover_candidates

    mock_call.return_value = ("report_candidates", {"candidates": {"source_excerpt": "4 + 3"}})

    with pytest.raises(ValidationError):
        discover_candidates(_text_blocks(["The problem is 4 + 3."]))


# The discovery prompt is the gate every candidate passes through; only the
# answer forms it names get flagged. Downstream v3 strategies also render
# non-arithmetic answers -- pair_elimination selects a value from a list,
# ray_shade graphs an inequality's ray, and the M22 rotation strategy stages a
# rigid-motion image. When the prompt described only "a specific quantity that
# can be computed", the rotation fixture ("Rotate the triangle 90° about the
# point, three times. Where does it land?") returned zero candidates and the
# UI showed "No solvable problems found in this document", which is what this
# regression guards against.
_EXPECTED_ADMITTED_ANSWER_FORMS = (
    "computed quantity",
    "selected from a stated collection",
    "graphed region on a number line",
    "image produced by a stated geometric transformation",
)


@pytest.mark.parametrize("phrase", _EXPECTED_ADMITTED_ANSWER_FORMS)
def test_discovery_prompt_admits_every_answer_form_the_pipeline_can_render(phrase):
    from app.pipeline.discovery import _DISCOVERY_SYSTEM_PROMPT

    assert phrase in _DISCOVERY_SYSTEM_PROMPT


def _load_fixture_builder():
    """Import `eval/generate_fixtures.py` off-path so the test covers the exact
    artifact the manual-upload runbook uses. Reimplementing the deck locally
    would let this regression stay green while a change to the real fixture
    silently broke the workshop upload -- the very failure mode this test
    exists to catch.
    """
    import importlib.util
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    fixtures_module_path = repo_root / "eval" / "generate_fixtures.py"
    spec = importlib.util.spec_from_file_location(
        "eval_generate_fixtures", fixtures_module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@patch("app.pipeline.discovery.call_with_tool")
def test_discover_candidates_flags_rotation_problem_on_real_fixture(mock_call, tmp_path):
    """End-to-end guard for the M22 rotation fixture: build the deck through
    `eval/generate_fixtures.py::build_rotation_test_deck` (the same builder the
    manual-upload runbook uses), parse it, then run real discovery against a
    Bedrock stub that returns the excerpt the parsed deck actually contains.
    The candidate must survive grounding and reach the frontend as a Candidate,
    so the upload flow does not empty out on "No solvable problems found in
    this document" the next time this deck is uploaded.
    """
    from app.pipeline.discovery import discover_candidates_for_document
    from app.pipeline.parsing import extract_slide_blocks

    fixture_builder = _load_fixture_builder()
    pptx_path = tmp_path / "rotation_test_deck.pptx"
    fixture_builder.build_rotation_test_deck(pptx_path)
    slide_blocks = extract_slide_blocks(pptx_path)

    # Pick the excerpt out of the parsed deck itself rather than hardcoding
    # it, so the test tracks whatever prose the fixture builder chooses to
    # ship. "Rotation" is the slide's title block; the problem text is the
    # other text block, which is what a compliant LLM would flag.
    text_blocks = [
        block.text
        for block in slide_blocks[0]
        if block.kind == "text" and block.text.strip().lower() != "rotation"
    ]
    assert len(text_blocks) == 1, text_blocks
    excerpt = text_blocks[0]

    mock_call.return_value = (
        "report_candidates",
        {
            "candidates": [
                {
                    "source_excerpt": excerpt,
                    "slide_index": 0,
                    "one_line_summary": "Rotate a triangle three times",
                }
            ]
        },
    )

    candidates = discover_candidates_for_document(slide_blocks)

    assert len(candidates) == 1
    assert candidates[0].source_excerpt == excerpt
    assert candidates[0].slide_index == 0
