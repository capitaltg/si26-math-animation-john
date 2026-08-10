"""Contract: approving a draft replays frozen artifacts — no Bedrock call.

An approved draft is the source of truth for a published template. The
publish step (`approve_draft_service`) verifies preconditions on the
draft's stored `scene_program_json`, validation report, and quality
report — nothing about that flow requires fresh LLM inference. If the
step ever grows a Bedrock call, deployments without credentials would
break at approve time and republished templates would drift each time
they are re-approved.

The test seeds a real, publishable draft (via the existing
`_seed_draft` helper from tests.meta.test_approval) with all reports
in place, patches `call_with_tool` at the Bedrock client boundary to
raise on invocation, then calls `approve_draft_service`. Success
proves the contract: publishing replays frozen state, not an LLM.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.meta import approval, db
from app.meta.approval import approve_draft_service
from app.meta.models import TEMPLATE_VERSION_ENABLED

# _seed_draft is a plain function (not a pytest fixture), so importing it
# is safe. The engine/session fixtures in that module are per-module and
# would not carry across if imported; local copies below.
from tests.meta.test_approval import _seed_draft


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: eng)
    # `approve_draft_service` reads meta_required_fixture_count from settings
    # to decide the per-owner fixture floor; give it a matching value so a
    # 5-fixture seed clears the bar.
    monkeypatch.setattr(
        approval,
        "get_settings",
        lambda: SimpleNamespace(meta_required_fixture_count=5),
    )
    db.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def test_approve_draft_service_never_calls_bedrock(engine, session):
    """The core republish invariant: approval consumes frozen artifacts only.

    Patching `call_with_tool` at the Bedrock-client boundary catches every
    caller — discovery, extraction, classification, stated-answer parsing.
    Any of them wired into the approve path (directly or indirectly through
    revalidation) would fail this test with a clear signal.
    """
    _seed_draft(session, draft_id="draft-1", fingerprint_key="k1")

    def _forbidden(*_args, **_kwargs):
        raise AssertionError(
            "approve_draft_service must not invoke Bedrock — publishing "
            "replays the draft's frozen scene_program_json and reports."
        )

    with patch("app.pipeline.bedrock_client.call_with_tool", side_effect=_forbidden):
        version = approve_draft_service(
            draft_id="draft-1",
            template_name="apples_count",
            reviewer_label="dev",
            math_semantics_confirmed=True,
        )

    assert version.status == TEMPLATE_VERSION_ENABLED, (
        "approve_draft_service returned a non-enabled version — a downstream "
        "step may have swallowed the AssertionError from the Bedrock stub."
    )
    assert version.template_name == "apples_count"
