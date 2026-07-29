# Unified Development Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `./scripts/run-dev.sh` launch and cleanly stop the backend, frontend, and meta-template worker as one local development command.

**Architecture:** Add a reusable worker launcher parallel to the existing backend/frontend launchers. Keep the frontend in the foreground and manage backend/worker PIDs in `run-dev.sh`; one cleanup function terminates and waits for both. A temporary fake-process integration test verifies startup and cleanup without opening ports or invoking Bedrock.

**Tech Stack:** Bash 3.2-compatible shell, Python 3.11+, pytest, existing Vite/FastAPI launchers.

## Global Constraints

- No new dependency or process manager.
- Keep feature-flag behavior inside `scripts.meta_worker`.
- Keep the frontend as the foreground process.
- Ctrl-C, TERM, or frontend exit must stop and reap backend and worker children.
- Preserve normal development when meta-template flags are disabled.
- Do not modify the real `backend/.env`.

---

### Task 1: Lifecycle regression test and unified launchers

**Files:**
- Create: `backend/tests/scripts/test_run_dev.py`
- Create: `scripts/run-meta-worker.sh`
- Modify: `scripts/run-dev.sh`

**Interfaces:**
- Produces: executable `scripts/run-meta-worker.sh`.
- Produces: `scripts/run-dev.sh` invoking sibling `run-backend.sh`, `run-meta-worker.sh`, and `run-frontend.sh`.
- Preserves: zero-argument launcher contracts.

- [ ] **Step 1: Write the failing lifecycle integration test**

The test copies the real `run-dev.sh` to `tmp_path`, creates executable fake
sibling launchers, and passes a log path through `DEV_TEST_LOG`:

```python
import os
import subprocess
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUN_DEV = BACKEND_ROOT.parent / "scripts" / "run-dev.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def test_run_dev_starts_all_processes_and_reaps_background_children(tmp_path):
    (tmp_path / "run-dev.sh").write_text(RUN_DEV.read_text())
    (tmp_path / "run-dev.sh").chmod(0o755)
    background = """#!/usr/bin/env bash
set -eu
name="$(basename "$0" .sh)"
printf '%s-started\n' "$name" >> "$DEV_TEST_LOG"
trap 'printf "%s-stopped\\n" "$name" >> "$DEV_TEST_LOG"; exit 0' TERM INT
while true; do sleep 0.05; done
"""
    _write_executable(tmp_path / "run-backend.sh", background)
    _write_executable(tmp_path / "run-meta-worker.sh", background)
    _write_executable(
        tmp_path / "run-frontend.sh",
        (
            "#!/usr/bin/env bash\n"
            "printf 'run-frontend-started\\n' >> \"$DEV_TEST_LOG\"\n"
            "sleep 0.2\n"
        ),
    )
    log_path = tmp_path / "events.log"

    result = subprocess.run(
        [str(tmp_path / "run-dev.sh")],
        env={**os.environ, "DEV_TEST_LOG": str(log_path)},
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert set(log_path.read_text().splitlines()) == {
        "run-backend-started",
        "run-meta-worker-started",
        "run-frontend-started",
        "run-backend-stopped",
        "run-meta-worker-stopped",
    }
```

- [ ] **Step 2: Run the test and verify RED**

```bash
cd backend
.venv/bin/pytest tests/scripts/test_run_dev.py -v
```

Expected: fail because current `run-dev.sh` never invokes
`run-meta-worker.sh`, so worker lifecycle events are missing.

- [ ] **Step 3: Add the worker launcher**

Create an executable Bash script that resolves `ROOT`, checks
`$ROOT/.venv/bin/python`, exports the rendering toolchain `PATH`, changes to
`$ROOT/backend`, and executes:

```bash
exec "$VENV/bin/python" -m scripts.meta_worker
```

- [ ] **Step 4: Update `run-dev.sh` process management**

Start backend and worker in the background, record both PIDs, and install:

```bash
cleanup() {
  trap - EXIT INT TERM
  kill "$BACKEND_PID" "$WORKER_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  wait "$WORKER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
```

Then execute `run-frontend.sh` in the foreground.

- [ ] **Step 5: Run lifecycle and syntax tests and verify GREEN**

```bash
cd backend
.venv/bin/pytest tests/scripts/test_run_dev.py tests/scripts/test_meta_worker.py -v
cd ..
bash -n scripts/run-dev.sh scripts/run-backend.sh scripts/run-frontend.sh scripts/run-meta-worker.sh
```

Expected: all tests pass and Bash syntax validation exits zero.

### Task 2: Documentation and complete verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents: `./scripts/run-dev.sh` as the default one-command demo startup.
- Preserves: separate-process commands as troubleshooting instructions.

- [ ] **Step 1: Update the demo startup section**

Replace the default three-terminal instructions with:

```bash
./scripts/run-dev.sh
```

Explain that it starts FastAPI, Vite, and the meta worker and that Ctrl-C stops
all three. Keep the individual commands in an optional manual-start subsection.

- [ ] **Step 2: Run full verification**

```bash
cd backend
.venv/bin/pytest -q
cd ../frontend
npm test
npm run build
cd ..
git diff --check
```

Expected: all backend/frontend tests pass, the Vite build succeeds, and diff
formatting is clean.

- [ ] **Step 3: Commit the implementation branch**

```bash
git add scripts/run-dev.sh scripts/run-meta-worker.sh \
  backend/tests/scripts/test_run_dev.py README.md
git commit -m "feat: include meta worker in dev command"
```

### Task 3: Merge and push

**Files:**
- No new files.

**Interfaces:**
- Produces: verified implementation on local and remote `main`.

- [ ] **Step 1: Fetch and fast-forward-check `origin/main`**

Fetch `origin/main`; stop for conflicts or unexpected remote divergence.

- [ ] **Step 2: Fast-forward local `main` to the implementation branch**

Merge with `--ff-only`.

- [ ] **Step 3: Verify the merged result**

Run the complete backend suite, complete frontend suite, frontend build, and
Bash syntax check from `main`.

- [ ] **Step 4: Push main**

```bash
git push origin main
```

- [ ] **Step 5: Remove the merged worktree and branch**

Remove the project-owned worktree, prune registrations, and delete the merged
feature branch.
