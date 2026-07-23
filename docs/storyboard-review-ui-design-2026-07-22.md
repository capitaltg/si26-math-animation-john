# Storyboard Review UI — Design Spec

**Date:** 2026-07-22
**Ticket:** Storyboard review UI
**Status:** Design approved, pending implementation plan

## 1. Summary

Insert a **storyboard review step** between template selection and full render.
Today the pipeline jumps straight from `/options` (classify + pick template) to
`/render` (extract + full render in one shot), giving the teacher no chance to
verify or correct extracted values before committing to a full Manim render.

This ticket delivers the review step end-to-end — backend endpoints and the React
UI — matching the Week 3 storyboard review described in the project design doc
(§4 steps 8–9, §5, §8). A teacher sees a fast thumbnail preview per scene,
grounded against the source excerpt, with editable extracted values, a grade
override, and per-scene approve / reject / retry controls. Full render runs only
on approved scenes, using the teacher's stored (edited) values.

**Scope:** full vertical slice — backend + frontend.

## 2. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Backend + React | Storyboard step does not exist server-side yet. |
| Pipeline shape | New `/storyboard` step | Clean 3-stage flow: options → storyboard → render. |
| Edit form | Schema-driven generic renderer | One renderer for all 6 templates + future ones; server stays sole validator. |
| Edit cycle | Validate → re-render thumbnail synchronously | Direct "edit → see updated preview" loop, the point of a storyboard. |
| Retry | Re-extract on the same template | Matches "extraction was slightly off, try again". Template change = back to options. |
| Stated-answer consistency check | **Deferred** to a follow-up ticket | No code captures a stated answer today; requires discovery/extraction changes. This ticket ships schema + guard re-validation only. |

## 3. Current state (context)

- Flow: `POST /upload` → candidates; `POST /options` → template choices per
  candidate (caches `ClassificationResult` in `session.options`); `POST /render`
  → extract + full render + clip.
- `Scene` model (`backend/app/models/scene.py`) **already anticipates review**:
  `status="pending_review"`, `thumbnail_path`, `grade_overridden`,
  `stated_answer` — all present, none populated yet.
- `render_scene_thumbnail` (`backend/app/render/full_render.py`) already exists —
  `save_last_frame` + low quality, single-frame PNG via the same subprocess worker.
- Compatibility guards live inside pydantic `model_validator` on each template's
  params, so re-validating edited values is just `params_cls.model_validate(dict)`
  — schema + guard fire together.
- `process_scene` (`backend/app/pipeline/process_scene.py`) currently does
  extract → full-render → Scene in one shot, with retry-once-with-backoff and
  text-card fallback on mismatch.

## 4. API contract

All endpoints are cookie-session scoped, matching existing endpoints.

```
POST /storyboard
  body: { picks: [{ candidate_id, template }] }    # same shape /render takes today
  → per pick: extract params → validate → render thumbnail
    (extraction miss/mismatch → text_card fallback scene w/ reason)
  → stores Scene(status="pending_review"|"fallback") per pick in session
  → returns: { scenes: [SceneOut] }

PATCH /storyboard/{scene_id}
  body: { params?: {...}, grade_level?: int }       # either or both
  → validate params (schema + guard); set grade_overridden if grade sent
  → valid:   re-render thumbnail, return updated SceneOut
  → invalid: 422 { errors: [{loc, msg}] }, prior thumbnail kept

POST /storyboard/{scene_id}/retry
  → re-extract source on the SAME template → re-render thumbnail → pending_review
    (2nd mismatch → text_card fallback, terminal — no loop)

POST /storyboard/{scene_id}/approve   → status=approved
POST /storyboard/{scene_id}/reject    → status=rejected

POST /render        # CHANGED: no body; renders session scenes with status=approved,
                    # using STORED (edited) params — no re-extraction
  → returns { clips: [ClipResult] }    # rejected scenes skipped

GET /thumbnails/{thumb_id}   → FileResponse, media_type=image/png
```

**`SceneOut`:**
```
{
  scene_id, candidate_id, template, grade_level, grade_overridden,
  params,                 # current (possibly edited) values
  params_schema,          # params_cls.model_json_schema() — drives the edit form
  status,                 # pending_review | approved | rejected | fallback
  fallback_reason,        # non-null only for fallback scenes
  thumbnail_url,          # /thumbnails/{id}, or null if render failed
  source_excerpt,         # from candidate — the grounding line
  detected_summary        # candidate.one_line_summary — "what was detected"
}
```

**Key invariant:** full render uses **stored** params, not a re-extraction — a
teacher's edits are authoritative and cannot be silently discarded at render time.

## 5. Backend internals

### 5.1 Session state
Add to `Session` (`backend/app/session.py`):
```python
scenes: dict[str, Scene] = field(default_factory=dict)   # keyed by scene_id
scene_order: list[str]   = field(default_factory=list)   # display order
```
Retry replaces the Scene in place (same `scene_id`). Approve / reject / patch
mutate the stored Scene.

### 5.2 Refactor `process_scene`
Split the extract/validate/fallback *decision* from the *render mode*:
```
assemble_scene(candidate, template, grade, output_dir) -> Scene
   # extract → validate → render THUMBNAIL
   # success                       → Scene(status="pending_review", thumbnail_path=...)
   # TemplateMismatch/Validation   → text_card fallback Scene (thumbnail of the card)
```
- `/storyboard` calls `assemble_scene` per pick.
- The existing retry-once-with-backoff logic moves into `assemble_scene`
  (extraction is where transient failures live).
- `/render` does **not** re-extract: for each approved scene it calls
  `render_scene_to_mp4(scene.template, params_cls.model_validate(scene.params), out)`.
  Full render keeps its own subprocess error handling.

### 5.3 Edit validation (`PATCH`)
```python
params_cls.model_validate(edited_params)   # schema + guard fire together
```
- Valid → store params, re-render thumbnail, return scene.
- Invalid → map `ValidationError.errors()` to `[{loc, msg}]`, return 422,
  thumbnail untouched.
- **No grounding check on edits** — grounding guards against *model* fabrication;
  teacher edits are intentional overrides. Grounding still runs inside
  `assemble_scene`'s extraction, unchanged.

### 5.4 Grade override
`PATCH grade_level` sets `grade_level` and `grade_overridden=True`. Range `0..8`
enforced by the existing `Scene.grade_level` field validator (9 → 422).

## 6. Thumbnail serving
Thumbnails are PNGs in `session.output_dir`. Serve like clips.

Add to `SessionStore` (mirror `register_clip` / `get_clip`):
```python
register_thumbnail(path) -> thumb_id      # OrderedDict, LRU, separate max_thumbnails (~1000)
get_thumbnail(thumb_id)  -> Path | None
```
```
GET /thumbnails/{thumb_id}  →  FileResponse(path, media_type="image/png")
```
- `assemble_scene` and `PATCH` register the new PNG and set
  `thumbnail_url = f"/thumbnails/{id}"`.
- Re-render on edit/retry registers a **new** thumb_id — the URL changes, so the
  browser never serves a stale cached image.
- Separate `max_thumbnails` cap keeps fast thumbnail churn from evicting clips.
- File cleanup: rely on session-dir `shutil.rmtree` on session eviction (same as
  clips today). No per-thumb file deletion.

## 7. Frontend

Insert a storyboard stage between "Choose visualizations" and "Results" in
`frontend/src/App.jsx`. New state: `storyboard` (array of SceneOut). The options
screen's "Render" button now calls `POST /storyboard` (not `/render`) and lands
on the review screen.

**Review screen** — one card per scene, in `scene_order`:
- Thumbnail `<img src={thumbnail_url}>` (placeholder if null).
- `detected_summary` (bold) + `source_excerpt` (muted) — the grounding line.
- Fallback scenes: amber `fallback_reason` banner.
- Editable fields via `<SchemaForm>` (below).
- Grade `<select>` 0–8, shows "(overridden)" when `grade_overridden`.
- Buttons: **Save edits** (PATCH), **Retry** (POST retry), **Approve** / **Reject**
  (toggle status, highlight card).
- Per-scene inline error area for 422 field errors.

Bottom bar: **Render approved** → `POST /render` → Results screen (reuses the
existing results section). Disabled when zero scenes approved.

**`<SchemaForm schema params onChange>`** — the one genuinely new component:
```
walk schema.properties:
  integer / number     → <input type="number">
  enum (Literal)       → <select>
  array of objects     → repeatable rows; each row = nested SchemaForm
                         + add/remove-row (respect minItems / maxItems)
  string               → <input type="text">
```
Resolves one `$ref` level into `$defs` for nested item models (e.g. `steps` →
`NumberLineStep`) — that ref-following is the single load-bearing bit; everything
else is a flat type→widget switch. Parent holds per-scene draft state, sends on
Save.

Keep the current inline-style approach for consistency (no CSS framework in this
ticket).

## 8. Error handling & edge cases

| Case | Handling |
|---|---|
| Extraction miss/mismatch at `/storyboard` | Scene → `fallback` (text_card), thumbnail of the card, reason shown. Expected path, not an error. |
| Thumbnail render subprocess fails | Scene still returned, `thumbnail_url=null`. UI shows placeholder; scene still approvable (full render retried at `/render`). |
| Edit fails validation | 422 `{errors:[{loc,msg}]}`, old thumbnail kept, card stays `pending_review`. |
| Grade out of 0–8 | Scene field validator → 422. |
| Approve a `fallback` scene | Allowed — `/render` renders the text_card MP4 from stored params. Honest fallback clip. |
| `/render` with zero approved | 400 "No approved scenes to render" (UI disables button too). |
| Full render fails for one approved scene | That `ClipResult` → error/fallback, others still returned. One bad scene doesn't sink the batch. |
| Stale/expired session (LRU evicted) | 400 "No active session" — existing pattern. |
| Unknown `scene_id` on PATCH/retry/approve/reject | 404. |
| Retry re-extract mismatches again | Scene → `fallback`, terminal. No infinite loop. |
| Concurrent edits (2 tabs, same session) | Out of scope — single-user demo state, last-write-wins. |

## 9. Testing

**Backend** (`backend/.venv/bin/pytest`):
- `assemble_scene`: success → `pending_review` + thumbnail; mismatch → `fallback`
  text_card + reason; transient extraction error → retry-once then fallback.
  Mock `call_with_tool`, stub `render_scene_thumbnail`.
- Edit validation: valid params store + re-thumbnail; guard violation (number_line
  span > 20, negative running total) → 422 field errors, thumbnail unchanged;
  grade override sets `grade_overridden`; grade 9 → 422.
- Retry: replaces scene in place, same `scene_id`.
- `/render`: renders only `approved`; skips `rejected`; uses stored params (assert
  Bedrock mock **not** called — no re-extraction); one render failure doesn't drop
  the batch.
- Schema contract: assert `NumberLineParams.model_json_schema()` exposes
  `$defs` + `steps` array so the `SchemaForm` ref-following assumption holds.

**Test-client status:** `test_routes.py` already runs green (23 pass) — `httpx2>=2.7`
is pinned in dev deps (commit `ec9ffa5`) and Starlette `TestClient` works against it.
No dep fix needed; new endpoint tests (`/storyboard`, `PATCH`, retry, approve/reject,
`/render`) go straight into `test_routes.py` using the existing `TestClient` fixture.
(An earlier draft flagged this as a blocker — verified resolved on 2026-07-22.)

**Frontend:** no test runner in `frontend/` today. Manual verification via `/run`
against a known-good PPTX (matches the demo-rehearsal approach in the project
plan). A test runner would be its own ticket.

## 10. Out of scope (this ticket)

- Stated-answer consistency check + capturing a stated answer upstream (follow-up).
- Frontend test-runner setup.
- Any CSS framework / visual redesign — inline styles only, matching current UI.
- Concurrent multi-tab session editing.
```
