# Meta-template Demo Runbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a canonical, self-contained runbook for rehearsing and presenting the local meta-template demo.

**Architecture:** Put the complete workflow in `docs/meta-template-demo.md` and replace the detailed README instructions with a concise overview and link. Verify the guide against repository paths, configuration names, UI labels, and the bundled four-slide fixture.

**Tech Stack:** Markdown, shell-based repository checks, Git

## Global Constraints

- The guide is for local developer demonstrations only.
- `docs/meta-template-demo.md` is the canonical workflow.
- The README must not retain a second full copy of the workflow.
- The guide must use `eval/fixtures/meta_template_unsupported_shapes_deck.pptx`.
- The review UI must use the backend-configured fixture threshold without
  changing configuration defaults or approval-service rules.
- Preserve the user's unrelated untracked `CLAUDE.md`.

---

### Task 1: Align the review UI with the backend fixture threshold

**Files:**
- Modify: `backend/app/meta/review_api.py`
- Modify: `backend/tests/meta/test_review_api.py`
- Modify: `frontend/src/MetaReviewPanel.jsx`
- Modify: `frontend/src/MetaReviewPanel.test.jsx`

**Interfaces:**
- Consumes: `Settings.fingerprint_observation_threshold`
- Produces: `DraftDetailOut.required_fixture_count: int` for the review panel

- [ ] **Step 1: Add failing backend coverage**

Extend `test_get_draft_detail_includes_fixtures_and_preview_url` to override
`FINGERPRINT_OBSERVATION_THRESHOLD=1`, clear the settings cache, request the
draft detail, and assert:

```python
assert body["required_fixture_count"] == 1
```

Run:

```bash
cd backend
../.venv/bin/python -m pytest tests/meta/test_review_api.py::test_get_draft_detail_includes_fixtures_and_preview_url -q
```

Expected: FAIL because `required_fixture_count` is absent.

- [ ] **Step 2: Return the configured threshold**

Add this field to `DraftDetailOut`:

```python
required_fixture_count: int
```

Set it in `_draft_detail`:

```python
required_fixture_count=get_settings().fingerprint_observation_threshold,
```

Run the focused backend test again. Expected: PASS.

- [ ] **Step 3: Add failing frontend coverage**

Set `required_fixture_count: 1` on the single-fixture `draftDetail`, give that
fixture an expected result, and add a test that enters a valid template name,
checks the mathematical-semantics checkbox, and expects **Approve and publish**
to become enabled.

Run:

```bash
cd frontend
npm test -- --run src/MetaReviewPanel.test.jsx
```

Expected: FAIL while the panel still compares against the hardcoded value five.

- [ ] **Step 4: Consume the API threshold**

Remove `FIXTURE_THRESHOLD`. Compute:

```jsx
const requiredFixtureCount = selected?.required_fixture_count ?? 5
```

Use `requiredFixtureCount` in both `canApprove` and the `Verified fixtures`
copy.

Run the focused frontend test again. Expected: PASS.

- [ ] **Step 5: Run focused suites and commit**

Run:

```bash
cd backend
../.venv/bin/python -m pytest tests/meta/test_review_api.py -q
cd ../frontend
npm test -- --run src/MetaReviewPanel.test.jsx
```

Expected: both suites pass with no failures.

Commit:

```bash
git add backend/app/meta/review_api.py backend/tests/meta/test_review_api.py frontend/src/MetaReviewPanel.jsx frontend/src/MetaReviewPanel.test.jsx
git commit -m "fix: align meta review fixture threshold"
```

---

### Task 2: Write the canonical demo runbook

**Files:**
- Create: `docs/meta-template-demo.md`

**Interfaces:**
- Consumes: `scripts/run-dev.sh`, `scripts/run-meta-worker.sh`, `backend/app/config.py`, `frontend/src/App.jsx`, `frontend/src/MetaReviewPanel.jsx`, and `eval/fixtures/meta_template_unsupported_shapes_deck.pptx`
- Produces: The canonical human-facing demo workflow linked from the README

- [ ] **Step 1: Verify repository inputs**

Run:

```bash
test -x scripts/run-dev.sh
test -x scripts/run-meta-worker.sh
test -f eval/fixtures/meta_template_unsupported_shapes_deck.pptx
rg -n "META_TEMPLATES_ENABLED|META_CODEGEN_ENABLED|META_APPROVAL_ENABLED|META_DYNAMIC_CLASSIFIER_ENABLED|META_REVIEWER_TOKEN|FINGERPRINT_OBSERVATION_THRESHOLD" backend
rg -n "Get options|Load drafts|Save fixture|Reject and request refinement|Approve and publish" frontend/src
```

Expected: all `test` commands exit successfully and every documented flag and
UI label has a current source match.

- [ ] **Step 2: Create the guide**

Write `docs/meta-template-demo.md` with these concrete sections:

```markdown
# Meta-template Demo Runbook

## What this demo proves
## Before the demo
### Install and migrate
### Configure the dev-only flags
### Confirm external dependencies
## Start the application
## Rehearsal reset
## Live demo sequence
### 1. Introduce the fixture
### 2. Seed a new template with slide 1
### 3. Watch the worker create a draft
### 4. Review and publish
### 5. Reuse the template with slide 2
### 6. Optional slides 3 and 4
## Presenter talk track
## Expected checkpoints
## Troubleshooting
## After the demo
```

The guide must include:

- `./scripts/run-dev.sh`
- `http://localhost:5173`
- `http://localhost:5173/?meta-review`
- reviewer token example `local-meta-demo`
- seed answer `{"answer": 22}`
- reuse answer `28`
- optional answers `8` and `2750`
- template name example `rectangle_perimeter`
- the requirement that `text_card` be the only compatible fallback
- the two-second worker polling interval
- explicit warnings that classification is probabilistic and the flags are
  not production-ready

- [ ] **Step 3: Check the guide for incomplete or stale copy**

Run:

```bash
rg -n "T[B]D|T[O]DO|F[I]XME|P[L]ACEHOLDER" docs/meta-template-demo.md
rg -n "run-dev.sh|meta-review|rectangle_perimeter|local-meta-demo|answer.*22" docs/meta-template-demo.md
git diff --check
```

Expected: the placeholder search has no matches, the required workflow search
finds all five concepts, and `git diff --check` exits successfully.

---

### Task 3: Make the README route to the canonical guide

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: `docs/meta-template-demo.md`
- Produces: A concise repository entry point with no duplicated step-by-step workflow

- [ ] **Step 1: Replace the detailed README section**

Replace the content from `## Meta-template demo (dev only)` through the end of
its troubleshooting list with:

```markdown
## Meta-template demo (dev only)

The meta-template system can learn a bounded, reviewable animation template
from a concrete problem that falls back to `text_card`, then reuse the
published template for structurally similar problems.

For setup, the bundled fixture deck, the live presentation sequence, expected
checkpoints, reset steps, and troubleshooting, follow the canonical
[meta-template demo runbook](docs/meta-template-demo.md).

Keep all meta-template flags disabled in production until the operational
rollout work is complete.
```

- [ ] **Step 2: Verify the README has one canonical route**

Run:

```bash
rg -n "meta-template demo runbook" README.md
rg -n "### 1\\. Prepare the backend|### 5\\. Exercise the published template|No worker draft appears" README.md
git diff --check
```

Expected: the first search finds exactly one link, the duplicated-workflow
search has no matches, and `git diff --check` exits successfully.

---

### Task 4: Verify and commit the documentation

**Files:**
- Verify: `docs/meta-template-demo.md`
- Verify: `README.md`

**Interfaces:**
- Consumes: The completed guide and README pointer
- Produces: A committed, self-contained demo runbook

- [ ] **Step 1: Validate all documented local paths**

Run:

```bash
test -f docs/meta-template-demo.md
test -f eval/fixtures/meta_template_unsupported_shapes_deck.pptx
test -x scripts/run-dev.sh
test -x scripts/run-backend.sh
test -x scripts/run-frontend.sh
test -x scripts/run-meta-worker.sh
```

Expected: every command exits with status 0.

- [ ] **Step 2: Review the final documentation diff**

Run:

```bash
git diff -- README.md docs/meta-template-demo.md
git diff --check
git status --short
```

Expected: the diff contains only the canonical guide and README routing change;
the status may also show the pre-existing untracked `CLAUDE.md`, which must
remain untouched.

- [ ] **Step 3: Commit**

Run:

```bash
git add README.md docs/meta-template-demo.md
git commit -m "docs: add meta-template demo runbook"
```

Expected: one documentation commit containing the runbook and README pointer.
