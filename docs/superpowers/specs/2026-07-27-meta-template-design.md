# Meta-template system: AI-assisted authoring of new animation templates

## Problem

The six hand-written templates (`number_line`, `array_grid`, `text_card`,
`fraction_bar`, `balance_scale`, and `fraction_of_whole`) do not cover most K–8
math problem shapes. Problems without a compatible structural template use
`text_card`, which is useful as an honest fallback but does not visualize the
mathematics. Hand-authoring a new template for every recurring shape does not
scale.

## Goal and trust model

Build a dev-facing pipeline that uses Bedrock to **propose declarative template
definitions** when the same unsupported problem shape recurs. A human reviewer
can refine, validate, and approve a proposal before it becomes selectable.

V1 preserves these invariants:

1. Bedrock never generates or executes Python, Manim source, imports, or file
   paths. It produces data conforming to closed JSON schemas.
2. AI never makes a run-time correctness or publication decision. Reviewed,
   deterministic code validates params, grounding, guards, and expected outputs.
3. A draft cannot be published until a human has verified its mathematical
   semantics and every deterministic validation stage passes.
4. Preview and final render resolve the same immutable, content-addressed
   template version.
5. Disabling or revoking a template prevents it from being selected for new
   scenes; revocation also prevents already-pinned scenes from rendering.

The phrase “deterministic validation” does **not** mean an AI-proposed guard is
automatically mathematically correct. Synthetic tests can prove that the fixed
compiler implements a predicate consistently, but only independently verified
fixtures plus human review establish that the proposed predicates describe the
intended mathematics.

## Non-goals (v1)

- No retroactive re-classification of already-approved `text_card` scenes after
  a new template ships.
- No embeddings or fuzzy clustering.
- No arbitrary Python or general-purpose expression language in template
  definitions.
- No dynamic chained-scene variants. Dynamic templates render one problem per
  scene in v1.
- No new end-user auth model. The authoring UI and worker remain dev-only and
  disabled by default outside the local development configuration.
- No claim that source grounding proves an answer correct. Grounding establishes
  provenance of source operands; verified fixtures establish expected results.

## High-level flow

```text
Classifier resolves an unsupported problem to text_card
        │
        ▼
Store structural-fallback observation
        │
        ▼
Bedrock tags it with a closed, versioned fingerprint schema
        │
        ▼
Application code canonicalizes the fingerprint
        │  threshold N reached and no live/active job exists
        ▼
Atomically enqueue one durable codegen job
        │
        ▼
Bedrock proposes:
  - params field schema
  - declarative mathematical guard predicates
  - declarative animation/layout nodes
  - classifier contract bullet
        │
        ▼
Deterministic validation:
  - JSON-schema and resource-limit validation
  - DSL compilation
  - independently verified positive/negative fixtures
  - grounding checks
  - preview render through reviewed primitives
        │
        ├── failure → failed_validation (cannot approve)
        ▼
pending_review
        │
        ├── Reject with feedback → new immutable revision → validate again
        ▼
Human verifies math, preview, guard summary, and fixture report
        │
        ▼
Atomic approval publishes the exact validated artifact hash
        │
        ▼
Classifier may select the enabled immutable version
```

## Components

### 1. Durable store

The current `SessionStore` is an in-memory, LRU-evicted dictionary. Meta-template
observations, jobs, drafts, reviews, and approved versions need a separate
cross-session store.

Use SQLite through SQLAlchemy and schema migrations. SQLite is sufficient for the
single-operator v1, but all job-claiming transitions must use transactions. Store
preview media beneath a configured durable artifact root, not a session output
directory. Artifact filenames are their SHA-256 hashes; database rows store the
hash and relative key, never an arbitrary filesystem path.

| Table | Purpose and required fields |
|---|---|
| `fallback_observations` | Append-only structural fallback log: `id`, `candidate_id`, `source_excerpt`, `grade_level`, `observation_kind`, `fingerprint_version`, structured `fingerprint_json`, canonical `fingerprint_key`, nullable reviewer-supplied `expected_result_json`, `tagger_model_id`, `tagger_prompt_version`, `created_at`. |
| `generation_jobs` | Durable job state: fingerprint identity, triggering observation IDs, `status` (`queued`, `running`, `succeeded`, `failed`, `needs_manual_authoring`), `attempt`, lease owner/expiry, cooldown deadline, error summary, timestamps. A partial unique index permits at most one `queued` or `running` job per fingerprint. |
| `template_drafts` | One immutable proposal per revision: fingerprint identity, version number, params schema, guard spec, animation spec, classifier bullet, `artifact_hash`, validation report, status, parent draft, reviewer feedback, timestamps. Proposal content is never updated in place. |
| `template_reviews` | Append-only human decisions and fixture annotations: draft ID, decision, reviewer label, mathematical-semantics confirmation, feedback, timestamp. |
| `template_versions` | Immutable approved artifacts: stable template name, monotonically increasing version, the three DSL documents, classifier bullet, artifact hash, source draft, approval record, enabled/revoked state, timestamps. |
| `templates` | Stable-name index with the currently enabled version ID. It contains no mutable template source. |

Database rows and artifact files have explicit retention:

- Observations and review records are retained.
- Rejected/superseded draft media may be garbage-collected after 30 days.
- An artifact referenced by a draft, approved version, validation report, or
  pinned scene cannot be deleted.
- Startup reconciliation flags missing/corrupt artifacts and disables affected
  versions rather than silently regenerating them.

### 2. Observation semantics

Do not hook observation creation only into `_fallback_scene`. That function
represents extraction mismatches and technical failures, while the largest target
population takes the direct `template == text_card` path.

Create an observation after the classifier/storyboard decision when all of these
are true:

- The resolved template is `text_card`.
- No non-text structural option was accepted.
- The candidate contains a concrete solvable problem.
- The reason is `unsupported_shape`, not `technical_failure`,
  `render_failure`, manual template selection, or an ambiguous/non-problem input.

The decision layer emits a typed `TextCardReason`; persistence consumes that
event. `_fallback_scene` may report a typed reason but does not write directly to
the database. This keeps retries from recording the same candidate repeatedly.
`candidate_id` plus `observation_kind` is unique, making ingestion idempotent.

### 3. Versioned structural fingerprints

Bedrock does not return a free-form fingerprint string. It must call a tool whose
schema contains only bounded fields:

```json
{
  "fingerprint_version": 1,
  "operation_family": "compare|compose|decompose|transform|measure|pattern|other",
  "representation_family": "grid|bar|set|shape|table|clock|money|coordinate|other",
  "number_domain": "whole|integer|decimal|fraction|mixed",
  "operand_arity": 2,
  "step_count": 1,
  "grade_band": "K-2|3-5|6-8"
}
```

Application code validates bounds and enum membership, then serializes fields in
a fixed order to produce `fingerprint_key`. Exact matching applies to this
canonical key. The tagger is still probabilistic and can misclassify a shape; the
spec claims only that serialization and matching are deterministic, not that
semantic tagging is infallible.

Every observation records the model ID, prompt version, and fingerprint schema
version. Changing any of those does not silently regroup old observations.
Instead, an explicit offline retag migration creates new versioned tags. Reviewers
can mark an incorrectly tagged observation as excluded; v1 does not provide fuzzy
merge/split operations.

### 4. Declarative template contract

Bedrock proposes three closed JSON documents. Unknown keys, unknown node types,
unbounded collections, and schema violations are rejected before compilation.
The artifact hash is SHA-256 over canonical JSON containing the params, guard,
and animation documents, classifier bullet, DSL schema versions, and required
compiler/renderer compatibility versions. Changing any of those values creates a
different artifact.

#### 4.1 Params schema

The params schema supports:

- bounded integers and finite decimal numbers;
- bounded strings and closed enums;
- bounded arrays of bounded objects;
- required fields and defaults;
- display labels and descriptions.

It does not accept arbitrary JSON Schema keywords, regex execution, Python types,
callables, references outside the document, or custom validators.

A reviewed compiler maps this subset to a Pydantic model through
`create_model`. `TemplateParamsBase` runs the compiled guard and exposes
grounding metadata derived from the guard/expression DSL. Dynamic params models
are cached by immutable template-version ID, never by mutable template name.

#### 4.2 Guard and expression DSL

The guard DSL has a closed predicate vocabulary such as `range`, `positive`,
`equals`, `not_equals`, `sum_equals`, `product_equals`, `divisible_by`, and
`ordered`. Operands can be params fields, bounded array projections, or nodes in a
closed arithmetic expression tree (`add`, `subtract`, `multiply`, `divide`,
`fraction`). There is no source text, attribute access, function call, loop, or
general-purpose expression evaluation.

Compilation performs:

- field-reference and type checking;
- divide-by-zero and overflow checks;
- maximum expression depth and operation-count checks;
- exact rational arithmetic where possible;
- explicit finite-number checks for decimal operations;
- derivation of literal operands and permitted derived totals for
  `grounding.py`.

The compiler is fixed application code. It raises structured validation errors;
it never evaluates strings as code.

#### 4.3 Animation DSL

The animation DSL is a bounded tree of reviewed primitives:

- layout: row, column, overlay, align, padding;
- math visuals: number line, grid, bar, set of objects, shape partition, label;
- animation: appear, highlight, transform between declared nodes, wait;
- style tokens chosen from a fixed theme palette.

Each node references params or the closed expression DSL. The DSL cannot express
imports, Python names, arbitrary file paths, URLs, shell commands, environment
access, network calls, or raw Manim code. Limits include maximum nodes, labels,
text length, animation steps, coordinates, and total duration.

`DynamicTemplateScene` is human-authored once. It interprets validated DSL nodes
by calling reviewed Manim primitives. The existing timeout-bounded render
subprocess remains defense in depth for Manim crashes and resource overruns; it
is not described as a security sandbox and does not execute generated code.

### 5. Correctness and publication gate

Bedrock may propose a params schema, predicates, and examples, but AI-proposed
expected answers never count as verified fixtures.

Before a draft can enter `pending_review`, its fingerprint cluster must have at
least the configured threshold of real observations. Before it can be approved:

1. A reviewer supplies or confirms `expected_result_json` for at least five
   representative real observations, including every example shown in the
   review UI. If the source does not state an answer, the reviewer computes and
   records it.
2. The reviewer supplies at least one negative fixture for each guard predicate
   or accepts a deterministic mutation generated from a verified positive
   fixture.
3. Extraction results pass grounding and produce the reviewer-verified expected
   result under the compiled expression/guard semantics.
4. All positive fixtures validate and render; all negative fixtures are rejected
   for the expected reason.
5. Boundary tests pass, including zero, negative, just-inside/outside ranges,
   maximum collection sizes, and division edge cases.
6. The reviewer explicitly confirms the plain-English mathematical contract,
   each derived value, and the rendered preview.

The validation report records fixture IDs, expected outcomes, compiler version,
renderer version, and the artifact hash. Synthetic tests validate compiler
consistency; they are never presented as independent evidence that the proposed
mathematics is correct.

### 6. Draft state machine and refinement

Allowed draft transitions are:

```text
generated → validating → pending_review → approved
                    │             └──────→ rejected
                    └──→ failed_validation

pending_review | failed_validation | rejected
                    └── feedback/refine → superseded + new generated revision
```

Approval is a server-side transaction and is allowed only when:

- status is exactly `pending_review`;
- the latest validation report is passing;
- the report's artifact hash equals the immutable draft artifact hash;
- all required verified fixtures and the human semantics confirmation exist;
- the fingerprint has no revoked live version conflict.

`failed_validation`, `rejected`, `superseded`, and stale-hash drafts cannot be
approved. The UI does not render an Approve action for them, but the server rule
is authoritative.

Refinement creates a new row; it never mutates the prior artifact. Bedrock
receives the prior DSL documents, validation failures, and reviewer feedback.
The full validation pipeline runs from the beginning. A fingerprint permits at
most five refinement rounds before the job becomes `needs_manual_authoring`.

### 7. Idempotent job triggering

Observation insertion and threshold evaluation occur in one transaction:

1. Insert the observation with its idempotency key, or return the existing row.
2. Count eligible observations for the canonical fingerprint.
3. Do nothing when an enabled version or active job already exists.
4. When the threshold is met, insert one `queued` job under the partial unique
   fingerprint constraint.

A separate worker claims jobs using a lease. Expired leases can be reclaimed.
Successful jobs do not retrigger. Failed codegen jobs use bounded exponential
backoff and may be retriggered only after the cooldown and a new eligible
observation. Validation failures create reviewable drafts and do not create an
automatic retry storm.

SQLite writes use short transactions; Bedrock calls and rendering occur outside
transactions. Compare-and-swap state transitions prevent two workers from
publishing the same job result.

### 8. Immutable dynamic loading

Introduce a `TemplateRef` carried through classification, storyboard, session
state, preview, and final render:

```json
{
  "name": "decimal_comparison_grid",
  "version_id": "uuid",
  "artifact_hash": "sha256:..."
}
```

Static templates use a versioned static reference derived from their contract
version; dynamic templates use `template_versions.id`.

The migration covers every template-bearing boundary:

- `Scene.template`;
- `TemplateOption.template`;
- `ClassificationResult` tool schemas;
- `RenderPick`;
- session requested-template mappings;
- registry lookup functions;
- render function signatures and worker arguments;
- API request/response models and frontend option state.

At classification time, the server loads one enabled-template snapshot and
builds the Bedrock tool schema with a closed enum containing static names plus
that snapshot's dynamic names. Each returned option is resolved to the snapshot's
immutable version before it leaves classification. A plain unvalidated string
from Bedrock is never used as a registry key.

`get_template(ref)` checks the artifact hash, loads the exact immutable version,
and returns `DynamicTemplateScene` plus the cached params class and compiled DSL.
It never resolves a pinned scene through the mutable stable-name pointer.

Publishing a new version moves the stable-name pointer for future
classifications but does not change existing scenes. Superseded versions remain
renderable for pinned scenes. Disabling removes a version from future snapshots;
revoking also makes render return a clear non-retryable error for existing pinned
scenes.

### 9. Classifier integration

The classifier prompt appends the enabled snapshot's
`classifier_contract_bullet` values. The tool schema and prompt use the same
snapshot, preventing a name from being described but rejected—or accepted
without a contract—because of a concurrent publish.

Dynamic template options flow through the same compatibility extraction,
grounding, storyboard review, and approval process as static options. A dynamic
extraction mismatch returns an honest `text_card` scene and records at most one
new structural observation for the candidate.

### 10. Review UI

The dev-only review UI shows:

- fingerprint fields and contributing observations;
- excluded/incorrectly tagged observations;
- verified versus missing expected results;
- params, guard, and animation DSL summaries;
- plain-English mathematical predicates and derived values;
- positive, negative, boundary, grounding, and render test results;
- immutable artifact hash and compiler/renderer versions;
- preview thumbnail/video;
- validation or artifact-integrity failures;
- Approve, Reject, and Refine actions allowed by the server state machine.

Approval requires a confirmation control for mathematical semantics and is
disabled until fixtures are complete. The API independently enforces every gate.
Reject/Refine requires feedback. No UI action sends or stores executable code.

## Error handling

- Fingerprint call fails: store the untagged observation and retry tagging with
  bounded backoff; do not lose the observation.
- Codegen fails or times out: mark the durable job failed, release its lease, and
  apply cooldown. A later eligible observation may trigger a bounded retry.
- DSL/schema compilation fails: create a `failed_validation` immutable draft with
  structured errors.
- Fixture, grounding, or render validation fails: create/update only the
  validation report; the draft remains unapprovable.
- Preview artifact is missing or hash-mismatched: fail closed, disable approval,
  and rerun validation to create a new immutable artifact.
- Enabled version artifact is corrupt: remove it from classifier snapshots.
  Rendering a pinned version fails clearly; it never falls forward to another
  version.
- Database is unavailable: the ordinary six-template application continues
  without dynamic templates; observation and authoring operations report a
  recoverable error.
- Worker crashes: its lease expires and another worker can reclaim the job.

## Testing and acceptance criteria

### Security and DSL tests

- Every params, guard, expression, and animation node type has compiler tests.
- Unknown keys/nodes, excessive depth/count/size, non-finite numbers, dangerous
  strings, external references, URLs, and arbitrary paths are rejected.
- Property tests confirm the DSL compiler never invokes `eval`, `exec`, dynamic
  imports, or source compilation.
- Fixture-generated dynamic templates render without any generated Python.
- Render timeout tests confirm the subprocess is defense in depth, not relied on
  for code isolation.

### Correctness tests

- Every predicate and arithmetic node has positive, negative, and boundary tests.
- A self-consistent but mathematically wrong guard fixture fails independent
  expected-result verification.
- Approval fails when expected results are missing, AI-only, stale, or attached
  to a different artifact hash.
- Grounding and expected-result checks are tested separately so neither is
  treated as a substitute for the other.
- `failed_validation` drafts cannot be approved through either UI or direct API.

### Observation and clustering tests

- Direct `text_card` resolution for `unsupported_shape` records one observation.
- Extraction, render, ambiguous-input, and manual-text-card cases do not pollute
  structural clusters.
- Repeated processing of one candidate is idempotent.
- Fingerprint serialization is stable across field order and formatting.
- Model/prompt/schema version changes do not silently regroup observations.

### Concurrency and durability tests

- Concurrent threshold crossings create exactly one active job.
- Lease expiry and compare-and-swap recovery do not duplicate drafts.
- Restart tests preserve observations, jobs, drafts, reviews, and versions.
- Artifact retention and reconciliation detect missing/corrupt files.
- Failure/cooldown behavior cannot create a retry storm.

### Versioning and integration tests

- The classifier tool schema accepts enabled dynamic names even though the
  original static `TemplateName` enum does not contain them.
- Every template-bearing model carries a validated `TemplateRef`.
- A scene previewed with version A renders version A after version B is
  published.
- Disabled versions disappear from new classifier snapshots.
- Revoked versions cannot render even when a scene is pinned to them.
- Prompt and tool-schema snapshots remain consistent during concurrent publish.
- An end-to-end fixture flows from structural fallback through observation,
  canonical clustering, one durable job, validation, human fixture confirmation,
  approval, classification, extraction, storyboard preview, and final render.

## Rollout

1. Add the durable store, observation event, structured fingerprinting, and job
   state machine behind disabled feature flags. Do not run codegen yet.
2. Implement and exhaustively test the DSL compilers and reviewed Manim
   primitives.
3. Add draft generation, validation, durable artifacts, and the dev review UI.
   Approval remains disabled.
4. Migrate all template-bearing contracts to immutable `TemplateRef` and run
   static-template compatibility tests.
5. Enable approval for local development after the publication-gate tests pass.
6. Enable dynamic classifier snapshots only after an approved fixture template
   completes the full integration suite.

Each phase can be disabled independently. Turning off dynamic templates leaves
the current six static templates and `text_card` behavior intact.
