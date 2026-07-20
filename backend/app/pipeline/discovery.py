from uuid import uuid4

from pydantic import BaseModel

from app.models.candidate import Candidate
from app.pipeline.bedrock_client import call_with_tool
from app.pipeline.parsing import chunk_slide_texts

_DISCOVERY_SYSTEM_PROMPT = (
    "You find candidate K-8 math example problems in slide text. Only flag text that "
    "states a concrete solvable math problem with numbers — ignore dates, page numbers, "
    "standards codes (e.g. 3.OA.A.1), and student counts that are not part of a math problem. "
    "Do not state a computed answer or include the final answer in one_line_summary."
)


class _DiscoveredItem(BaseModel):
    source_excerpt: str
    slide_index: int
    one_line_summary: str


class _DiscoveryResult(BaseModel):
    candidates: list[_DiscoveredItem]


def _normalize_for_grounding(text: str) -> str:
    return " ".join(text.split()).casefold()


def _is_grounded(item: _DiscoveredItem, slide_texts: list[str], start_index: int) -> bool:
    local_index = item.slide_index - start_index
    if not 0 <= local_index < len(slide_texts):
        return False

    excerpt = _normalize_for_grounding(item.source_excerpt)
    slide_text = _normalize_for_grounding(slide_texts[local_index])
    return bool(excerpt) and excerpt in slide_text


def discover_candidates(slide_texts: list[str], start_index: int = 0) -> list[Candidate]:
    numbered = "\n".join(f"[slide {start_index + i}] {text}" for i, text in enumerate(slide_texts))
    schema = _DiscoveryResult.model_json_schema()
    result = call_with_tool(
        system_prompt=_DISCOVERY_SYSTEM_PROMPT,
        user_message=numbered,
        tool_name="report_candidates",
        tool_schema=schema,
    )
    parsed = _DiscoveryResult.model_validate(result)
    return [
        Candidate(
            candidate_id=str(uuid4()),
            source_excerpt=item.source_excerpt,
            slide_index=item.slide_index,
            one_line_summary=item.one_line_summary,
        )
        for item in parsed.candidates
        if _is_grounded(item, slide_texts, start_index)
    ]


def discover_candidates_for_document(slide_texts: list[str], chunk_size: int = 25) -> list[Candidate]:
    all_candidates: list[Candidate] = []
    for chunk_index, chunk in enumerate(chunk_slide_texts(slide_texts, chunk_size=chunk_size)):
        start_index = chunk_index * chunk_size
        all_candidates.extend(discover_candidates(chunk, start_index=start_index))
    return all_candidates
