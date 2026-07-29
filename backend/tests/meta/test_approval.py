import json
import threading
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.meta import db, models
from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.drafts import create_generated_draft
from app.meta.models import (
    DRAFT_APPROVED,
    DRAFT_GENERATED,
    DRAFT_PENDING_REVIEW,
    TEMPLATE_VERSION_DISABLED,
    TEMPLATE_VERSION_ENABLED,
    TEMPLATE_VERSION_REVOKED,
)
from app.meta.versions import DSL_COMPILER_VERSION, DYNAMIC_RENDERER_VERSION

import app.meta.approval as approval
from app.meta.approval import (
    ApprovalConflictError,
    ApprovalPreconditionError,
    DraftNotApprovableError,
    DraftNotFoundError,
    RevokedConflictError,
    TemplateNameConflictError,
    approve_draft_service,
)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: eng)
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


def _fresh(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _now():
    return datetime(2026, 7, 28, tzinfo=timezone.utc)


def _proposal(*, positive_count, obs_prefix):
    fixtures = []
    for i in range(positive_count):
        fixtures.append(
            ProposedFixture(
                kind="positive",
                expected_outcome="accept",
                observation_id=f"obs-{obs_prefix}-{i}",
                params={"n": 5},
            )
        )
    fixtures.append(ProposedFixture(kind="negative", expected_outcome="reject", params={"n": -1}))
    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
        ),
        guard_document=GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=FieldRefNode(field="n"))],
        ),
        answer_expression=FieldRefNode(field="n"),
        animation_document=AnimationDocument(root={"kind": "label", "text": "n"}),
        classifier_bullet="use for X",
        fixtures=fixtures,
    )


def _seed_draft(
    session,
    *,
    draft_id="draft-1",
    job_id=None,
    fingerprint_key="k1",
    positive_count=5,
    status=DRAFT_PENDING_REVIEW,
    passed=True,
    report_hash=None,
    coverage=None,
    structural_ok=True,
    set_expected_result=True,
    include_report=True,
):
    job_id = job_id or f"job-{draft_id}"
    job = models.GenerationJob(
        id=job_id, fingerprint_key=fingerprint_key, fingerprint_version=1,
        fingerprint_json="{}", trigger_observation_ids="[]", status=models.JOB_SUCCEEDED,
        created_at=_now(), updated_at=_now(),
    )
    session.add(job)
    for i in range(positive_count):
        session.add(models.FallbackObservation(
            id=f"obs-{draft_id}-{i}", candidate_id=f"cand-{draft_id}-{i}",
            source_excerpt="there are 5 apples", grade_level=2,
            observation_kind="unsupported_shape", excluded=False, created_at=_now(),
        ))
    session.flush()

    draft = create_generated_draft(
        session, new_id=draft_id, job=job,
        proposal=_proposal(positive_count=positive_count, obs_prefix=draft_id),
        now=_now(),
    )
    # Mark positive fixtures human-confirmed (expected_result present) and passing.
    for fx in session.query(models.TemplateDraftFixture).filter_by(draft_id=draft.id).all():
        if fx.kind == "positive":
            if set_expected_result:
                fx.expected_result_json = json.dumps({"answer": "5"})
            fx.structural_check_passed = structural_ok
        else:
            fx.structural_check_passed = True

    draft.status = status
    draft.preview_artifact_hash = "preview-hash"
    if include_report:
        cov = coverage if coverage is not None else [0]
        report = {
            "passed": passed,
            "compile_error": None,
            "fixture_results": [],
            "preview_ok": passed,
            "preview_error": None,
            "artifact_hash": report_hash if report_hash is not None else draft.artifact_hash,
            "compiler_version": DSL_COMPILER_VERSION,
            "renderer_version": DYNAMIC_RENDERER_VERSION,
            "negative_predicate_coverage": cov,
        }
        draft.validation_report_json = json.dumps(report)
    session.flush()
    session.commit()
    return draft


# ---------------------------------------------------------------- happy path


def test_approve_publishes_enabled_version_and_durable_review(engine, session):
    draft = _seed_draft(session, draft_id="draft-1", fingerprint_key="k1")

    version = approve_draft_service(
        draft_id="draft-1", template_name="apples_count",
        reviewer_label="dev", math_semantics_confirmed=True,
    )
    assert version.status == TEMPLATE_VERSION_ENABLED
    assert version.template_name == "apples_count"
    assert version.draft_id == "draft-1"
    assert version.artifact_hash == draft.artifact_hash

    check = _fresh(engine)
    reloaded = check.get(models.TemplateDraft, "draft-1")
    assert reloaded.status == DRAFT_APPROVED

    versions = check.query(models.TemplateVersion).filter_by(fingerprint_key="k1").all()
    assert len(versions) == 1
    assert versions[0].status == TEMPLATE_VERSION_ENABLED

    reviews = check.query(models.TemplateReview).filter_by(draft_id="draft-1").all()
    assert len(reviews) == 1
    assert reviews[0].decision == "approve"
    assert reviews[0].reviewer_label == "dev"
    assert reviews[0].math_semantics_confirmed is True
    check.close()


# ------------------------------------------------ preconditions (in order)


def test_unknown_draft_raises_not_found(engine, session):
    with pytest.raises(DraftNotFoundError):
        approve_draft_service(
            draft_id="nope", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_wrong_status_raises_not_approvable(engine, session):
    _seed_draft(session, draft_id="draft-1", status=DRAFT_GENERATED)
    with pytest.raises(DraftNotApprovableError):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_unconfirmed_semantics_raises_precondition(engine, session):
    _seed_draft(session, draft_id="draft-1")
    with pytest.raises(ApprovalPreconditionError):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=False,
        )


def test_missing_report_raises_precondition(engine, session):
    _seed_draft(session, draft_id="draft-1", include_report=False)
    with pytest.raises(ApprovalPreconditionError):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_failed_report_raises_precondition(engine, session):
    _seed_draft(session, draft_id="draft-1", passed=False)
    with pytest.raises(ApprovalPreconditionError):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_stale_hash_raises_precondition(engine, session):
    _seed_draft(session, draft_id="draft-1", report_hash="sha256:stale")
    with pytest.raises(ApprovalPreconditionError):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


@pytest.mark.parametrize(
    ("runtime_key", "active_version"),
    [
        ("compiler_version", DSL_COMPILER_VERSION),
        ("renderer_version", DYNAMIC_RENDERER_VERSION),
    ],
)
def test_stale_validation_runtime_version_raises_precondition(
    engine, session, runtime_key, active_version
):
    draft = _seed_draft(session, draft_id="draft-1")
    report = json.loads(draft.validation_report_json)
    report[runtime_key] = active_version - 1
    draft.validation_report_json = json.dumps(report)
    session.commit()

    with pytest.raises(ApprovalPreconditionError, match="stale"):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_incomplete_predicate_coverage_raises_precondition(engine, session):
    _seed_draft(session, draft_id="draft-1", coverage=[])
    with pytest.raises(ApprovalPreconditionError):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_insufficient_real_fixtures_raises_precondition(engine, session):
    _seed_draft(session, draft_id="draft-1", positive_count=4)
    with pytest.raises(ApprovalPreconditionError):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_missing_expected_result_not_counted_raises_precondition(engine, session):
    # Fixtures with no human-confirmed expected_result must not count toward the
    # minimum-real-fixture threshold even though observation_id is set.
    _seed_draft(session, draft_id="draft-1", set_expected_result=False)
    with pytest.raises(ApprovalPreconditionError):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_revoked_fingerprint_raises_revoked_conflict(engine, session):
    _seed_draft(session, draft_id="draft-1", fingerprint_key="k1")
    revoked = models.TemplateVersion(
        id="ver-revoked", fingerprint_key="k1", template_name="old_name",
        draft_id=None, artifact_hash="sha256:old", status=TEMPLATE_VERSION_REVOKED,
        created_at=_now(), updated_at=_now(),
    )
    session.add(revoked)
    session.commit()
    with pytest.raises(RevokedConflictError):
        approve_draft_service(
            draft_id="draft-1", template_name="apples", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


@pytest.mark.parametrize("bad_name", ["Bad", "1abc", "has space", "with-dash", "", "UPPER"])
def test_invalid_template_name_raises_name_conflict(engine, session, bad_name):
    _seed_draft(session, draft_id="draft-1")
    with pytest.raises(TemplateNameConflictError):
        approve_draft_service(
            draft_id="draft-1", template_name=bad_name, reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_name_collision_across_fingerprint_raises_name_conflict(engine, session):
    _seed_draft(session, draft_id="draft-1", fingerprint_key="k1")
    other = models.TemplateVersion(
        id="ver-other", fingerprint_key="k2", template_name="taken",
        draft_id=None, artifact_hash="sha256:other", status=TEMPLATE_VERSION_ENABLED,
        created_at=_now(), updated_at=_now(),
    )
    session.add(other)
    session.commit()
    with pytest.raises(TemplateNameConflictError):
        approve_draft_service(
            draft_id="draft-1", template_name="taken", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_same_name_same_fingerprint_is_allowed(engine, session):
    # A prior enabled version of the SAME fingerprint keeping the same name is
    # not a collision (it gets superseded, not blocked).
    _seed_draft(session, draft_id="draft-1", fingerprint_key="k1")
    prior = models.TemplateVersion(
        id="ver-prior", fingerprint_key="k1", template_name="stable",
        draft_id=None, artifact_hash="sha256:prior", status=TEMPLATE_VERSION_ENABLED,
        created_at=_now(), updated_at=_now(),
    )
    session.add(prior)
    session.commit()
    version = approve_draft_service(
        draft_id="draft-1", template_name="stable", reviewer_label="dev",
        math_semantics_confirmed=True,
    )
    assert version.status == TEMPLATE_VERSION_ENABLED


# ------------------------------------------- supersede without deleting


def test_second_draft_supersedes_first_without_deleting(engine, session):
    _seed_draft(session, draft_id="draft-1", job_id="job-1", fingerprint_key="k1")
    first = approve_draft_service(
        draft_id="draft-1", template_name="stable", reviewer_label="dev",
        math_semantics_confirmed=True,
    )
    first_id = first.id

    _seed_draft(session, draft_id="draft-2", job_id="job-2", fingerprint_key="k1")
    second = approve_draft_service(
        draft_id="draft-2", template_name="stable", reviewer_label="dev",
        math_semantics_confirmed=True,
    )

    check = _fresh(engine)
    versions = {v.id: v for v in check.query(models.TemplateVersion).filter_by(fingerprint_key="k1").all()}
    assert len(versions) == 2
    # first retained (not deleted) but disabled; second enabled
    assert versions[first_id].status == TEMPLATE_VERSION_DISABLED
    assert versions[second.id].status == TEMPLATE_VERSION_ENABLED
    enabled = [v for v in versions.values() if v.status == TEMPLATE_VERSION_ENABLED]
    assert len(enabled) == 1
    # prior version still independently loadable via its immutable draft link
    assert versions[first_id].draft_id == "draft-1"
    check.close()


# ------------------------------------------------- concurrency race


def test_concurrent_double_approve_yields_one_version_one_conflict(engine, session, monkeypatch):
    _seed_draft(session, draft_id="draft-1", fingerprint_key="k1")

    b_reached_claim = threading.Event()
    b_may_claim = threading.Event()
    state = {"b_thread_id": None}
    tls = threading.local()

    real_update = approval.update

    def wrapped_update(entity):
        # Only pause the worker (B) at its first update (the draft claim), so B
        # has already read pending_review, then let A publish fully first.
        if threading.get_ident() == state["b_thread_id"] and not getattr(tls, "paused", False):
            tls.paused = True
            b_reached_claim.set()
            assert b_may_claim.wait(timeout=15)
        return real_update(entity)

    monkeypatch.setattr(approval, "update", wrapped_update)

    results = {}

    def run_b():
        state["b_thread_id"] = threading.get_ident()
        try:
            results["b"] = approve_draft_service(
                draft_id="draft-1", template_name="apples", reviewer_label="dev-b",
                math_semantics_confirmed=True,
            )
        except Exception as exc:  # noqa: BLE001
            results["b_exc"] = exc

    t = threading.Thread(target=run_b)
    t.start()
    assert b_reached_claim.wait(timeout=15)

    # A runs fully (main thread; wrapper passes through) and publishes.
    results["a"] = approve_draft_service(
        draft_id="draft-1", template_name="apples", reviewer_label="dev-a",
        math_semantics_confirmed=True,
    )
    b_may_claim.set()
    t.join(timeout=15)

    assert "a" in results and results["a"].status == TEMPLATE_VERSION_ENABLED
    assert isinstance(results.get("b_exc"), ApprovalConflictError)

    check = _fresh(engine)
    versions = check.query(models.TemplateVersion).filter_by(fingerprint_key="k1").all()
    assert len(versions) == 1
    assert versions[0].status == TEMPLATE_VERSION_ENABLED
    # loser did not disable the winner's version
    reviews = check.query(models.TemplateReview).filter_by(draft_id="draft-1").all()
    assert len(reviews) == 1
    assert reviews[0].reviewer_label == "dev-a"
    check.close()
