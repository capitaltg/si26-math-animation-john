from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.models.candidate import Candidate
from app.pipeline.bedrock_client import call_with_tool
from app.pipeline.grounding import tokenize_for_grounding
from app.pipeline.parsing import Block, chunk_slide_blocks, flatten_blocks

_DISCOVERY_SYSTEM_PROMPT = (
    "You find candidate K-8 math example problems in slide text. Only flag text that "
    "states a concrete solvable math problem with numbers — ignore dates, page numbers, "
    "standards codes (e.g. 3.OA.A.1), and student counts that are not part of a math problem. "
    "A question still counts as solvable even when phrased as classroom discussion "
    "(\"turn and tell\", \"how do you know\", \"why?\") or bundled with a diagram you cannot "
    "see, as long as it asks for a specific answer that follows from the numbers given in "
    "the text — a computed quantity, a value selected from a stated collection (e.g. the "
    "median of a listed set), a graphed region on a number line (e.g. the solution to an "
    "inequality), or the image produced by a stated geometric transformation (e.g. rotate "
    "a polygon N times about a point) — flag that sub-question. "
    "Copy source_excerpt verbatim from the reported slide; do not paraphrase it. "
    "Do not state a computed answer or include the final answer in one_line_summary."
)


class _DiscoveredItem(BaseModel):
    source_excerpt: str
    slide_index: int
    one_line_summary: str


class _DiscoveryResult(BaseModel):
    candidates: list[_DiscoveredItem]


class _DiscoveryEnvelope(BaseModel):
    candidates: list[Any]


def _suffix_from_table_rectangle(
    suffix: list[str],
    cells_by_coord: dict[tuple[int, int], list[str]],
) -> bool:
    """True iff `suffix` equals the exact row-major concatenation of every
    cell in some contiguous sub-rectangle of one table.

    A sub-rectangle is a contiguous span of the table's row indices and a
    contiguous span of its column indices; every cell inside it (origin
    cells of merged regions included, spanned duplicates excluded upstream)
    contributes its tokens in row-major order. Requiring a rectangle keeps
    the label/value relationship intact: for a 2x2 table
    `width | 4 // height | 6`, "width 6" cannot bind because no rectangle
    contains cell (0,0) and cell (1,1) without also containing (0,1) and
    (1,0), so the concatenation would include "4" and "height" too.
    """
    if not suffix or not cells_by_coord:
        return False
    rows = sorted({r for r, _ in cells_by_coord})
    cols = sorted({c for _, c in cells_by_coord})
    suffix_len = len(suffix)
    for i, r1 in enumerate(rows):
        for r2 in rows[i:]:
            row_slice = [r for r in rows if r1 <= r <= r2]
            for j, c1 in enumerate(cols):
                for c2 in cols[j:]:
                    col_slice = [c for c in cols if c1 <= c <= c2]
                    concat: list[str] = []
                    overflow = False
                    for r in row_slice:
                        if overflow:
                            break
                        for c in col_slice:
                            concat.extend(cells_by_coord.get((r, c), ()))
                            if len(concat) > suffix_len:
                                overflow = True
                                break
                    if not overflow and concat == suffix:
                        return True
    return False


def _contiguous_in_any_block(prefix: list[str], block_token_lists: list[list[str]]) -> bool:
    if not prefix:
        return True
    prefix_len = len(prefix)
    for block_tokens in block_token_lists:
        for i in range(len(block_tokens) - prefix_len + 1):
            if block_tokens[i:i + prefix_len] == prefix:
                return True
    return False


def _is_excerpt_grounded(excerpt_tokens: list[str], blocks: list[Block]) -> bool:
    if not excerpt_tokens:
        return False

    text_token_lists: list[list[str]] = []
    tables_blocks: dict[int, list[Block]] = {}
    for block in blocks:
        if block.kind == "text":
            text_token_lists.append(tokenize_for_grounding(block.text))
        else:
            tables_blocks.setdefault(block.table_ord, []).append(block)

    tables_by_coord: list[dict[tuple[int, int], list[str]]] = []
    all_cell_token_lists: list[list[str]] = []
    for cells in tables_blocks.values():
        cell_tokens = [tokenize_for_grounding(cell.text) for cell in cells]
        all_cell_token_lists.extend(cell_tokens)
        # A table with fully populated row/col indices can splice cells that
        # form a contiguous sub-rectangle. A legacy or hand-built table
        # missing that geometry falls back to single-cell containment only —
        # never cross-cell splicing — because relationship-preserving
        # rectangle checks require the actual coordinates.
        if all(cell.row is not None and cell.col is not None for cell in cells):
            tables_by_coord.append(
                {(cell.row, cell.col): tokens for cell, tokens in zip(cells, cell_tokens)}
            )

    # An excerpt entirely contained in one cell (a self-contained problem
    # typed straight into a table, common in K-8 decks) grounds directly.
    # This is single-block contiguity, the same guarantee text blocks get,
    # so it can't recombine tokens across cells or tables — it never
    # touches the cross-table suffix path below.
    if _contiguous_in_any_block(excerpt_tokens, all_cell_token_lists):
        return True

    for split in range(len(excerpt_tokens) + 1):
        prefix, suffix = excerpt_tokens[:split], excerpt_tokens[split:]
        if not _contiguous_in_any_block(prefix, text_token_lists):
            break
        if not suffix:
            return True
        if any(
            _suffix_from_table_rectangle(suffix, cells_by_coord)
            for cells_by_coord in tables_by_coord
        ):
            return True
    return False


def _is_grounded(item: _DiscoveredItem, slide_blocks: list[list[Block]], start_index: int) -> bool:
    local_index = item.slide_index - start_index
    if not 0 <= local_index < len(slide_blocks):
        return False

    excerpt_tokens = tokenize_for_grounding(item.source_excerpt)
    return _is_excerpt_grounded(excerpt_tokens, slide_blocks[local_index])


def discover_candidates(slide_blocks: list[list[Block]], start_index: int = 0) -> list[Candidate]:
    numbered = "\n".join(
        f"[slide {start_index + i}] {flatten_blocks(blocks)}"
        for i, blocks in enumerate(slide_blocks)
    )
    schema = _DiscoveryResult.model_json_schema()
    _, result = call_with_tool(
        system_prompt=_DISCOVERY_SYSTEM_PROMPT,
        user_message=numbered,
        tools=[{"name": "report_candidates", "schema": schema}],
    )
    parsed = _DiscoveryEnvelope.model_validate(result)
    candidates: list[Candidate] = []
    for raw_item in parsed.candidates:
        try:
            item = _DiscoveredItem.model_validate(raw_item)
        except ValidationError:
            continue
        if _is_grounded(item, slide_blocks, start_index):
            candidates.append(
                Candidate(
                    candidate_id=str(uuid4()),
                    source_excerpt=item.source_excerpt,
                    slide_index=item.slide_index,
                    one_line_summary=item.one_line_summary,
                )
            )
    return candidates


def discover_candidates_for_document(
    slide_blocks: list[list[Block]], chunk_size: int = 25
) -> list[Candidate]:
    all_candidates: list[Candidate] = []
    for chunk_index, chunk in enumerate(chunk_slide_blocks(slide_blocks, chunk_size=chunk_size)):
        start_index = chunk_index * chunk_size
        all_candidates.extend(discover_candidates(chunk, start_index=start_index))
    return all_candidates
