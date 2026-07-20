# Ordered-Token Candidate Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace contiguous-substring candidate grounding with deterministic ordered-token grounding so faithful noncontiguous excerpts survive while invented or altered content remains rejected.

**Architecture:** Keep candidate grounding inside `app.pipeline.discovery` at the existing Bedrock trust boundary. Tokenize the returned excerpt and its reported slide locally, then require the excerpt tokens to be an ordered subsequence of the slide tokens after removing only presentation syntax; no API, model, or persistence changes are needed.

**Tech Stack:** Python 3.11+, standard-library `re`, Pydantic v2, pytest, AWS Bedrock for the final live acceptance run.

## Global Constraints

- Preserve the chunk-range check before accessing a reported slide.
- Preserve words, integers, decimals, fractions, and arithmetic operators as exact tokens.
- Ignore only whitespace, presentation punctuation, and literal bracketed `[blank]` placeholders.
- Do not add fuzzy thresholds, embeddings, dependencies, model calls, templates, or public API changes.
- Every production behavior change must begin with a failing automated test.
- Live Bedrock output is acceptance evidence, not the regression test.

---

### Task 1: Implement ordered-token grounding

**Files:**
- Modify: `backend/tests/pipeline/test_discovery.py`
- Modify: `backend/app/pipeline/discovery.py`

**Interfaces:**
- Consumes: `_DiscoveredItem`, `discover_candidates(slide_texts: list[str], start_index: int = 0) -> list[Candidate]`
- Produces: `_tokenize_for_grounding(text: str) -> list[str]`, `_is_ordered_subsequence(needle: list[str], haystack: list[str]) -> bool`, and the revised `_is_grounded(item: _DiscoveredItem, slide_texts: list[str], start_index: int) -> bool`

- [ ] **Step 1: Add the failing Grade 7 regression test**

Append this public-behavior test to `backend/tests/pipeline/test_discovery.py`:

```python
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
```

- [ ] **Step 2: Run the regression test and verify red**

Run:

```bash
cd backend
.venv/bin/pytest tests/pipeline/test_discovery.py::test_discover_candidates_accepts_ordered_noncontiguous_slide_tokens -v
```

Expected: FAIL because `candidates` is empty; the current normalized whole-string substring check cannot cross the omitted `Source:` text or tolerate table separators/placeholders.

- [ ] **Step 3: Add safety characterization tests before relaxing grounding**

Add `import pytest` below the existing imports, then append:

```python
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
```

- [ ] **Step 4: Run all discovery tests and confirm the safety baseline**

Run:

```bash
cd backend
.venv/bin/pytest tests/pipeline/test_discovery.py -v
```

Expected: the new Grade 7 regression remains the only failure. The changed-operator, changed-number, reordered-content, placeholder-only, fabricated-excerpt, and out-of-range tests pass under the stricter old matcher.

- [ ] **Step 5: Implement the minimal ordered-token matcher**

In `backend/app/pipeline/discovery.py`, import `re`, strengthen the prompt contract, replace `_normalize_for_grounding`, and revise `_is_grounded` as follows:

```python
import re
from uuid import uuid4

from pydantic import BaseModel

from app.models.candidate import Candidate
from app.pipeline.bedrock_client import call_with_tool
from app.pipeline.parsing import chunk_slide_texts

_DISCOVERY_SYSTEM_PROMPT = (
    "You find candidate K-8 math example problems in slide text. Only flag text that "
    "states a concrete solvable math problem with numbers — ignore dates, page numbers, "
    "standards codes (e.g. 3.OA.A.1), and student counts that are not part of a math problem. "
    "Copy source_excerpt verbatim from the reported slide; do not paraphrase it. "
    "Do not state a computed answer or include the final answer in one_line_summary."
)

_BLANK_PLACEHOLDER_RE = re.compile(r"\[\s*blank\s*\]")
_GROUNDING_TOKEN_RE = re.compile(
    r"\d+(?:[./]\d+)*|[^\W\d_]+(?:'[^\W\d_]+)*|[+\-−×·÷=]"
)


def _tokenize_for_grounding(text: str) -> list[str]:
    normalized = text.casefold().replace("’", "'")
    normalized = _BLANK_PLACEHOLDER_RE.sub(" ", normalized)
    return _GROUNDING_TOKEN_RE.findall(normalized)


def _is_ordered_subsequence(needle: list[str], haystack: list[str]) -> bool:
    if not needle:
        return False
    haystack_iter = iter(haystack)
    return all(
        any(candidate == token for candidate in haystack_iter)
        for token in needle
    )


def _is_grounded(item: _DiscoveredItem, slide_texts: list[str], start_index: int) -> bool:
    local_index = item.slide_index - start_index
    if not 0 <= local_index < len(slide_texts):
        return False

    excerpt_tokens = _tokenize_for_grounding(item.source_excerpt)
    slide_tokens = _tokenize_for_grounding(slide_texts[local_index])
    return _is_ordered_subsequence(excerpt_tokens, slide_tokens)
```

- [ ] **Step 6: Assert the strengthened prompt contract**

Extend `test_discover_candidates_wraps_bedrock_response_into_candidates` with:

```python
    assert "verbatim" in mock_call.call_args.kwargs["system_prompt"]
```

- [ ] **Step 7: Run focused tests and verify green**

Run:

```bash
cd backend
.venv/bin/pytest tests/pipeline/test_discovery.py -v
```

Expected: all discovery tests PASS, including the Grade 7 regression and every safety case.

- [ ] **Step 8: Run the full deterministic verification gate**

Run from the repository root:

```bash
backend/.venv/bin/pytest -q backend/tests
backend/.venv/bin/python -m compileall -q backend/app backend/tests eval
backend/.venv/bin/pip check
git diff --check
```

Expected: all backend tests pass, compilation emits no errors, `pip check` reports `No broken requirements found.`, and `git diff --check` emits no output.

- [ ] **Step 9: Commit the implementation**

```bash
git add backend/app/pipeline/discovery.py backend/tests/pipeline/test_discovery.py
git commit -m "fix: accept grounded noncontiguous excerpts"
```

---

### Task 2: Verify against real PPTX decks

**Files:**
- Read: `eval set/*.pptx` (local, ignored fixtures)
- Read: `eval/run_eval.py`
- No repository files are modified by this task.

**Interfaces:**
- Consumes: `run_fixture(pptx_path: Path) -> dict` and the user-approved AWS Bedrock connection
- Produces: live acceptance evidence that real proportional-table excerpts pass grounding without weakening the synthetic zero-candidate fixture

- [ ] **Step 1: Rerun the three synthetic acceptance fixtures**

Run from the repository root:

```bash
backend/.venv/bin/python eval/run_eval.py
```

Expected: `zero_candidate_deck.pptx` produces 0 candidates, `distractor_heavy_deck.pptx` produces the grounded apples candidate without date/standard/page-number false positives, and `ambiguous_phrasing_deck.pptx` does not promote its under-specified prompt.

- [ ] **Step 2: Rerun all six approved real decks and print per-deck counts**

Run from the repository root:

```bash
backend/.venv/bin/python -c 'from pathlib import Path; from eval.run_eval import run_fixture; reports=[run_fixture(path) for path in sorted(Path("eval set").glob("*.pptx"))]; [print("{}: {}".format(report["fixture"], report["candidate_count"])) for report in reports]'
```

Expected: `g7 u2 l2.pptx` produces grounded proportional-table candidates instead of the previous false zero when Bedrock reports them. Exact counts may vary because this is a live model call, but every accepted excerpt must still satisfy local ordered-token grounding.

- [ ] **Step 3: Confirm the working tree remains clean**

Run:

```bash
git status --short
```

Expected: no output. The real decks and generated fixture PPTX files remain ignored, and the acceptance run creates no tracked artifacts.
