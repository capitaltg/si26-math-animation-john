# Eval-Set Timing Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the live sequential processing time of each real evaluation PPTX and record the results in a reproducible standalone Markdown report.

**Architecture:** Invoke the existing `eval.run_eval.run_fixture(path)` interface once per deck in sorted order, measuring every complete call with `time.perf_counter()`. Capture candidate counts, per-deck wall times, and an independently measured total, then write only the requested documentation artifact.

**Tech Stack:** Python 3.14 virtual environment, standard-library `time` and `json`, existing PPTX extraction pipeline, AWS Bedrock, Markdown.

## Global Constraints

- Run all six files from `eval set/` sequentially in sorted filename order.
- Measure each complete `run_fixture(path)` call with `time.perf_counter()`.
- Use the configured live AWS Bedrock model without mocks or concurrency.
- The user explicitly approved sending extracted slide contents from these six local PPTX files to AWS Bedrock.
- Do not print credentials, modify source decks, add a reusable benchmark script, or change production behavior.
- Report per-deck times, the independently measured total, and the total divided by six as the arithmetic mean.
- Round displayed times to two decimal places and disclose live-model latency/count variability.

---

### Task 1: Measure and document real-deck processing time

**Files:**
- Read: `eval set/*.pptx`
- Read: `eval/run_eval.py`
- Create: `docs/eval-set-timing-2026-07-20.md`

**Interfaces:**
- Consumes: `run_fixture(pptx_path: Path) -> dict`
- Produces: a Markdown timing report with one measured row per deck, total time, average time, counts, method, caveats, and reproduction command

- [ ] **Step 1: Verify the input set and clean starting state**

Run:

```bash
find "eval set" -maxdepth 1 -type f -name "*.pptx" | sort
git status --short
```

Expected: exactly the six approved deck paths are printed and the working tree has no uncommitted changes.

- [ ] **Step 2: Run the sequential live timing measurement**

Run from the repository root:

```bash
backend/.venv/bin/python -c 'import json, time; from pathlib import Path; from eval.run_eval import run_fixture; from app.config import get_settings; paths=sorted(Path("eval set").glob("*.pptx")); started=time.perf_counter(); rows=[]; [(lambda deck_started, path: rows.append({"fixture": (report := run_fixture(path))["fixture"], "candidate_count": report["candidate_count"], "elapsed_seconds": time.perf_counter() - deck_started}))(time.perf_counter(), path) for path in paths]; total=time.perf_counter()-started; print(json.dumps({"model": get_settings().bedrock_model_id, "deck_count": len(rows), "total_seconds": total, "average_seconds": total / len(rows), "decks": rows}, indent=2))'
```

Expected: exit code 0 and JSON containing `deck_count: 6`, the configured model, six fixture/count/time objects, an independently measured total, and the total divided by six. If sandbox DNS blocks Bedrock, rerun the identical command with approved network escalation; do not substitute mocks.

- [ ] **Step 3: Create the timing report from the successful output**

Use `apply_patch` to create `docs/eval-set-timing-2026-07-20.md`. Start with the
heading `# Eval-Set Processing Time`, identify the exact model returned by Step
2, and state that the current `main` pipeline processed all decks sequentially
on 2026-07-20. Add a three-column Markdown table named `Deck`, `Candidates`,
and `Processing time`, with the six Step 2 rows in their measured order. Format
every elapsed value as seconds with two decimal places.

Below the table, record the independently measured `total_seconds` and
`average_seconds`, each rounded to two decimal places. Explain that each timer
wraps the complete `run_fixture(path)` call: PPTX text extraction, live Bedrock
discovery, response validation, and local ordered-token grounding. State that
the decks ran without mocks or concurrency, and that live Bedrock counts and
latency can vary.

Finish with a `To reproduce` section containing the exact Step 2 command
verbatim. Do not include credentials or raw slide content.

- [ ] **Step 4: Verify the artifact**

Run:

```bash
sed -n '1,240p' docs/eval-set-timing-2026-07-20.md
git diff --check
git status --short
```

Expected: the report contains six unique deck rows, all displayed times have two decimal places, total and average match the raw successful output after rounding, `git diff --check` emits no output, and only the report is untracked.

- [ ] **Step 5: Commit the report**

```bash
git add docs/eval-set-timing-2026-07-20.md
git commit -m "docs: record eval set processing time"
```
