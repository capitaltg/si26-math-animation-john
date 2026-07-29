# Meta-template Demo Fixture Deck Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and visually verify a four-slide PowerPoint fixture containing extraction-friendly problems outside the current static animation-template contracts.

**Architecture:** Author a 1280×720 deck with `@oai/artifact-tool` in an external temporary workspace, adapting the sparse Codex Grid slide-01/slide-26 composition into two alternating silhouettes. Export only the final PPTX into `eval/fixtures`; keep source, previews, layouts, inspection output, and QA artifacts in scratch.

**Tech Stack:** Plain JavaScript ES modules, `@oai/artifact-tool`, PowerPoint `.pptx`, bundled presentation render/QA tools.

## Global Constraints

- Final path: `eval/fixtures/meta_template_unsupported_shapes_deck.pptx`.
- Exactly four slides and one complete problem statement per slide.
- No answers, hints, formulas, standards codes, diagrams, or decorative images.
- 16:9 white canvas, black Helvetica Neue/Arial type, light gray structure, one blue accent.
- Category label at least 24pt; problem text at least 35pt.
- Use only `@oai/artifact-tool` to author and export the deck.
- Do not add a repository-local generator or scratch artifacts.

---

### Task 1: Initialize artifact workspace and author the deck

**Files:**
- Create in external scratch: `tmp/create-deck.mjs`
- Create in repository: `eval/fixtures/meta_template_unsupported_shapes_deck.pptx`

**Interfaces:**
- Produces: four editable PowerPoint slides.
- Produces in scratch: slide PNGs, layout JSON, montage, and inspection NDJSON.

- [ ] **Step 1: Create the external workspace**

Use the host temporary directory and initialize artifact-tool resolution:

```bash
node "$SKILL_DIR/container_tools/setup_artifact_tool_workspace.mjs" \
  --workspace "$TMP_DIR"
```

- [ ] **Step 2: Author a plain `.mjs` deck builder**

Create a `Presentation` with `{ width: 1280, height: 720 }`. For each problem:

- add a white slide;
- add one pale-gray structural block;
- add one blue accent rule;
- add one short category label;
- add the complete question in one dominant textbox;
- name every element for inspection.

Use the exact content approved in the design specification. Adapt the Codex Grid
slide-01/slide-26 frames and typography hierarchy, alternating accent placement
without changing extraction order.

- [ ] **Step 3: Export all QA artifacts and the final PPTX**

The builder exports:

- `preview/slide-01.png` through `slide-04.png`;
- `layout/slide-01.layout.json` through `slide-04.layout.json`;
- `qa/deck-montage.webp`;
- `qa/inspection.ndjson`;
- final `eval/fixtures/meta_template_unsupported_shapes_deck.pptx`.

- [ ] **Step 4: Run the builder**

```bash
node "$TMP_DIR/create-deck.mjs"
```

Expected: exit zero and all outputs exist.

### Task 2: Render and inspect the final deck

**Files:**
- No additional repository files.

**Interfaces:**
- Verifies visual layout, text, slide count, and PowerPoint bounds.

- [ ] **Step 1: Render the final PPTX independently**

```bash
python "$SKILL_DIR/container_tools/render_slides.py" "$FINAL_PPTX"
```

Expected: four rendered slide PNGs.

- [ ] **Step 2: Create an independent montage**

```bash
python "$SKILL_DIR/container_tools/create_montage.py" \
  --input_dir "<rendered-slide-directory>" \
  --output_file "$QA_DIR/final-montage.png"
```

- [ ] **Step 3: Inspect all slides visually**

View the montage for consistency, then open every rendered slide at full size.
Fix any clipping, unexpected wrapping, low contrast, unintended overlap, or
text-order ambiguity and repeat export/render.

- [ ] **Step 4: Run bounds validation**

```bash
python "$SKILL_DIR/container_tools/slides_test.py" "$FINAL_PPTX"
```

Expected: no overflow or overlap errors.

- [ ] **Step 5: Verify content and slide count**

Use artifact-tool inspection plus the PPTX slide XML to confirm:

- four slides;
- one intended question and one category label on each;
- no answer text;
- expected problem strings appear exactly once.

### Task 3: Repository verification and integration

**Files:**
- Verify: `eval/fixtures/meta_template_unsupported_shapes_deck.pptx`

**Interfaces:**
- Produces: validated fixture on local `main`.

- [ ] **Step 1: Inspect repository status and file metadata**

Confirm the final PPTX is the only implementation artifact added and that
pre-existing `CLAUDE.md` remains untouched.

- [ ] **Step 2: Commit the fixture branch**

```bash
git add eval/fixtures/meta_template_unsupported_shapes_deck.pptx
git commit -m "test: add meta-template demo fixture deck"
```

- [ ] **Step 3: Merge locally after verification**

Fast-forward local `main`, verify the PPTX still renders to four slides, then
remove the temporary worktree and branch.
