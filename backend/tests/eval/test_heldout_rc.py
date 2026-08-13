"""Held-out release-candidate eval.

Runs the rotation demo runbook (``_run_demo_lesson``) once per held-out
lesson defined in :mod:`heldout_rotation_lessons`, exactly the way the
in-tree demo runs the three lessons in ``test_demo_end_to_end``. The
supported path is: seed the classifier fallback observation, generate a
persistable draft, save the positive fixture, approve the draft,
re-probe the published program, and render a second-slide MP4.

Marked ``rc`` so a normal pytest run stays fast; opt in with

    .venv/bin/pytest backend/tests/eval -m rc -q

before freezing a release candidate. The suite fails if any held-out
lesson does not complete the runbook cleanly; the pass rate is
"all-or-nothing" on purpose -- a partial success on a held-out deck is
a regression, not a soft warning.

If a future ticket adds live-Bedrock coverage (feeding the excerpt to
the real ``propose_template_draft`` and asserting the returned draft
survives validation), place it in a sibling module that skips unless an
opt-in env var like ``RC_HELDOUT_LIVE=1`` is set -- that keeps the cost
gate explicit and out of the default RC run.
"""

from __future__ import annotations

import pytest

from tests.meta.test_demo_end_to_end import (  # noqa: F401  (imports the `client` fixture)
    _run_demo_lesson,
    client,
)
from tests.eval.heldout_rotation_lessons import HELDOUT_ROTATION_LESSONS


@pytest.mark.rc
@pytest.mark.parametrize(
    "lesson",
    HELDOUT_ROTATION_LESSONS,
    ids=[lesson.template_name for lesson in HELDOUT_ROTATION_LESSONS],
)
def test_heldout_rotation_lesson_survives_runbook(lesson, client, tmp_path):
    """Every held-out rotation lesson must reach a rendered MP4.

    The assertion is that ``_run_demo_lesson`` returned without raising
    and that the second-slide MP4 landed on disk with nonzero bytes --
    the same evidence the demo test relies on. Any earlier failure (a
    generation retry that exhausted attempts, a validation refusal, an
    approval 409, a render-worker crash) surfaces as an exception from
    inside ``_run_demo_lesson`` and fails this case with the
    line-of-failure preserved.
    """
    rendered = _run_demo_lesson(client, lesson, tmp_path)
    assert rendered.mp4_path.exists(), (
        f"held-out lesson {lesson.template_name!r} did not render an MP4"
    )
    assert rendered.mp4_path.stat().st_size > 0, (
        f"held-out lesson {lesson.template_name!r} rendered an empty MP4"
    )
