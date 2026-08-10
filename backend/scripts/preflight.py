"""Deploy-time and CI-time preflight for the backend's runtime deps.

Runs a small set of self-contained checks that would otherwise only fail
when a real request hits the affected code path. Each check prints a
single `OK  <name>` or `FAIL <name>: <detail>` line so a CI log or a
container healthcheck reads at a glance. Exits nonzero on any failure so
the caller can treat "some check failed" as a boot refusal.

Explicitly out of scope:
- Live Bedrock reachability (needs credentials — checked via schema and
  presence only, not by calling `converse`).
- A full LaTeX render of a MathTex glyph (the pytest suite covers that,
  and it takes long enough that a preflight would stop being cheap).
- Anything that mutates real state — every check works in a temp dir.

Invoke: `python -m scripts.preflight` from the backend/ directory. In
CI, wire this in before pytest so a system-dep drift fails fast with a
diagnostic instead of a mysterious per-test error later.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PASS = "OK  "
FAIL = "FAIL"


def _run_binary_version(binary: str, flag: str = "--version") -> tuple[bool, str]:
    """Confirm a binary is on PATH and can print a version.

    We do not parse the version — the check exists to catch "binary
    missing" and "binary present but broken" (nonzero exit or crash).
    """
    if shutil.which(binary) is None:
        return False, f"{binary!r} not on PATH"
    try:
        result = subprocess.run(
            [binary, flag], capture_output=True, text=True, timeout=10
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"{binary!r} {flag} crashed: {exc}"
    if result.returncode != 0:
        return False, f"{binary!r} {flag} exited {result.returncode}: {result.stderr.strip()[:200]}"
    first = (result.stdout or result.stderr).splitlines()[0].strip() if (result.stdout or result.stderr) else ""
    return True, first[:200]


def check_ffmpeg() -> tuple[bool, str]:
    # ffmpeg uses single-dash `-version`; `--version` parses as an
    # end-of-options marker followed by an input filename on some builds
    # and exits nonzero.
    return _run_binary_version("ffmpeg", flag="-version")


def check_latex() -> tuple[bool, str]:
    return _run_binary_version("latex")


def check_dvisvgm() -> tuple[bool, str]:
    return _run_binary_version("dvisvgm")


def check_manim_import() -> tuple[bool, str]:
    try:
        import manim  # noqa: F401
    except Exception as exc:
        return False, f"import manim failed: {exc}"
    return True, f"manim {getattr(manim, '__version__', 'unknown')}"


def check_manim_render() -> tuple[bool, str]:
    """Render a Text-only Manim scene to an MP4.

    Uses Pango-based `Text` so the check does not require LaTeX. If
    Manim, Pango, Cairo, or ffmpeg are subtly broken this fails with the
    real Manim error rather than a downstream mystery.
    """
    try:
        from manim import Scene, Text, config
    except Exception as exc:
        return False, f"import manim failed: {exc}"

    class _Probe(Scene):
        def construct(self):
            self.add(Text("preflight"))
            self.wait(0.05)

    with tempfile.TemporaryDirectory() as tmp:
        prev_media = config.media_dir
        prev_quality = config.quality
        try:
            config.media_dir = tmp
            config.quality = "low_quality"
            try:
                _Probe().render()
            except Exception as exc:
                return False, f"Manim render crashed: {exc}"
            mp4s = list(Path(tmp).rglob("*.mp4"))
            if not mp4s:
                return False, "Manim render produced no MP4"
            return True, f"rendered {mp4s[0].name} ({mp4s[0].stat().st_size} bytes)"
        finally:
            config.media_dir = prev_media
            config.quality = prev_quality


def check_bedrock_config() -> tuple[bool, str]:
    """No live call — schema and presence only.

    A live Bedrock call would need real credentials and would tie the
    preflight to network availability. What we can catch here without
    either: (a) a missing model id, and (b) that `boto3.client` accepts
    the resolved config without complaining. The `NoCredentialsError`
    handler in `app.main` catches the runtime case.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.bedrock_model_id:
        return False, "bedrock_model_id is empty"
    if not settings.aws_region:
        return False, "aws_region is empty"
    try:
        import boto3  # noqa: F401
    except Exception as exc:
        return False, f"import boto3 failed: {exc}"
    has_creds = bool(
        settings.aws_access_key_id
        or os.environ.get("AWS_ACCESS_KEY_ID")
        or os.environ.get("AWS_PROFILE")
    )
    creds_note = "credentials present" if has_creds else "no credentials (Bedrock calls will 503)"
    return True, f"model={settings.bedrock_model_id} region={settings.aws_region} — {creds_note}"


def check_writable_storage() -> tuple[bool, str]:
    """Every directory the app writes to must be creatable + writable.

    Missing directories are created — the app does the same on demand,
    so a preflight that failed on absence would report a false negative.
    """
    from app.config import get_settings

    settings = get_settings()
    to_check: list[Path] = [
        settings.meta_artifact_root,
        settings.meta_db_path.parent,
    ]
    problems: list[str] = []
    for path in to_check:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".preflight-write"
            probe.write_bytes(b"x")
            probe.unlink()
        except Exception as exc:
            problems.append(f"{path}: {exc}")
    if problems:
        return False, "; ".join(problems)
    return True, ", ".join(str(p) for p in to_check)


def check_feature_flags() -> tuple[bool, str]:
    """Not a pass/fail check — prints the resolved flag values so the
    deploy log names the feature set that is actually live. Always OK.
    """
    from app.config import get_settings

    settings = get_settings()
    flags = {
        "meta_templates_enabled": settings.meta_templates_enabled,
        "meta_codegen_enabled": settings.meta_codegen_enabled,
        "meta_approval_enabled": settings.meta_approval_enabled,
        "meta_dynamic_classifier_enabled": settings.meta_dynamic_classifier_enabled,
        "session_cookie_secure": settings.session_cookie_secure,
    }
    return True, ", ".join(f"{k}={v}" for k, v in flags.items())


# (name, check, required). `required=False` means the check runs but a
# failure is a warning, not a preflight failure — for optional deps like
# LaTeX when the deploy only serves text-only templates.
CHECKS: list[tuple[str, callable, bool]] = [
    ("ffmpeg", check_ffmpeg, True),
    ("latex", check_latex, True),
    ("dvisvgm", check_dvisvgm, True),
    ("manim import", check_manim_import, True),
    ("manim render", check_manim_render, True),
    ("bedrock config", check_bedrock_config, True),
    ("writable storage", check_writable_storage, True),
    ("feature flags", check_feature_flags, True),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="NAME",
        help="Skip a check by name (may repeat). Use for deploys that intentionally omit a dep.",
    )
    args = parser.parse_args()
    skip = set(args.skip)

    failures = 0
    for name, check, required in CHECKS:
        if name in skip:
            print(f"SKIP {name:20s} (via --skip)")
            continue
        try:
            ok, detail = check()
        except Exception as exc:
            ok, detail = False, f"unhandled exception: {exc!r}"
        prefix = PASS if ok else FAIL
        print(f"{prefix} {name:20s} {detail}")
        if not ok and required:
            failures += 1

    if failures:
        print(f"\npreflight FAILED — {failures} required check(s) failed")
        return 1
    print("\npreflight OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
