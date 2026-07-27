# Meta-template system: AI-assisted authoring of new animation templates

## Problem

The 6 hand-written templates (`number_line`, `array_grid`, `text_card`, `fraction_bar`,
`balance_scale`, `fraction_of_whole`) don't cover a majority of K-8 math problem shapes.
Problems that don't fit any template fall back to `text_card` (a plain text card, no
animation). Hand-authoring a new template for every uncovered shape doesn't scale.

## Goal

Build a pipeline that uses Bedrock to draft new animation templates automatically when
a problem shape recurs often enough as a `text_card` fallback, while preserving the
existing pipeline's core invariant: **AI never verifies math at run time.** Every real
render's math correctness is decided by deterministic code (a compiled guard +
`grounding.py`), never by trusting AI output directly, exactly as it works today for the
6 hand-written templates.

## Non-goals (v1)

- No retroactive re-classification of already-approved `text_card` fallback scenes once
  a new template ships.
- No embedding-based fuzzy clustering — exact fingerprint string match only for
  detecting recurring problem shapes. Smarter clustering is a plausible future
  improvement, not needed to ship v1.
- No new auth/permissions model. This is a dev-facing tool, matching the app's current
  no-auth, single-operator posture.
- No sandboxing beyond AST import-allowlisting + the existing subprocess isolation +
  render timeout. No container/gVisor-level isolation. Consistent with the app's
  current trust model — revisit if stronger isolation is wanted given that generated
  code is ultimately derived from untrusted uploaded slide content.

## High-level flow

```
Fallback scenes (status=fallback) accumulate over time
        │
        ▼
Signature clustering (deterministic: grade_level + AI-tagged shape fingerprint)
        │  threshold N reached for a fingerprint
        ▼
Codegen job (Bedrock):
  - drafts scene.py-equivalent (free-form Manim Python)
  - proposes params schema (fields/types/bounds)
  - proposes declarative guard spec (structured predicates, not code)
        │
        ▼
Validation harness (fully deterministic, no AI):
  - AST allowlist check on generated scene code
  - compiles guard spec → callable, runs against real recurring examples
    (real fallback source_excerpts + their stated_answer, when known)
  - runs auto-generated boundary/edge test table against compiled guard
  - renders a preview video/thumbnail in the existing isolated subprocess
        │
        ▼
Template draft stored (status=pending_review) — NOT wired into registry yet
        │
        ▼
Dev watches the rendered video + reads guard spec in plain English + sees
test pass/fail table  →  Approve / Reject
        │                     │
        ▼                     ▼
  Wired live,           Chat refinement loop: describe what's wrong →
  classifier prompt     Bedrock revises scene/params/guard spec →
  gets new bullet       re-validate → re-render → review again
```

## Components

### Durable store (new: SQLite via SQLAlchemy)

The app currently has **no database** — `app/session.py`'s `SessionStore` is a pure
in-memory, LRU-evicted (200 sessions) dict, wiped on restart. This feature needs the
app's first durable, cross-session store, since fallback observations must be tracked
over time (beyond any one session) and approved templates must survive process
restarts. SQLite (via SQLAlchemy, for migration/query ergonomics as the schema grows)
is the storage choice, kept as a single new file-backed dependency consistent with the
codebase's otherwise lightweight style.

| Table | Purpose |
|---|---|
| `fallback_observations` | Append-only log written whenever a scene falls back to `text_card` (hook into `_fallback_scene` in `process_scene.py`). Columns: `source_excerpt`, `grade_level`, `fingerprint`, `stated_answer` (nullable), `created_at`. |
| `template_drafts` | One row per draft iteration. Columns: `fingerprint`, `version`, `scene_source` (generated Manim code), `params_schema` (JSON field defs), `guard_spec` (JSON predicate list), `preview_video_path`, `test_report` (JSON pass/fail results), `status` (`pending_review` / `approved` / `rejected` / `failed_validation` / `superseded`), `reviewer_feedback` (JSON history of chat-refinement rounds), `created_at`. |
| `templates` | Approved, live templates. Columns: `name` (slug), `scene_source`, `params_schema`, `guard_spec`, `classifier_contract_bullet` (text fed into the classification prompt), `enabled`, `approved_from_draft_id`. |

### Boilerplate template contract (new `_shared/` modules)

Human-authored once, alongside existing `_shared/fit_to_frame.py` / `_shared/chained_scene.py`:

- `TemplateParamsBase` — pydantic base wiring `guard_spec` evaluation into
  `model_validator`, plus the existing `grounding_number_tokens` /
  `grounding_derived_totals` hooks so dynamic templates plug into `grounding.py`
  unchanged. A `templates` row's `params_schema` (JSON field defs: name/type/bounds)
  is turned into a live class at load time via `pydantic.create_model(...,
  __base__=TemplateParamsBase)`, so `get_template()` can return a real params class the
  same way it already does for the 6 static templates.
- **Declarative guard predicate DSL** — a small, closed vocabulary (`equals`, `range`,
  `divisible_by`, `positive`, `sum_equals`, etc., expressed over param field names).
  Bedrock proposes a list of these predicates; a fixed, once-reviewed compiler turns
  them into the actual `check_compatibility(params)` callable (same shape/contract as
  today's hand-written `guard.py` files — raises `ValueError` on violation). This is
  the mechanism that keeps "math verified programmatically, not by AI" literally true
  at run time: the compiler is fixed, boring, tested code; only its *input data*
  (the predicate list) is AI-authored, and that data is validated (see below) before
  ever being trusted.
- **`scene_source` contract** — must define `draw_fn(scene, params)` with the expected
  signature (mirrors the existing hand-written template shape, e.g.
  `balance_scale/scene.py`'s `draw_fn`). Enforced via a static `ast`-based check
  *before* the code is ever executed: only whitelisted imports (`manim`,
  `app.templates._shared.*`, safe stdlib) are allowed; no `subprocess`, `socket`, `os`,
  `eval`, `exec`, `__import__`, or file I/O outside the render scratch dir. This closes
  off arbitrary-code-execution risk cheaply and deterministically — important because
  the pipeline's ultimate input (uploaded slide content) is untrusted, so a poisoned
  deck attempting prompt injection into the codegen step is a real threat model, not a
  hypothetical.

### Dynamic loading

`render_worker.py` already runs every render in an isolated, timeout-bounded subprocess
(`full_render.py`, `RENDER_TIMEOUT_SECONDS = 120`) — this is where a `templates` row's
`scene_source` gets executed and its compiled guard runs, so a crash or hang in
generated code is contained exactly as it is today for hand-written templates.
`registry.get_template()` becomes: check the static `_REGISTRY` dict first (the 6
hand-written templates, untouched), then fall back to querying the `templates` table by
name. `Scene.template` (currently `TemplateName | None`, a closed `str` enum) becomes a
plain `str | None`, validated against "static enum member or known DB template name"
instead of strict enum membership.

### Classifier integration

`classification.py`'s hardcoded `_TEMPLATE_CONTRACTS` string gets each `enabled`
template's `classifier_contract_bullet` appended at call time (queried from the
`templates` table), so a newly-approved template becomes selectable by the existing
classifier without any code change to `classification.py` itself.

## Fingerprint clustering

A new lightweight Bedrock call, invoked wherever `_fallback_scene` fires, tags the
fallback with a short structural fingerprint (e.g. `"compare two decimals on grid"`) —
same tool-call pattern as `classify_candidate`. v1 clusters by **exact fingerprint
string match** (no embedding infrastructure). A configurable threshold `N` (default 5,
added to `app/config.py`) on same-fingerprint count triggers a codegen attempt for that
cluster.

## Chat-refinement loop

Rejecting a draft prompts for free-text feedback (e.g. "the bar should split into
thirds, not halves"). This creates a new `template_drafts` row (`version + 1`) with the
feedback appended to `reviewer_feedback`, and re-invokes codegen with the prior
`scene_source` / `params_schema` / `guard_spec` plus the feedback as context. **The full
validation harness re-runs from scratch on every revision** — no step is skipped just
because it's an iteration, not a first draft. Capped at 5 refinement rounds per
fingerprint; beyond that, the draft is surfaced as "needs manual authoring" rather than
looping indefinitely.

## Validation harness

Runs before every review (initial draft and every chat-refinement revision):

1. **AST allowlist check** on `scene_source` (see contract above).
2. **Guard spec compiles** to a callable via the fixed predicate-DSL compiler.
3. **Real-example check** — the actual `fallback_observations` rows that triggered this
   cluster (real curriculum problems, with `stated_answer` when known) are run through
   extraction + the compiled guard + a render; must not raise.
4. **Synthetic boundary check** — a deterministic generator derives edge-case param
   values directly from the guard spec's own predicates (just-inside/outside ranges,
   equality violations, zero/negative cases) and confirms the compiled guard
   accepts/rejects consistently with what the spec implies. This catches compiler bugs,
   not spec-correctness bugs — spec correctness (does this predicate list actually
   capture the real math invariant) is what the plain-English guard summary + video
   review is for.
5. **Render smoke test** — thumbnail + short preview clip, via the existing isolated
   subprocess mechanism.

If any step fails: one automatic retry feeding the failure back to Bedrock. If it fails
again, the draft still surfaces in the review queue — never silently dropped — but
flagged `failed_validation` so it's clear it shouldn't be trusted on sight.

## Review UI

Reuses the existing approve/reject interaction pattern already built for scene review
(`frontend/src/App.jsx`'s `/approve` / `/reject` against `/storyboard/...`), pointed at
`template_drafts` instead of `Scene`s: video/thumbnail preview, the guard spec rendered
as plain-English predicate sentences, and the test-report pass/fail table, with
Approve / Reject (with feedback) actions.

## Error handling

- Codegen call fails/times out: log and drop this cycle's attempt; no retry storm — the
  next fallback observation for the same fingerprint re-triggers the threshold check
  and tries again.
- AST check, guard-compile, or render failures: one automatic retry with the failure
  fed back to Bedrock, then surfaced flagged `failed_validation` per the harness section
  above.
- Chat-refinement loop: capped at 5 rounds (see above).

## Testing

- Unit tests for the predicate-DSL compiler (the one piece of fixed code this whole
  system's safety rests on) — exhaustive coverage of every predicate type, including
  edge cases the synthetic boundary generator itself relies on.
- Unit tests for the AST allowlist checker — known-bad code samples (disallowed
  imports, `eval`/`exec` usage) must be rejected; known-good samples (the 6 existing
  hand-written `scene.py` files) must pass.
- Integration test: a fake/fixture codegen response run end-to-end through the
  validation harness into a `pending_review` draft, then through approval into a live,
  render-able template via `get_template()`.
