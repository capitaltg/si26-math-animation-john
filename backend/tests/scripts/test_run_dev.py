import os
import subprocess
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUN_DEV = BACKEND_ROOT.parent / "scripts" / "run-dev.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def test_run_dev_starts_all_processes_and_reaps_background_children(tmp_path):
    _write_executable(tmp_path / "run-dev.sh", RUN_DEV.read_text())
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
