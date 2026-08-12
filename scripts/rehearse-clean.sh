#!/usr/bin/env bash
# Clean-environment rehearsal of the supported path (rotation demo).
#
# Rebuilds a throw-away virtualenv from a fresh clone-equivalent tree,
# runs migrations against an isolated SQLite DB, and drives the rotation
# demo lesson end-to-end (candidate -> draft -> approve -> render). Any
# state the test writes lands under a per-run scratch dir; nothing under
# backend/var is touched.
#
# The goal is not to duplicate CI — it is to prove that a machine with
# only the repo checked out and the documented external tools installed
# (Python 3.14, LaTeX, ffmpeg) can reach a rendered MP4 without any
# hidden dependency on developer state.
#
# Usage:
#   scripts/rehearse-clean.sh
#
# Exits nonzero at the first failing step; the scratch dir is preserved
# on failure so a follow-up run can inspect the venv / DB / artifacts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

REHEARSAL_ROOT="${REHEARSAL_ROOT:-$ROOT/var/rehearsal}"
STAMP="$(date +%Y%m%dT%H%M%S)"
WORKSPACE="$REHEARSAL_ROOT/$STAMP"
VENV="$WORKSPACE/.venv"
DB_DIR="$WORKSPACE/db"
ARTIFACT_ROOT="$WORKSPACE/meta_artifacts"
LOG="$WORKSPACE/rehearsal.log"

mkdir -p "$WORKSPACE" "$DB_DIR" "$ARTIFACT_ROOT"

# LaTeX (number-line labels) + Homebrew (ffmpeg) must be on PATH for
# rendering, matching run-backend.sh.
export PATH="/Library/TeX/texbin:/opt/homebrew/bin:$PATH"

# Isolate every path the app writes to under $WORKSPACE. get_settings()
# reads META_DB_PATH and META_ARTIFACT_ROOT out of env; we set the
# artifact root through the rehearsal-specific `REHEARSAL_META_ARTIFACT_ROOT`
# handshake so the `client` fixture in `test_demo_end_to_end.py` picks
# it up without an ambient `META_ARTIFACT_ROOT` in a developer/CI shell
# ever leaking into the normal test suite.
export META_DB_PATH="$DB_DIR/meta.db"
export REHEARSAL_META_ARTIFACT_ROOT="$ARTIFACT_ROOT"
export META_TEMPLATES_ENABLED=1
export META_APPROVAL_ENABLED=1

python3 --version | tee "$LOG"
echo "workspace: $WORKSPACE" | tee -a "$LOG"

step() {
  echo | tee -a "$LOG"
  echo ">>> $*" | tee -a "$LOG"
}

step "Create fresh virtualenv"
python3 -m venv "$VENV"

step "Install backend into fresh venv"
"$VENV/bin/pip" install --upgrade pip >>"$LOG" 2>&1
"$VENV/bin/pip" install -e "$ROOT/backend[dev]" >>"$LOG" 2>&1

step "Preflight (LaTeX / ffmpeg / manim / Bedrock config)"
(cd "$ROOT/backend" && "$VENV/bin/python" -m scripts.preflight) | tee -a "$LOG"

step "Migrate isolated DB to head"
(cd "$ROOT/backend" && "$VENV/bin/alembic" upgrade head) | tee -a "$LOG"

step "Drive rotation demo end-to-end"
(cd "$ROOT/backend" && "$VENV/bin/pytest" \
    tests/meta/test_demo_end_to_end.py::test_rotation_demo_slide_approves_end_to_end \
    -x -vv) | tee -a "$LOG"

step "Assert rendered artifact was written"
"$VENV/bin/python" "$SCRIPT_DIR/rehearse_assert_artifacts.py" "$ARTIFACT_ROOT" | tee -a "$LOG"

echo | tee -a "$LOG"
echo "Rehearsal PASSED. Workspace kept at $WORKSPACE" | tee -a "$LOG"
