# Chain Feature Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a three-slide PowerPoint fixture whose independently discoverable number-line problems form the continuous chain `3 → 7 → 2 → 8`.

**Architecture:** Extend the established `python-pptx` fixture generator rather than introducing a second deck-generation path. A focused harness test opens the generated deck and verifies slide count, titles, and exact prompt text so the arithmetic handoffs cannot silently regress.

**Tech Stack:** Python 3.11+, python-pptx, pytest, LibreOffice/Poppler slide rendering tools.

## Global Constraints

- The fixture contains exactly three slides with one complete number-line problem per slide.
- Each problem's result is the next problem's starting value: `3 + 4 = 7`, `7 - 5 = 2`, `2 + 6 = 8`.
- Each slide remains independently discoverable so the storyboard initially builds three solo scenes.
- Preserve all existing fixture builders and generated fixture names.
- Generated `.pptx` files remain ignored local artifacts under `eval/fixtures/`.

---

### Task 1: Add and verify the continuous chain fixture

**Files:**
- Modify: `eval/generate_fixtures.py`
- Modify: `backend/tests/test_eval_harness.py`
- Generate: `eval/fixtures/chain_test_deck.pptx` (ignored local artifact)

**Interfaces:**
- Consumes: `_new_presentation() -> tuple[Presentation, SlideLayout]`.
- Produces: `build_chain_test_deck(path: Path) -> None`, generating a three-slide deck; `main()` writes it as `chain_test_deck.pptx`.

- [ ] **Step 1: Write the failing fixture-content test**

Replace `test_fixture_builders_write_all_three_decks` in
`backend/tests/test_eval_harness.py` with:

```python
def test_fixture_builders_write_all_four_decks(tmp_path):
    from pptx import Presentation

    from eval.generate_fixtures import (
        build_ambiguous_phrasing_deck,
        build_chain_test_deck,
        build_distractor_heavy_deck,
        build_zero_candidate_deck,
    )

    builders = [
        build_zero_candidate_deck,
        build_distractor_heavy_deck,
        build_ambiguous_phrasing_deck,
        build_chain_test_deck,
    ]
    paths = [tmp_path / f"fixture_{index}.pptx" for index in range(4)]

    for builder, path in zip(builders, paths):
        builder(path)

    assert all(path.exists() and path.stat().st_size > 0 for path in paths)

    chain_deck = Presentation(paths[-1])
    assert len(chain_deck.slides) == 3
    assert [
        (slide.shapes.title.text, slide.placeholders[1].text)
        for slide in chain_deck.slides
    ] == [
        (
            "Problem 1",
            "A frog is sitting on 3. It jumps forward 4 spaces. Where does it land?",
        ),
        (
            "Problem 2",
            "Start at 7. Move back 5. What number are you on?",
        ),
        (
            "Problem 3",
            "A snail starts at 2. It crawls forward 6. What number does it reach?",
        ),
    ]
```

- [ ] **Step 2: Run the test and confirm the chain assertion fails**

Run from the repository root:

```bash
backend/.venv/bin/pytest backend/tests/test_eval_harness.py::test_fixture_builders_write_all_four_decks -v
```

Expected: FAIL because slide 2 currently says `Start at 8`, not `Start at 7`.

- [ ] **Step 3: Make the second problem start from the first result**

In `build_chain_test_deck`, set the three slide bodies exactly to:

```python
slide1.placeholders[1].text = (
    "A frog is sitting on 3. It jumps forward 4 spaces. Where does it land?"
)
slide2.placeholders[1].text = "Start at 7. Move back 5. What number are you on?"
slide3.placeholders[1].text = (
    "A snail starts at 2. It crawls forward 6. What number does it reach?"
)
```

Keep `main()` generating:

```python
build_chain_test_deck(FIXTURES_DIR / "chain_test_deck.pptx")
```

- [ ] **Step 4: Run the focused and full harness tests**

Run:

```bash
backend/.venv/bin/pytest backend/tests/test_eval_harness.py -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Generate and validate the fixture artifact**

Run:

```bash
backend/.venv/bin/python eval/generate_fixtures.py
backend/.venv/bin/python -c 'from pathlib import Path; from app.pipeline.parsing import extract_slide_texts; p = Path("eval/fixtures/chain_test_deck.pptx"); texts = extract_slide_texts(p); assert len(texts) == 3; assert "3" in texts[0] and "4" in texts[0]; assert "7" in texts[1] and "5" in texts[1]; assert "2" in texts[2] and "6" in texts[2]; print(texts)'
```

Expected: generator reports `Wrote fixtures to .../eval/fixtures`, followed by
the three extracted slide texts in chain order.

- [ ] **Step 6: Render and visually inspect all slides**

Run:

```bash
backend/.venv/bin/python /Users/ctg/.codex/plugins/cache/openai-primary-runtime/presentations/26.715.12143/skills/presentations/container_tools/render_slides.py eval/fixtures/chain_test_deck.pptx
backend/.venv/bin/python /Users/ctg/.codex/plugins/cache/openai-primary-runtime/presentations/26.715.12143/skills/presentations/container_tools/slides_test.py eval/fixtures/chain_test_deck.pptx
```

Expected: three PNG previews are produced; `slides_test.py` reports no slide
overflow. Inspect every PNG at full size and confirm titles and prompts are
fully visible with no clipping or unintended overlap.

- [ ] **Step 7: Commit the source and test**

```bash
git add eval/generate_fixtures.py backend/tests/test_eval_harness.py
git commit -m "test: add continuous chain fixture deck"
```

Do not add `eval/fixtures/chain_test_deck.pptx`; generated fixture decks are
ignored local artifacts.
