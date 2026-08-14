# Clean Code Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve maintainability across backend, frontend, tests, and scripts without changing observable behavior.

**Architecture:** Keep existing public contracts and module ownership intact while extracting focused private helpers from the largest orchestration functions. Separate React side-effect orchestration from presentation, and delete commentary that repeats code or preserves change history better served by Git.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, pytest, React 18, Vitest, Vite, Bash

## Global Constraints

- Preserve public HTTP contracts, persisted data formats, template behavior, rendered output, user-facing copy, and command-line interfaces.
- Do not add dependencies solely for stylistic enforcement.
- Keep comments that explain security, concurrency, persistence, compatibility, mathematical, rendering, framework-ordering, or counterintuitive constraints.
- Avoid repository-wide formatting churn.
- Split files only across clear responsibility boundaries covered by existing tests.

---

### Task 1: Remove Runtime-Version Changelog Comments

**Files:**
- Modify: `backend/app/meta/versions.py`
- Modify: `backend/tests/meta/test_config_phase3.py`

**Interfaces:**
- Consumes: no application interfaces
- Produces: unchanged `DSL_COMPILER_VERSION: int` and `DYNAMIC_RENDERER_VERSION: int`

- [ ] **Step 1: Record the focused baseline**

Run:

```powershell
Set-Location backend
python -m pytest tests/meta/test_config_phase3.py -q
```

Expected: all tests pass and the current constants are `15` and `14`.

- [ ] **Step 2: Replace historical narration with the active invariant**

Reduce `versions.py` to concise rationale adjacent to the constants:

```python
# Bump when compiler behavior changes so stored validation reports become stale.
DSL_COMPILER_VERSION = 15

# Bump when measured or rendered output changes so stale previews cannot ship.
DYNAMIC_RENDERER_VERSION = 14
```

Delete the per-version history; Git retains it and the comments do not affect how callers use the constants.

- [ ] **Step 3: Simplify the duplicated tripwire test**

Replace the two version tests and their duplicated history with one direct contract:

```python
def test_version_constants_identify_current_runtime():
    assert DSL_COMPILER_VERSION == 15
    assert DYNAMIC_RENDERER_VERSION == 14
```

- [ ] **Step 4: Verify the focused test**

Run:

```powershell
python -m pytest tests/meta/test_config_phase3.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/meta/versions.py backend/tests/meta/test_config_phase3.py
git commit -m "refactor: trim runtime version history comments"
```

### Task 2: Decompose the Approval Transaction

**Files:**
- Modify: `backend/app/meta/approval.py`
- Test: `backend/tests/meta/test_approval.py`

**Interfaces:**
- Consumes: `TemplateDraft`, `TemplateVersion`, SQLAlchemy session, and existing approval exception classes
- Produces: unchanged `approve_draft_service(draft_id, template_name, reviewer_label, math_semantics_confirmed, owner_session_id=None, publish_shared=False) -> TemplateVersion`

- [ ] **Step 1: Run the approval characterization suite**

Run:

```powershell
Set-Location backend
python -m pytest tests/meta/test_approval.py -q
```

Expected: all approval, collision, ownership, and concurrency cases pass.

- [ ] **Step 2: Extract report validation helpers**

Add private helpers with narrow contracts:

```python
def _load_passing_report(raw_report: str | None, *, missing_message: str) -> dict:
    report = json.loads(raw_report) if raw_report else None
    if not report or report.get("passed") is not True:
        raise ApprovalPreconditionError(missing_message)
    return report


def _require_current_artifact(
    report: dict,
    artifact_hash: str,
    *,
    stale_message: str,
) -> None:
    if report.get("artifact_hash") != artifact_hash:
        raise ApprovalPreconditionError(stale_message)
```

Call them from `approve_draft_service` without changing the existing error text.

- [ ] **Step 3: Extract draft and fixture preconditions**

Introduce:

```python
def _require_approvable_draft(session, draft_id: str) -> TemplateDraft:
    draft = session.get(TemplateDraft, draft_id)
    if draft is None:
        raise DraftNotFoundError(f"Unknown draft {draft_id}")
    if draft.status != DRAFT_PENDING_REVIEW:
        raise DraftNotApprovableError(
            f"Draft {draft_id} is not approvable in status {draft.status}"
        )
    return draft


def _verified_fixture_count(session, draft_id: str) -> int:
    return session.execute(
        select(func.count(func.distinct(TemplateDraftFixture.observation_id)))
        .select_from(TemplateDraftFixture)
        .where(
            TemplateDraftFixture.draft_id == draft_id,
            TemplateDraftFixture.kind == "positive",
            TemplateDraftFixture.observation_id.isnot(None),
            TemplateDraftFixture.expected_result_json.isnot(None),
            TemplateDraftFixture.structural_check_passed.is_(True),
        )
    ).scalar_one()


def _require_publishable_draft(
    session,
    draft: TemplateDraft,
    *,
    math_semantics_confirmed: bool,
    effective_owner: str | None,
) -> None:
    if math_semantics_confirmed is not True:
        raise ApprovalPreconditionError(
            "Mathematical-semantics confirmation is required for approval"
        )

    report = _load_passing_report(
        draft.validation_report_json,
        missing_message="Draft has no passing validation report",
    )
    _require_current_artifact(
        report,
        draft.artifact_hash,
        stale_message="Validation report is stale: artifact hash mismatch",
    )
    quality = _load_passing_report(
        draft.quality_report_json,
        missing_message="Draft has no passing pedagogical quality report",
    )
    _require_current_artifact(
        quality,
        draft.artifact_hash,
        stale_message="Quality report is stale: artifact hash mismatch",
    )

    if (
        report.get("compiler_version") != DSL_COMPILER_VERSION
        or report.get("renderer_version") != DYNAMIC_RENDERER_VERSION
    ):
        raise ApprovalPreconditionError(
            "Validation report is stale: runtime version mismatch"
        )

    predicate_count = len(json.loads(draft.guard_document_json)["predicates"])
    if report.get("negative_predicate_coverage") != list(range(predicate_count)):
        raise ApprovalPreconditionError(
            "Validation report lacks complete negative-predicate coverage"
        )

    if _verified_fixture_count(session, draft.id) < _required_fixture_count(
        session, draft, effective_owner
    ):
        raise ApprovalPreconditionError(
            "Draft has too few verified real fixtures to publish"
        )
```

Move the existing checks without reordering them. Replace numbered comments with helper names; retain concise comments only where artifact/runtime/fixture invariants are not evident from code.

- [ ] **Step 4: Extract name and version-mutation helpers**

Introduce these exact internal boundaries:

```python
def _require_available_template_name(
    session,
    draft: TemplateDraft,
    template_name: str,
    visibility_scope: str | None,
) -> None:
    if not _TEMPLATE_NAME_RE.fullmatch(template_name):
        raise TemplateNameConflictError(f"Invalid template name {template_name!r}")
    if template_name in _STATIC_TEMPLATE_NAMES:
        raise TemplateNameConflictError(
            f"Template name {template_name!r} is reserved by a static template"
        )
    replaces_own = session.execute(
        select(func.count())
        .select_from(TemplateVersion)
        .where(
            TemplateVersion.template_name == template_name,
            TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
            TemplateVersion.fingerprint_key == draft.fingerprint_key,
            _same_owner(visibility_scope),
        )
    ).scalar_one()
    if not replaces_own and _name_is_reserved(
        session, template_name, visibility_scope
    ):
        raise TemplateNameConflictError(
            f"Template name {template_name!r} is already in use"
        )


def _disable_replaced_versions(
    session,
    draft: TemplateDraft,
    *,
    owner_session_id: str | None,
    publish_shared: bool,
    now: datetime,
) -> None:
    disable_scope = (
        or_(
            TemplateVersion.owner_session_id.is_(None),
            _same_owner(owner_session_id),
        )
        if publish_shared
        else _same_owner(owner_session_id)
    )
    session.execute(
        update(TemplateVersion)
        .where(
            TemplateVersion.fingerprint_key == draft.fingerprint_key,
            TemplateVersion.status == TEMPLATE_VERSION_ENABLED,
            disable_scope,
        )
        .values(status=TEMPLATE_VERSION_DISABLED, updated_at=now)
    )


def _new_template_version(
    draft: TemplateDraft,
    template_name: str,
    owner_session_id: str | None,
    now: datetime,
) -> TemplateVersion:
    return TemplateVersion(
        id=uuid4().hex,
        fingerprint_key=draft.fingerprint_key,
        template_name=template_name,
        draft_id=draft.id,
        artifact_hash=draft.artifact_hash,
        status=TEMPLATE_VERSION_ENABLED,
        owner_session_id=owner_session_id,
        created_at=now,
        updated_at=now,
    )
```

Keep the conditional draft claim, disabling query, insertion, and review record inside the same `meta_session()` transaction and preserve `IntegrityError` translation outside the context manager.

- [ ] **Step 5: Verify approval behavior**

Run:

```powershell
python -m pytest tests/meta/test_approval.py -q
```

Expected: every existing test passes, including double-approval and owner-scope cases.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/meta/approval.py
git commit -m "refactor: decompose draft approval transaction"
```

### Task 3: Decompose Render Batch Orchestration

**Files:**
- Modify: `backend/app/routes.py`
- Test: `backend/tests/test_render_guards.py`
- Test: `backend/tests/test_routes.py`

**Interfaces:**
- Consumes: existing in-memory `Session`, render functions, and clip store
- Produces: unchanged `POST /render` response and status behavior

- [ ] **Step 1: Run render characterization tests**

Run:

```powershell
Set-Location backend
python -m pytest tests/test_render_guards.py tests/test_routes.py -q
```

Expected: all route and guard tests pass.

- [ ] **Step 2: Extract batch claiming and release**

Add helpers that keep lock ownership explicit:

```python
def _claim_render_batch(session: Session) -> list[Scene]:
    with session.session_lock:
        approved = [
            session.scenes[scene_id]
            for scene_id in session.scene_order
            if _is_render_ready(session.scenes[scene_id])
        ]
        _require_valid_render_batch(session, approved)
        session.rendering_scene_ids.update(scene.scene_id for scene in approved)
        return approved


def _release_render_batch(session: Session, scenes: list[Scene]) -> None:
    with session.session_lock:
        for scene in scenes:
            session.rendering_scene_ids.discard(scene.scene_id)
```

Move the empty, cap, and collision checks into `_require_valid_render_batch` with identical status codes and messages.

- [ ] **Step 3: Extract one-scene rendering**

Introduce:

The exact helper interface is `_render_scene(session: Session, scene: Scene, *, deadline: float) -> ClipResult`.

Move parameter validation, cache reuse, deadline handling, reservation, rendering, current-revision publication, abort behavior, and `ClipResult` construction into this helper. Preserve comments explaining reservation versus orphan sweeping and stale-render rejection; remove comments that only label the next statement.

- [ ] **Step 4: Reduce the endpoint to orchestration**

The route body should follow this structure:

```python
approved = _claim_render_batch(session)
deadline = time.monotonic() + RENDER_JOB_DEADLINE_SECONDS
try:
    results = [_render_scene(session, scene, deadline=deadline) for scene in approved]
finally:
    _release_render_batch(session, approved)
return RenderResponse(clips=results)
```

- [ ] **Step 5: Verify render behavior**

Run:

```powershell
python -m pytest tests/test_render_guards.py tests/test_routes.py -q
```

Expected: all tests pass, including timeout, cache, concurrent-render, mid-render edit, and chained-render coverage.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/routes.py
git commit -m "refactor: separate render batch responsibilities"
```

### Task 4: Separate Template Workshop Presentation from Effects

**Files:**
- Create: `frontend/src/components/TemplateWorkshopView.jsx`
- Modify: `frontend/src/TemplateWorkshop.jsx`
- Test: `frontend/src/TemplateWorkshop.test.jsx`

**Interfaces:**
- Consumes: workshop build and draft data already owned by `TemplateWorkshop`
- Produces: unchanged default `TemplateWorkshop` component and DOM behavior

- [ ] **Step 1: Run the workshop characterization tests**

Run:

```powershell
Set-Location frontend
npm test -- --run src/TemplateWorkshop.test.jsx
```

Expected: all workshop tests pass.

- [ ] **Step 2: Move pure presentation units**

Move `stageStates`, `formatSeconds`, `capitalize`, `StageList`, `Attempts`, `ClearAction`, and `ReadyBand` to `components/TemplateWorkshopView.jsx`. Export only the two units used by the orchestrator:

Export `PendingWorkshopCard({ candidate, requesting, onRequest })` and `WorkshopBuildCard({ build, candidate, draft, approvedName, refreshFailed, elapsed, busy, error, onApprove, onReject, onClear })`. Their JSX is moved unchanged from the corresponding inline branches so class names, accessibility attributes, and copy remain stable.

Keep state and network effects in `TemplateWorkshop.jsx`; keep form-local name, confirmation, rejection, and feedback state inside `ReadyBand`.

- [ ] **Step 3: Replace inline rendering with named view components**

Map pending candidates to `PendingWorkshopCard` and builds to `WorkshopBuildCard`. Preserve keys, ARIA attributes, class names, and all user-facing text exactly.

Remove comments that narrate JSX branches. Keep concise explanations for server-clock interpolation, per-candidate request state, poll lifetime, and draft revision fetching.

- [ ] **Step 4: Verify workshop behavior**

Run:

```powershell
npm test -- --run src/TemplateWorkshop.test.jsx
```

Expected: all tests pass and fake-timer cleanup still reports no timer after terminal builds.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/TemplateWorkshop.jsx frontend/src/components/TemplateWorkshopView.jsx
git commit -m "refactor: separate workshop view from effects"
```

### Task 5: Extract Demo Render-Queue State

**Files:**
- Create: `frontend/src/lib/useRenderQueue.js`
- Modify: `frontend/src/pages/DemoShell.jsx`
- Test: `frontend/src/pages/DemoShell.test.jsx`

**Interfaces:**
- Consumes: `storyboard`, `setStoryboard`, and a toast callback
- Produces: `useRenderQueue({ storyboard, setStoryboard, pushToast }) -> { pendingRenders, setPendingRenders, renderJob, dismissRenderJob }`

- [ ] **Step 1: Run the shell characterization tests**

Run:

```powershell
Set-Location frontend
npm test -- --run src/pages/DemoShell.test.jsx
```

Expected: all upload, option, storyboard, render-drain, and notification tests pass.

- [ ] **Step 2: Extract the render queue hook**

Move `renderInFlight`, `storyboardRef`, `pendingRef`, `jobOpen`, `mountedRef`, the render dispatch effect, and render-job state into:

```js
export default function useRenderQueue({ storyboard, setStoryboard, pushToast }) {
  const [pendingRenders, setPendingRenders] = useState(new Set())
  const [renderJob, setRenderJob] = useState(null)
  const dismissRenderJob = useCallback(() => setRenderJob(null), [])
  return { pendingRenders, setPendingRenders, renderJob, dismissRenderJob }
}
```

Insert the existing refs and render-dispatch effect between state setup and `dismissRenderJob` without changing their dependency list or state-update order.

Preserve the comments explaining drain-on-completion, mid-flight additions, and why requests are not aborted. Remove comments that merely describe the adjacent state setter.

- [ ] **Step 3: Use the hook from `DemoShell`**

Replace the extracted state/effect with:

```js
const {
  pendingRenders,
  setPendingRenders,
  renderJob,
  dismissRenderJob,
} = useRenderQueue({ storyboard, setStoryboard, pushToast })
```

Preserve the context value shape so child components require no changes.

- [ ] **Step 4: Verify shell behavior**

Run:

```powershell
npm test -- --run src/pages/DemoShell.test.jsx
```

Expected: all tests pass, especially mid-flight queue draining and render-dock state retention.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/lib/useRenderQueue.js frontend/src/pages/DemoShell.jsx
git commit -m "refactor: extract demo render queue hook"
```

### Task 6: Audit Comments, Names, and Local Control Flow

**Files:**
- Modify when warranted: `backend/app/**/*.py`
- Modify when warranted: `backend/tests/**/*.py`
- Modify when warranted: `frontend/src/**/*.{js,jsx,css}`
- Modify when warranted: `frontend/e2e/**/*.js`
- Modify when warranted: `eval/**/*.py`
- Modify when warranted: `scripts/**/*.{py,sh}`

**Interfaces:**
- Consumes: the comment policy in the approved design
- Produces: behavior-identical source with redundant commentary removed and local intent made explicit

- [ ] **Step 1: Generate the complete comment inventory**

Run:

```powershell
rg -n '^\s*(#|//|/\*|\*)|TODO|FIXME|HACK|XXX' backend/app backend/tests frontend/src frontend/e2e eval scripts -g '*.py' -g '*.js' -g '*.jsx' -g '*.css' -g '*.sh'
```

Review every match. Classify it against the approved keep/remove policy.

- [ ] **Step 2: Remove historical and narrating comments**

Delete comments that name completed tickets or phases, enumerate obvious sequential statements, restate a condition, or duplicate test assertions. Examples of transformations:

```python
# 1. Draft exists and is pending review.
draft = _require_approvable_draft(session, draft_id)
```

```jsx
const [approved, setApproved] = useState({})
const [refreshFailed, setRefreshFailed] = useState({})
```

Do not remove shebangs, public contract docstrings, or rationale required to safely change the code later.

- [ ] **Step 3: Tighten comments that carry real invariants**

Rewrite verbose retained comments to lead with the reason. For example:

```python
# Reserve before rendering so the orphan sweep cannot delete an in-flight file.
output_path = store.reserve(session, suffix=".mp4")
```

Keep detailed explanations where shortening would hide a race, security boundary, mathematical constraint, or rendering invariant.

- [ ] **Step 4: Apply only obvious local cleanups exposed by the audit**

Rename ambiguous local variables such as `resp`, `prev`, or `s` only within a function when the longer name materially clarifies ownership. Replace deep conditionals with early returns or named predicates only when tests already cover the branch. Do not rename serialized fields, route parameters, React context properties, CSS classes, or public functions.

- [ ] **Step 5: Review the diff for churn and accidental behavior changes**

Run:

```powershell
git diff --check
git diff --stat
git diff -- backend/app backend/tests frontend/src frontend/e2e eval scripts
```

Expected: no whitespace errors, no user-facing copy changes, no endpoint/schema changes, and no purely stylistic mass formatting.

- [ ] **Step 6: Commit**

```powershell
git add backend/app backend/tests frontend/src frontend/e2e eval scripts
git commit -m "refactor: remove redundant code commentary"
```

### Task 7: Full Verification

**Files:**
- No source changes expected

**Interfaces:**
- Consumes: all preceding refactors
- Produces: fresh evidence that the behavior-preserving cleanup is safe

- [ ] **Step 1: Run the complete backend suite**

Run:

```powershell
Set-Location backend
python -m pytest -q
```

Expected: the default non-`rc` suite passes with zero failures.

- [ ] **Step 2: Run the complete frontend suite**

Run:

```powershell
Set-Location ../frontend
npm test
```

Expected: every Vitest file passes.

- [ ] **Step 3: Build the production frontend**

Run:

```powershell
npm run build
```

Expected: Vite exits successfully and emits the production bundle.

- [ ] **Step 4: Check Python syntax outside pytest imports**

Run:

```powershell
Set-Location ..
python -m compileall -q backend/app backend/scripts eval scripts
```

Expected: exit code `0` with no syntax errors.

- [ ] **Step 5: Perform the final comment and contract review**

Run:

```powershell
rg -n '^\s*(#|//|/\*|\*)|TODO|FIXME|HACK|XXX' backend/app backend/tests frontend/src frontend/e2e eval scripts -g '*.py' -g '*.js' -g '*.jsx' -g '*.css' -g '*.sh'
git diff HEAD~6 --check
git status --short
```

Confirm retained comments explain intent, all changed files are tracked, and the working tree contains no accidental generated output.

- [ ] **Step 6: Report verification evidence**

Record exact pass counts, build status, and any environment-bound check that could not run. Do not claim completion unless the fresh commands above support it.
