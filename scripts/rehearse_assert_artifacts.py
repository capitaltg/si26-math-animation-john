"""Verify the rehearsal actually produced preview artifacts.

Invoked at the end of scripts/rehearse-clean.sh, after the rotation demo
end-to-end test has run. The pytest tmp_path holding the MP4 is torn
down by pytest at exit, so the observable signal that the pipeline
touched disk is the META_ARTIFACT_ROOT tree — render_preview_and_probe
writes its preview PNG + probe manifest there and does NOT clean up.

Exits nonzero if the artifact root is empty or missing, which means the
supported path did not actually reach the preview render.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(root_arg: str) -> int:
    root = Path(root_arg)
    if not root.is_dir():
        print(f"FAIL rehearsal artifact root missing: {root}")
        return 1
    files = [p for p in root.rglob("*") if p.is_file()]
    if not files:
        print(f"FAIL rehearsal artifact root empty: {root}")
        return 1
    total_bytes = sum(p.stat().st_size for p in files)
    print(f"OK   rehearsal artifacts: {len(files)} files, {total_bytes} bytes under {root}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: rehearse_assert_artifacts.py <artifact_root>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
