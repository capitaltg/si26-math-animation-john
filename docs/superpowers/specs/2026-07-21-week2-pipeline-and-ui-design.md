# Week 2 Design: Classification/Extraction Pipeline, Fallback Routing, New Templates, and Web App

**Date:** 2026-07-21
**Status:** Approved (design phase)
**Predecessor:** Week 1 foundation is complete (`docs/superpowers/plans/2026-07-17-week1-foundation.md`), hardened per `docs/superpowers/specs/2026-07-20-week1-review-remediation-design.md`. 59 backend tests pass.

## 1. Goal

Turn the Week 1 backend primitives into a working vertical slice a teacher can drive from a browser: upload a PPTX, see discovered candidate problems, select which to visualize, and get downloadable MP4 clips — with honest, clearly-labeled fallback for anything that doesn't classify or render cleanly.

This is Week 2 of the 4-week MVP per `project description.md` Section 11. It wires the classification/grade-inference call, parameter extraction, schema validation, and the retry/fallback control flow; adds three templates; and stands up the first FastAPI routes and a React frontend covering upload → candidate selection → trigger render.

## 2. Scope

**In scope:**
- Bedrock classification + grade-inference call per selected candidate.
- A single per-candidate orchestrator (`process_scene`) owning the classify → extract → validate → render flow and all fallback/retry decisions.
- Retry/fallback policy distinguishing classification ambiguity (fallback, no retry) from validation/render failure (retry once with backoff, then fallback).
- Three new templates: `text_card` (fallback), `fraction_bar` (partitioned shape), `balance_scale`.
- FastAPI routes: `POST /upload`, `POST /render`, `GET /clips/{id}`.
- In-memory session state keyed by a session cookie (no persistence).
- React + Vite frontend: upload → candidate selection → trigger render → per-clip download / fallback display.
- Synchronous render (blocking request + spinner), justified by the ~3.5s/scene Week 1 latency benchmark.

**Explicitly out of scope (Week 3 or later, not gaps):**
- Fast single-frame thumbnail preview step.
- Storyboard review UI: value editing with re-validation, grade override, approve/reject/retry.
- Multi-step chaining visuals and per-step captioning UI (note: `number_line` already accepts 2-3 steps from Week 1; no *new* multi-step UI this week).
- Galeo auth, output-format customization, icon theming.
- Persistent accounts / cross-session state.

## 3. Architecture

Week 1 delivered independently-testable modules (parsing, discovery, extraction, render, templates). Week 2 adds two pipeline modules, three templates, and a web layer composing the existing modules into routes. The per-candidate decision logic is centralized rather than scattered, per Section 10 of the product doc (classification ambiguity vs. technical failure must stay distinguishable).

### 3.1 Classification (`backend/app/pipeline/classification.py`)

A schema-constrained Bedrock tool call, mirroring the Week 1 discovery/extraction pattern (`call_with_tool`).

- Interface: `classify_candidate(source_text: str) -> ClassificationResult`
- `ClassificationResult` (Pydantic): `template: TemplateName | None`, `grade_level: int` (0..8), `ambiguous: bool`.
- The model returns a template category or flags the candidate as unsupported/ambiguous. `template is None` or `ambiguous is True` both route to fallback.
- Grade level is advisory this week (informs which representation the model picks); a manual override UI is Week 3.
- The LLM never computes arithmetic here — classification only selects a representation and infers grade.

### 3.2 Scene orchestrator (`backend/app/pipeline/process_scene.py`)

The single owner of the per-candidate flow and all fallback/retry policy.

- Interface: `process_scene(candidate: Candidate, output_dir: Path) -> Scene`
- Flow:
  1. `classify_candidate(candidate.source_excerpt)`.
  2. If `ambiguous` or `template is None` → return a fallback `Scene` (`status="fallback"`, `template=TEXT_CARD`, `fallback_reason` describing classification ambiguity). **No retry** — an identical retry against the same input reproduces the same result (Section 10).
  3. Otherwise: `extract_params(source_excerpt, params_cls_for(template))`, which validates against the template's Pydantic schema + guard on construction.
  4. Render via the Week 1 `render_scene_to_mp4` (subprocess-isolated).
  5. Extraction/validation failure **or** render failure → retry once with backoff. On second failure → fallback `Scene` with a `fallback_reason` naming the technical failure (distinct string from the ambiguity reason).
  6. Success → `Scene` with `status="approved"` for Week 2 (no separate review gate yet), `render_path` set.

Backoff is a short fixed sleep between the two attempts (retry policy, not throughput tuning).

### 3.3 Templates (`backend/app/templates/<name>/`)

Each follows the Week 1 layout: `params.py` (Pydantic model + `@model_validator` calling the guard), `guard.py` (pure compatibility function), `scene.py` (Manim `Scene` subclass with a settable `.params`). All three register in `app/templates/registry.py`, and `TemplateName` (in `app/models/scene.py`) gains the three new members.

- **`text_card`** — fallback card. Params: `headline: str`, `lines: list[str]` (non-empty). No arithmetic, no math guard (guard only enforces non-empty content). Scene renders a titled text/equation card. Used whenever `process_scene` falls back.
- **`fraction_bar`** — partitioned shape (fractions/decimals/percentages per Section 6). Params: `start: Fraction`, `steps: list[{operation: "add"|"subtract", amount: Fraction}]` (2-3 steps, single operation family). Guard: all denominators match (Section 8's same-denominator example), and each intermediate running total is non-negative and within a renderable upper bound (a small fixed number of whole units, so a bar/circle stays legible — mixed fractions like 5/2 are allowed, absurd totals are not). All arithmetic in Python via `fractions.Fraction`; the LLM supplies only operands. Pydantic serializes `Fraction` as a string (the `Scene` model already round-trips `Fraction` for `stated_answer`).
- **`balance_scale`** — equations / algebra readiness (Section 6). **v1 scope: a simple `a + b = c` equality visualization** (two pans, both sides shown to balance). Params: `left_terms: list[int]` (2 terms), `right_total: int`. Guard: `sum(left_terms) == right_total` (a mismatch is an invalid extraction → fallback). Higher-grade framing; no variable-solving.

### 3.4 Web backend (`backend/app/main.py`, `backend/app/routes/`, `backend/app/session.py`)

FastAPI app composing the pipeline. `pyproject.toml` already pins `fastapi` and `uvicorn`.

- `POST /upload` (multipart PPTX) → `extract_slide_texts` → `discover_candidates_for_document` → store candidates in session → set session cookie → return `{session_id, candidates: [...]}`.
- `POST /render` (`{candidate_ids: [...]}`) → for each id, look up the candidate in session → `process_scene` sequentially (each render already subprocess-isolated) → return per-clip results `[{candidate_id, status, clip_url?, fallback_reason?}]`. Sequential keeps Week 2 simple; ~3.5s/scene means a handful of clips stays within a tolerable blocking window with a spinner. Parallelization is a later optimization if clip counts grow.
- `GET /clips/{clip_id}` → stream the MP4 file for download. `clip_id` is a server-generated opaque id mapped to a path inside the session's output dir (never a client-supplied path — no path traversal).
- `SessionState` — an in-memory `dict[session_id -> {candidates, output_dir}]`. No database, no cross-restart persistence; matches the product doc's demo scope (state resets on restart / tab close). Session ids are server-generated (`uuid4`), never trusted from the client for anything but lookup.

### 3.4.1 Trust and safety boundaries

- Bedrock output remains untrusted (Week 1 grounding rules carry forward): classification `template` is validated against the `TemplateName` enum; extracted params validated by Pydantic + guard.
- Uploaded files: enforce the 50-slide cap (Section 3) and reject non-PPTX uploads before parsing.
- `clip_id` → path mapping lives server-side; the download route never joins client input into a filesystem path.

### 3.5 Frontend (`frontend/`, React + Vite)

A small SPA calling the FastAPI JSON routes; Vite dev server proxies `/api` (or the chosen prefix) to FastAPI, and CORS is configured for the dev origin.

- **Upload screen** — file picker (PPTX), submit → `POST /upload`.
- **Candidate list** — checkboxes over discovered candidates, each showing `one_line_summary` and `source_excerpt` (source grounding, per Section 8). "Render selected" → `POST /render`.
- **Results** — spinner during the blocking render; then a list where each selected candidate shows either a download link (rendered clip) or a labeled fallback card stating the `fallback_reason`.
- No client-side persistence; refresh resets (demo scope).

## 4. Data Flow

```
Upload PPTX
  → extract_slide_texts → discover_candidates_for_document
  → [candidates] stored in session, returned to UI
Teacher selects candidate_ids
  → POST /render
      for each candidate:
        process_scene:
          classify_candidate
            ├─ ambiguous / unsupported ─────────────→ text_card fallback (no retry)
            └─ template chosen
                 → extract_params (validate + guard)
                 → render_scene_to_mp4 (subprocess)
                      ├─ success ──────────────────→ approved Scene + clip
                      └─ validation/render failure → retry once w/ backoff
                            ├─ success ────────────→ approved Scene + clip
                            └─ fails again ────────→ text_card fallback
  → per-clip results (download url | fallback reason) → UI
```

## 5. Error Handling

- **Classification ambiguity / unsupported topic:** fallback to `text_card`, `fallback_reason` = ambiguity/unsupported message. No retry.
- **Extraction validation failure (schema/guard):** retry once with backoff; second failure → fallback with a technical `fallback_reason`.
- **Render failure/timeout:** same retry-once-then-fallback; Week 1's render worker already preserves the last good artifact and times out at 120s.
- **No candidates found on upload:** return an empty candidate list; UI shows the explicit "no problems found" message (Section 3).
- **Bad upload (non-PPTX, over 50 slides):** 4xx with a clear message; never reaches the pipeline.
- Fallback reason strings for the two paths (ambiguity vs. technical) are distinct so the teacher sees an accurate cause (Section 10).

## 6. Testing Strategy

- **Classification** (`test_classification.py`): Bedrock mocked; asserts enum validation and the `None`/`ambiguous` fields.
- **process_scene** (`test_process_scene.py`): mocked classify/extract/render covering every branch — clean success, ambiguity fallback (no retry, assert classify/extract called the expected number of times), validation-failure retry-then-success, render-failure retry-then-fallback. Assert `fallback_reason` differs by cause.
- **New template guards** (`test_text_card_guard.py`, `test_fraction_bar_guard.py`, `test_balance_scale_guard.py`): valid cases pass; mismatched fraction denominators, negative/oversized fraction totals, and `sum(left) != right` balance mismatches are rejected.
- **Routes** (`test_routes.py`): FastAPI `TestClient` with Bedrock + render mocked — upload returns candidates + sets a session cookie; render returns per-clip results; clips download; non-PPTX and oversized uploads rejected; unknown `clip_id` 404s.
- **Real render smoke** (one per new scene, like Week 1 `test_full_render.py`): actually invoke Manim+ffmpeg for `text_card`, `fraction_bar`, `balance_scale`, asserting a non-empty MP4.
- Every task's tests pass before the next; commit after each task.

## 7. Tech Stack Additions

- Backend: `fastapi` + `uvicorn` (already pinned in `pyproject.toml`); `python-multipart` for file upload; dev-only `httpx` for `TestClient`.
- Frontend: React + Vite (Node toolchain), plain `fetch` for API calls; no state library needed at this size.
- No new AI dependency — classification reuses the Week 1 `call_with_tool` Bedrock path.

## 8. Open Questions

None blocking. `balance_scale` is intentionally minimal (`a + b = c` equality) for v1; richer inequality/variable framing is deferred. Multi-clip render is sequential for Week 2; parallelization is a later optimization if needed.
