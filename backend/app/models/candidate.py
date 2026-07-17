from pydantic import BaseModel


class Candidate(BaseModel):
    candidate_id: str
    source_excerpt: str
    slide_index: int
    one_line_summary: str
