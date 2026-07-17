# K-8 Math Animation Generator — Technical Design Spec

**Date:** 2026-07-17
**Status:** Approved (pending final user sign-off on this document)
**Companion doc:** `project description.md` (Revision 4) — the product/pipeline design this spec implements. This document adds the implementation-level architecture (tech stack for the web layer, data model, request lifecycle, error handling, dev/deploy, testing) that the product doc left open.

---

## 1. Product Summary (reference)

Full product scope, the 11-step pipeline, the component/template library, the accuracy strategy, multi-step handling, and the 4-week plan are specified in `project description.md` and are **not repeated here** — this spec assumes that document as ground truth for *what* the system does and focuses on *how* it's built.

Key product decisions inherited unchanged:
- PPTX-only input for v1 (DOCX/PDF fast-follow)
- Never trust LLM arithmetic — all computation done in Python (`fractions.Fraction`)
- Per-template Pydantic compatibility guards, applied to both extracted and teacher-edited values
- Classification ambiguity and render failure are distinct failure types with distinct recourse
- Separate MP4 per approved scene, no stitching, no auto-embed into the original PPTX
- No accounts; state is ephemeral per session

---

## 2. Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend framework | **FastAPI** | Async-native, Pydantic is first-class (already the schema/validation tool per the product doc), auto-generated OpenAPI docs, comfortable with long-running blocking render calls |
| Frontend | **React + Vite SPA** | Best fit for the stateful, multi-step review UI (editable per-scene fields, approve/reject/retry, live thumbnails) |
| LLM | **AWS Bedrock, Claude Sonnet, single tier** for all calls (discovery, classification, extraction) | One model to prompt-tune and benchmark; matches the Week-1 latency-measurement task cleanly. Credentials provided via internship-issued Bedrock API key |
| Session state | **Server-side, in-memory**, keyed by session ID (HttpOnly cookie) | Simplest match for "no accounts, ephemeral state"; single-process is fine for a local-machine demo |
| File storage | **Local temp directory per session** | No extra infra; matches ephemeral-state design; cleaned up on session eviction |
| Progress UX | **Blocking request + spinner**, per-scene | Renders are per-scene (not whole-deck), so a blocking call with a per-card spinner is simple and sufficient — no job-polling layer needed |
| Deployment | **Local machine only** for v1 demo | Matches 4-week scope; avoids infra/IAM work unrelated to the core risk (extraction accuracy) |
| Animation engine | **Manim** (unchanged from product doc) | |
| Video encode | **ffmpeg**, per-clip only (unchanged from product doc) | |
| Schema/validation | **Pydantic**, one model per template (unchanged from product doc) | |
| Language | **Python** (backend/pipeline), **TypeScript** (frontend) | |

---

## 3. Project Structure

```
backend/
  app/
    main.py              # FastAPI app, route registration
    routes/              # upload, candidates, storyboard, render, download
    session.py           # in-memory SessionStore: dict[session_id -> SessionState]
    pipeline/
      parsing.py         # PPTX text extraction, chunking
      discovery.py       # Bedrock: candidate discovery
      classification.py  # Bedrock: topic/grade + template match
      extraction.py      # Bedrock: schema-scoped param extraction
      validation.py      # Pydantic validation, compatibility guards, consistency check
      arithmetic.py       # local computation only, never trusts LLM math
    templates/            # one subpackage per visual component
      <template>/
        scene.py          # Manim Scene subclass
        params.py         # Pydantic model for this template's params
        guard.py          # compatibility guard function
    render/
      thumbnail.py         # save_last_frame + low-quality config, single-frame preview
      full_render.py        # subprocess-isolated full Manim render + ffmpeg encode
    storage.py             # per-session temp dir management (upload, thumbnails, clips)
  tests/                    # pytest: unit + integration (Bedrock mocked)
frontend/
  src/
    pages/                # Upload, CandidateSelect, StoryboardReview
    components/            # SceneCard, EditableField (per-template registry), ApproveRejectRetry
    api/                   # typed fetch wrappers matching backend routes
eval/
  fixtures/                # hand-authored PPTX decks: known-good, zero-candidate, distractor-heavy, ambiguous-phrasing
  run_eval.py               # runs real pipeline against fixtures, dumps a report for human review
docs/superpowers/specs/     # this spec and future ones
```

---

## 4. Session & Request Lifecycle

**Session identity:** first `/upload` call generates a `session_id` (UUID), returned as an HttpOnly cookie. Every later request resolves `SessionState` from the in-memory store via that cookie. Sessions evict on an idle timeout (e.g. 30 min) — the closest practical proxy for "resets on tab close," since a server can't reliably observe a browser tab closing.

**Endpoints** (mapped onto the product doc's 11-step pipeline):

1. `POST /upload` — multipart PPTX → parse + chunk → run discovery → store `candidates` in `SessionState` → return candidates, or an explicit "no problems found" response
2. `POST /candidates/select` — chosen candidate IDs + optional manual entries → classification → grade inference → extraction → validation, per candidate → store `scenes` (storyboard) in `SessionState` → synchronously render thumbnails → return storyboard JSON with thumbnail URLs
3. `PATCH /scenes/{scene_id}` — edited values / grade override → re-validate → re-run consistency check → re-render thumbnail → return updated scene
4. `POST /scenes/{scene_id}/retry` — re-run classification → extraction → validation for that one scene from scratch
5. `POST /scenes/{scene_id}/render` (approve) — full Manim render in subprocess + ffmpeg encode → store MP4 in session temp dir → return download URL (blocking; frontend shows a per-card spinner)
6. `GET /scenes/{scene_id}/download` — streams the MP4
7. `DELETE /scenes/{scene_id}` (reject) — discard from `SessionState`, clean up partial temp files

---

## 5. Data Model

```python
class SessionState:
    session_id: str
    created_at: float
    upload_path: Path
    raw_text_chunks: list[str]
    candidates: list[Candidate]
    scenes: dict[str, Scene]

class Candidate(BaseModel):
    candidate_id: str
    source_excerpt: str
    slide_index: int
    one_line_summary: str

class Scene(BaseModel):
    scene_id: str
    candidate_id: str | None       # None if manually entered
    manual_source_text: str | None # Original manual entry; retained so Retry can reprocess it
    template: TemplateName | None  # None if fell back
    grade_level: int
    grade_overridden: bool
    params: dict                   # validated against the matching template's Pydantic model
    stated_answer: Fraction | None # Normalized source answer; retained for consistency re-checks
    status: Literal["pending_review", "approved", "rejected", "fallback"]
    fallback_reason: str | None    # populated only when status == "fallback"
    thumbnail_path: Path | None
    render_path: Path | None
```

Each template owns its own params model with a compatibility guard, e.g.:

```python
class NumberLineParams(BaseModel):
    start: Fraction
    steps: list[Step]   # {operation, amount} — never intermediate results

    @model_validator(mode="after")
    def compatibility_guard(self):
        ...  # e.g. same-denominator check for fraction templates
```

`Scene.params` is validated against the matching template's model at both extraction time and on every teacher edit (`PATCH /scenes/{id}`) — one model, two call sites, no drift between LLM-produced and hand-edited values.

`Scene.stated_answer` stores the classifier's answer after normalization to `Fraction`, rather than only using it during initial processing. After a teacher edits operands, `PATCH /scenes/{id}` computes the result from the newly validated params and compares it with this persisted value before re-rendering. `manual_source_text` is populated only for manual entries; discovered scenes retain `candidate_id` and resolve their source excerpt from `SessionState.candidates`. This gives Retry a durable source in both cases without duplicating uploaded slide text on every discovered scene.

Keeping `template` and `fallback_reason` as separate fields (rather than folding fallback into a template variant) is what makes "classification ambiguity vs. render failure are distinct failure types" enforceable in code — the frontend renders a different message depending on which is set.

---

## 6. Error Handling, Retries, Fallback Routing

```python
async def process_candidate(candidate_or_manual) -> Scene:
    source_text = candidate_or_manual.source_text
    manual_source_text = source_text if candidate_or_manual.is_manual else None
    try:
        classification = await classify(candidate_or_manual)
    except AmbiguousClassification:
        return build_fallback_scene(
            reason="Could not confidently match a template",
            manual_source_text=manual_source_text,
        )
        # no retry — an ambiguous case won't resolve differently on an identical retry

    stated_answer = normalize_answer(classification.stated_answer)
    try:
        raw_params = await extract_params(classification)
        validated = TemplateParams[classification.template].model_validate(raw_params)
    except (ValidationError, BedrockTimeoutError) as e:
        try:
            raw_params = await extract_params(classification)   # retry once, backoff
            validated = TemplateParams[classification.template].model_validate(raw_params)
        except Exception:
            return build_fallback_scene(
                reason=f"Extraction failed after retry: {e}",
                stated_answer=stated_answer,
                manual_source_text=manual_source_text,
            )

    computed = run_arithmetic_locally(validated)
    if stated_answer is not None and computed.final_value != stated_answer:
        return build_fallback_scene(
            reason="Computed result doesn't match stated answer",
            stated_answer=stated_answer,
            manual_source_text=manual_source_text,
        )

    return Scene(
        scene_id=new_scene_id(),
        candidate_id=candidate_or_manual.candidate_id,
        status="pending_review",
        template=classification.template,
        grade_level=classification.grade_level,
        params=validated.model_dump(),
        stated_answer=stated_answer,
        manual_source_text=manual_source_text,
    )
```

`POST /scenes/{scene_id}/retry` reconstructs its input from the candidate excerpt when `candidate_id` is set, otherwise from `manual_source_text`, and then calls `process_candidate` from the classification step. `PATCH /scenes/{scene_id}` never asks the classifier for the answer again: it validates the edited params, runs local arithmetic, and compares the new final value with the persisted normalized `scene.stated_answer`. Fallback builders preserve both source fields and `stated_answer` so a failed first pass remains retryable and auditable.

Distinct exception types (`AmbiguousClassification` vs `ValidationError` vs a render-specific error) — not a shared error with a `.kind` field — enforce the no-retry-on-ambiguity invariant structurally: it can't be accidentally bypassed by a later refactor of a shared `except` block.

Three teacher-facing messages, never a generic failure string:
- Ambiguous classification → "This problem's operands weren't clear enough to visualize automatically — try editing it manually."
- Extraction/validation failure after retry → "Extraction failed twice — the numbers may not have parsed correctly."
- Consistency mismatch → "The computed answer didn't match what the source stated — this usually means a number was misread."

Render failures (Manim subprocess crash, ffmpeg error) follow the same one-retry-then-fallback shape, producing a render-time fallback distinct from an extraction-time one. The Retry button (`POST /scenes/{id}/retry`) re-enters `process_candidate` from the classification step — the same code path as first-pass processing.

---

## 7. Frontend Flow

Three pages, matching the pipeline's actual checkpoints:

- **`Upload`** — PPTX drop/picker → `POST /upload`. Shows "no problems found" inline if candidates come back empty.
- **`CandidateSelect`** — checkbox list of candidates (summary + expandable source excerpt) plus a manual-entry form feeding the same `POST /candidates/select` call as an extra candidate.
- **`StoryboardReview`** — one `SceneCard` per scene: thumbnail, detected-summary + source excerpt, per-template field editor (a small per-template editor registry, not one generic form), grade override, and Approve/Reject/Retry. Fallback scenes render a distinct card variant showing `fallback_reason` and a Retry button, no editable params.

State management: no Redux/Zustand — plain `useState`/`useEffect` (or React Query) is enough, since the backend `SessionState` is the actual source of truth and each page fetches fresh on mount. A browser refresh mid-review just refetches; there's no frontend/backend state to drift.

Render (approve) blocks per the Progress UX decision — the `SceneCard` shows a spinner over just that card; other cards stay interactive since renders are per-scene.

---

## 8. Dev Setup & Deployment

Two processes for local dev:

```
# terminal 1
cd backend && uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend && npm run dev   # Vite dev server, port 5173, proxies /api/* to :8000
```

For the actual demo: `npm run build` produces static assets that FastAPI serves directly via `StaticFiles` — one process, one port, no proxy, simplest handoff to a presenter's laptop. Do a full build-and-serve dry run before the live presentation rather than relying on `--reload` dev mode throughout — the dev-proxy path and the demo-serving path are different enough that testing only one leaves the other unverified.

**Config/secrets:** Bedrock credentials load from environment variables via `pydantic-settings` (`.env`, gitignored; `.env.example` documents `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `BEDROCK_MODEL_ID`).

**System dependencies** the demo machine needs beyond `pip install`: ffmpeg, a LaTeX distribution if any template uses `MathTex`, Cairo/Pango (Manim's rendering deps). Worth a one-time setup doc since these vary by OS.

**Docker — Week 4 stretch goal, not a demo dependency.** A `Dockerfile` for `backend/` installing Python + Manim's system deps, multi-stage-building the frontend (`npm run build` copied into the final image) so `docker run` alone reproduces the "FastAPI serves built React" demo path. Not required for the Week 1-3 timeline; same priority tier as icon theming/Galeo auth — cut first if Week 4 is tight. Purpose: make the project handoff-able to a future dev or a different machine without redoing Manim's system-deps setup by hand.

---

## 9. Testing & Eval Strategy

Two distinct layers that test different things:

**Unit tests (`pytest`, `backend/tests/`):**
- `arithmetic.py` — pure Python, exhaustive: multi-step chains, `Fraction` arithmetic, edge cases
- Template `guard.py` functions — valid and deliberately invalid params (mismatched denominators, negative counts), assert accept/reject
- `validation.py` — Pydantic round-trips; re-validation on edited values follows the same code path as first-pass validation
- Parsing/chunking — fixture PPTX files with known slide bodies/notes, assert extracted text and chunk boundaries at the 50-slide cap

**Integration tests (FastAPI `TestClient`):**
- Full request lifecycle against a fixture PPTX with Bedrock calls mocked — verifies routing, session state transitions, status codes without live Bedrock calls
- A mocked "ambiguous classification" response asserting `fallback` status with the mock called exactly once (not twice) — the automatable check for the no-blind-retry invariant

**Frontend:** Vitest + React Testing Library for `SceneCard`'s three visual states (pending/fallback/approved). No full E2E suite in the 4-week window; manual click-through substitutes during Week 3-4.

**Eval set (real Bedrock calls, not mocked)** — the layer that actually matters for the project's core risk:
- `eval/fixtures/`: a known-good deck (primary rehearsed demo input), a zero-candidate deck, a distractor-heavy deck (dates, standard codes like "3.OA.A.1", page numbers), an ambiguous-phrasing deck
- `eval/run_eval.py`: runs the real pipeline against each fixture, dumps discovered candidates/classifications/extracted params to a JSON report for **human review** — not pass/fail assertions, since judging "did discovery find the right things" needs a human call, not a string match
- Run manually after any prompt change to discovery/classification/extraction, and at least once per week per the product doc's Week 1/3 eval-building tasks

**CI (GitHub Actions, once a repo exists):** `.github/workflows/test.yml` runs on every push/PR — backend `pytest` (Bedrock mocked) and frontend `npm test`. The eval set does **not** run in CI — it costs real Bedrock spend per run and needs human judgment on the report, not a pass/fail gate — so it stays a manual/local step on the Week 1/3 cadence. CI enforces the mockable invariants (no blind retry, guards catching bad params); it doesn't grade real LLM output.

---

## 10. Open Items Deferred to Implementation Planning

- Exact idle-timeout duration for session eviction
- Exact per-template field-editor registry contents (depends on which Tier 1 templates are built first per the product doc's Week 1-2 plan)
- Whether `.env` secrets are loaded per-developer or via a shared internship-provided secrets mechanism
