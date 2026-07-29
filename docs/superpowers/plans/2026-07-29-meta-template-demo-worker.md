# Meta-template Demo Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the standalone meta-template queue worker and make the complete dev review/publish flow reachable through the Vite interface for a local demo.

**Architecture:** Keep queue semantics in `app.meta.generation_pipeline.run_generation_job`; the standalone worker is a small polling scheduler with injected processing and waiting dependencies for deterministic tests. Vite proxies the review API without changing panel fetches. Safe disabled defaults and a README runbook document the three-process demo.

**Tech Stack:** Python 3.11+, pytest, FastAPI/SQLAlchemy existing pipeline, React/Vite/Vitest, Markdown.

## Global Constraints

- Meta-template, code-generation, approval, and dynamic-classifier flags remain disabled by default.
- The worker runs as a process separate from FastAPI.
- The worker does not duplicate job claim, lease, retry, validation, or completion logic.
- Empty queues and unexpected failures must not create a busy loop.
- Ctrl-C exits cleanly with status zero.
- The real `backend/.env` is user-owned and must not be modified.
- No new dependencies.

---

### Task 1: Standalone polling worker

**Files:**
- Create: `backend/tests/scripts/__init__.py`
- Create: `backend/tests/scripts/test_meta_worker.py`
- Modify: `backend/scripts/meta_worker.py`

**Interfaces:**
- Consumes: `run_generation_job(*, owner: str) -> TemplateDraft | None`.
- Produces: `run_worker(*, owner: str, process_one: Callable = run_generation_job, wait: Callable = time.sleep, poll_interval: float = 2.0) -> None`.
- Produces: `main() -> int`, invoked by `python -m scripts.meta_worker`.

- [ ] **Step 1: Write failing worker-loop tests**

Create tests that inject finite processor functions:

```python
from types import SimpleNamespace
from unittest.mock import Mock

from scripts import meta_worker


def test_worker_immediately_checks_again_after_producing_a_draft():
    process_one = Mock(side_effect=[SimpleNamespace(id="draft-1"), KeyboardInterrupt])
    wait = Mock()
    try:
        meta_worker.run_worker(
            owner="demo-worker", process_one=process_one, wait=wait, poll_interval=0.25
        )
    except KeyboardInterrupt:
        pass
    assert process_one.call_count == 2
    wait.assert_not_called()


def test_worker_waits_after_an_idle_iteration():
    process_one = Mock(side_effect=[None, KeyboardInterrupt])
    wait = Mock()
    try:
        meta_worker.run_worker(
            owner="demo-worker", process_one=process_one, wait=wait, poll_interval=0.25
        )
    except KeyboardInterrupt:
        pass
    wait.assert_called_once_with(0.25)


def test_worker_contains_unexpected_errors_and_waits(caplog):
    process_one = Mock(side_effect=[RuntimeError("boom"), KeyboardInterrupt])
    wait = Mock()
    try:
        meta_worker.run_worker(
            owner="demo-worker", process_one=process_one, wait=wait, poll_interval=0.25
        )
    except KeyboardInterrupt:
        pass
    wait.assert_called_once_with(0.25)
    assert "Unexpected meta worker iteration failure" in caplog.text
```

Also test `main()` with patched settings and `run_worker`:

```python
def test_main_exits_without_polling_when_feature_is_disabled(monkeypatch):
    run_worker = Mock()
    monkeypatch.setattr(meta_worker, "get_settings", lambda: SimpleNamespace(
        meta_templates_enabled=False, meta_codegen_enabled=True
    ))
    monkeypatch.setattr(meta_worker, "run_worker", run_worker)
    assert meta_worker.main() == 0
    run_worker.assert_not_called()


def test_main_turns_keyboard_interrupt_into_clean_exit(monkeypatch):
    monkeypatch.setattr(meta_worker, "get_settings", lambda: SimpleNamespace(
        meta_templates_enabled=True, meta_codegen_enabled=True
    ))
    monkeypatch.setattr(meta_worker, "run_worker", Mock(side_effect=KeyboardInterrupt))
    assert meta_worker.main() == 0
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd backend
.venv/bin/pytest tests/scripts/test_meta_worker.py -v
```

Expected: failures because `run_worker` does not exist and enabled `main()` still raises `NotImplementedError`.

- [ ] **Step 3: Implement the minimal worker**

Replace the Phase-1 stub with:

```python
import logging
import os
import socket
from time import sleep
from typing import Callable

from app.config import get_settings
from app.meta.generation_pipeline import run_generation_job

POLL_INTERVAL_SECONDS = 2.0


def run_worker(
    *,
    owner: str,
    process_one: Callable = run_generation_job,
    wait: Callable[[float], None] = sleep,
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> None:
    while True:
        try:
            draft = process_one(owner=owner)
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("Unexpected meta worker iteration failure")
            wait(poll_interval)
            continue
        if draft is None:
            wait(poll_interval)
            continue
        logger.info("Generated meta-template draft %s", draft.id)


def main() -> int:
    settings = get_settings()
    if not settings.meta_templates_enabled or not settings.meta_codegen_enabled:
        logger.info("Meta-template code generation is disabled; worker exiting")
        return 0
    owner = f"{socket.gethostname()}:{os.getpid()}"
    logger.info("Meta-template worker starting as %s", owner)
    try:
        run_worker(owner=owner)
    except KeyboardInterrupt:
        logger.info("Meta-template worker stopped")
    return 0
```

- [ ] **Step 4: Run focused worker tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/pytest tests/scripts/test_meta_worker.py -v
```

Expected: all worker tests pass.

- [ ] **Step 5: Run related generation tests**

Run:

```bash
cd backend
.venv/bin/pytest tests/meta/test_generation_pipeline.py tests/meta/test_job_lease.py -v
```

Expected: all tests pass.

### Task 2: Vite review-API proxy

**Files:**
- Create: `frontend/vite.config.test.js`
- Modify: `frontend/vite.config.js`

**Interfaces:**
- Produces: Vite `server.proxy["/meta"] === "http://localhost:8000"`.
- Preserves: every existing proxy target and frontend test configuration.

- [ ] **Step 1: Write a failing configuration test**

```javascript
import { describe, expect, it } from 'vitest'
import config from './vite.config'

describe('Vite development proxy', () => {
  it('forwards the meta-template review API to the backend', () => {
    expect(config.server.proxy['/meta']).toBe('http://localhost:8000')
  })
})
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
cd frontend
npm test -- vite.config.test.js
```

Expected: fail because `config.server.proxy["/meta"]` is undefined.

- [ ] **Step 3: Add the proxy entry**

Add this alongside the existing routes:

```javascript
'/meta': 'http://localhost:8000',
```

- [ ] **Step 4: Run the configuration test and verify GREEN**

Run:

```bash
cd frontend
npm test -- vite.config.test.js
```

Expected: pass.

### Task 3: Demo-safe configuration and runbook

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`

**Interfaces:**
- Documents: safe disabled defaults for every meta-template feature flag and a blank reviewer token.
- Documents: database migration, worker startup, unsupported-shape trigger, review/approval flow, and second-problem dynamic-template verification.

- [ ] **Step 1: Expand `.env.example` without enabling features by default**

Append:

```dotenv
# Dev-only meta-template authoring system. Enable explicitly for a local demo.
META_TEMPLATES_ENABLED=false
META_CODEGEN_ENABLED=false
META_APPROVAL_ENABLED=false
META_DYNAMIC_CLASSIFIER_ENABLED=false
META_REVIEWER_TOKEN=
FINGERPRINT_OBSERVATION_THRESHOLD=5
```

- [ ] **Step 2: Add a concise README demo section**

Document:

1. Copy the six demo values into the real `.env`, changing the four booleans to
   `true`, setting a disposable token, and lowering the threshold to `1`.
2. Run `../.venv/bin/alembic upgrade head`.
3. Start `./scripts/run-backend.sh`, `./scripts/run-frontend.sh`, and
   `cd backend && ../.venv/bin/python -m scripts.meta_worker`.
4. Upload a known unsupported geometry problem and build its text-card
   storyboard.
5. Open `http://localhost:5173/?meta-review`, load with the token, review, and
   approve.
6. Upload a structurally similar second problem and select/render the approved
   dynamic template.
7. Include troubleshooting for no queued job/draft, failed validation,
   credentials, and missing render dependencies.

- [ ] **Step 3: Validate documentation and configuration formatting**

Run:

```bash
git diff --check
```

Expected: exit code zero.

### Task 4: Full verification

**Files:**
- No new files.

**Interfaces:**
- Verifies all backend, frontend, and production-build behavior affected by the change.

- [ ] **Step 1: Run the complete backend suite**

```bash
cd backend
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the complete frontend suite**

```bash
cd frontend
npm test
```

Expected: all tests pass.

- [ ] **Step 3: Build the frontend**

```bash
cd frontend
npm run build
```

Expected: Vite production build succeeds.

- [ ] **Step 4: Inspect the final diff and status**

```bash
git diff --check
git status --short
git diff -- backend/scripts/meta_worker.py backend/tests/scripts/test_meta_worker.py frontend/vite.config.js frontend/vite.config.test.js backend/.env.example README.md
```

Expected: only the intended demo-worker, proxy, configuration, test, and runbook changes appear; pre-existing `CLAUDE.md` remains untouched.

