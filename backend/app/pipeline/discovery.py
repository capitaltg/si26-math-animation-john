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
    "see, as long as it asks for a specific quantity that can be computed from numbers given "
    "in the text — flag that sub-question. "
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


def _is_ordered_subsequence(needle: list[str], haystack: list[str]) -> bool:
    if not needle:
        return False
    haystack_iter = iter(haystack)
    return all(
        any(candidate == token for candidate in haystack_iter)
        for token in needle
    )


def _contiguous_in_any_block(prefix: list[str], text_blocks: list[Block]) -> bool:
    if not prefix:
        return True
    prefix_len = len(prefix)
    for block in text_blocks:
        block_tokens = tokenize_for_grounding(block.text)
        for i in range(len(block_tokens) - prefix_len + 1):
            if block_tokens[i:i + prefix_len] == prefix:
                return True
    return False


def _is_excerpt_grounded(excerpt_tokens: list[str], blocks: list[Block]) -> bool:
    if not excerpt_tokens:
        return False

    text_blocks = [block for block in blocks if block.kind == "text"]
    tables: dict[int, list[str]] = {}
    for block in blocks:
        if block.kind == "cell":
            tables.setdefault(block.table_ord, []).extend(
                tokenize_for_grounding(block.text)
            )

    for split in range(len(excerpt_tokens) + 1):
        prefix, suffix = excerpt_tokens[:split], excerpt_tokens[split:]
        if not _contiguous_in_any_block(prefix, text_blocks):
            continue
        if not suffix:
            return True
        if any(
            _is_ordered_subsequence(suffix, table_tokens)
            for table_tokens in tables.values()
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
