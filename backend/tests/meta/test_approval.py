import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.meta import db, models
from app.meta.dsl.expression import FieldRefNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.models import (
    DRAFT_APPROVED,
    DRAFT_GENERATED,
    DRAFT_PENDING_REVIEW,
    TEMPLATE_VERSION_DISABLED,
    TEMPLATE_VERSION_ENABLED,
    TEMPLATE_VERSION_REVOKED,
)
from app.meta.draft_generation import ProposedFixture
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.validation import compile_draft_documents, validate_proposed_fixtures
from app.meta.validation_pipeline import build_validation_report
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


def _fresh(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _now():
    return datetime(2026, 7, 28, tzinfo=timezone.utc)


def _plan():
    # Minimal but real teaching plan (single "label" visual driven only by
    # a constant string; the field "n" only appears in the answer expression),
    # just enough to satisfy TeachingPlanDocument's own validators and compile
    # via compile_teaching_plan -- this file tests approval preconditions, not
    # rendering, so the plan's pedagogical content is unimportant.
    return TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "State a whole number result.",
        "primary_visual": {"kind": "label", "ref": "n_label", "text": "value"},
        "strategy": "group_reveal",
        "beats": [
            {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "n_label"}],
             "intent": "show the value"},
            {"id": "focus", "kind": "focus", "targets": [{"visual_ref": "n_label"}],
             "intent": "focus on the value"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "n_label"}],
             "intent": "state the result"},
        ],
        "variation_seed": "approval-test",
    })


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
    quality_passed=True,
    quality_hash=None,
    include_quality_report=True,
    trigger_count=None,
    job_owner=None,
):
    job_id = job_id or f"job-{draft_id}"
    # The observations this draft was built from. The owner-scoped fixture floor
    # reads these, so they must be real rather than an empty list.
    trigger_ids = [f"obs-{draft_id}-{i}" for i in range(trigger_count if trigger_count is not None else positive_count)]
    job = models.GenerationJob(
        id=job_id, fingerprint_key=fingerprint_key, fingerprint_version=1,
        fingerprint_json="{}", trigger_observation_ids=json.dumps(trigger_ids),
        status=models.JOB_SUCCEEDED, owner_session_id=job_owner,
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

    # Built directly from real DSL document models and TemplateDraft/
    # TemplateDraftFixture rows (not via a draft-creation pipeline helper) --
    # the v2 `create_generated_draft` this fixture used to call is gone in v3;
    # persisting a candidate now requires a full ValidatedCandidate (real
    # rendered-quality probe), which is more than this file's approval-
    # precondition tests need or want to pay for.
    params_document = ParamsDocument(
        params_version=1,
        fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
    )
    guard_document = GuardDocument(
        guard_version=1,
        predicates=[PositivePredicate(value=FieldRefNode(field="n"))],
    )
    answer_expression = FieldRefNode(field="n")
    plan = _plan()
    scene_program = compile_teaching_plan(
        plan, answer_expression, frozenset({"n"}),
        CompileContext(concept_family="count_group", grade_band="K-2"),
    )
    artifact_hash = f"sha256:{draft_id}"

    draft = models.TemplateDraft(
        id=draft_id,
        job_id=job_id,
        fingerprint_key=fingerprint_key,
        fingerprint_version=1,
        fingerprint_json="{}",
        revision=1,
        params_document_json=params_document.model_dump_json(),
        guard_document_json=guard_document.model_dump_json(),
        answer_expression_json=answer_expression.model_dump_json(),
        teaching_plan_json=plan.model_dump_json(),
        scene_program_json=scene_program.model_dump_json(),
        classifier_bullet="use for X",
        dsl_schema_versions_json=json.dumps(
            {"params": 1, "guard": 1, "teaching_plan": 3, "scene": 3}
        ),
        artifact_hash=artifact_hash,
        status=status,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(draft)
    session.flush()

    for i in range(positive_count):
        session.add(models.TemplateDraftFixture(
            id=f"{draft_id}-fixture-pos-{i}",
            draft_id=draft_id,
            observation_id=f"obs-{draft_id}-{i}",
            kind="positive",
            expected_outcome="accept",
            generation_method="proposed",
            params_json=json.dumps({"n": 5}),
            expected_result_json=json.dumps({"answer": "5"}) if set_expected_result else None,
            structural_check_passed=structural_ok,
            created_at=_now(),
        ))
    session.add(models.TemplateDraftFixture(
        id=f"{draft_id}-fixture-neg",
        draft_id=draft_id,
        observation_id=None,
        kind="negative",
        expected_outcome="reject",
        generation_method="proposed",
        params_json=json.dumps({"n": -1}),
        expected_result_json=None,
        structural_check_passed=True,
        created_at=_now(),
    ))

    draft.preview_artifact_hash = "preview-hash"
    if include_report:
        cov = coverage if coverage is not None else [0]
        report = {
            "passed": passed,
            "compile_error": None,
            "fixture_results": [],
            "preview_ok": passed,
            "preview_error": None,
            "artifact_hash": report_hash if report_hash is not None else artifact_hash,
            "compiler_version": DSL_COMPILER_VERSION,
            "renderer_version": DYNAMIC_RENDERER_VERSION,
            "negative_predicate_coverage": cov,
        }
        draft.validation_report_json = json.dumps(report)
    if include_quality_report:
        quality_report = {
            "passed": quality_passed,
            "checks": [],
            "artifact_hash": quality_hash if quality_hash is not None else artifact_hash,
        }
        draft.quality_report_json = json.dumps(quality_report)
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


def test_approve_succeeds_with_a_validation_report_built_by_the_production_builder(engine, session):
    """Defect A: every other test in this file seeds validation_report_json
    with a hand-built dict shaped like ``build_validation_report``'s output --
    a shape production never actually emits (the real builder didn't even
    write an ``artifact_hash`` key). A test that constructs its own report
    literal cannot catch that class of regression. This one instead calls
    ``build_validation_report`` -- the exact function ``validate_candidate``
    calls -- against the draft's own compiled documents and real fixture
    results, so it fails immediately if the production builder ever again
    stops writing (or duplicates with a different value) the artifact_hash
    precondition 4 checks."""
    draft = _seed_draft(session, draft_id="draft-1", include_report=False)

    params_document = ParamsDocument.model_validate(json.loads(draft.params_document_json))
    guard_document = GuardDocument.model_validate(json.loads(draft.guard_document_json))
    answer_expression = FieldRefNode.model_validate(json.loads(draft.answer_expression_json))
    plan = TeachingPlanDocument.model_validate(json.loads(draft.teaching_plan_json))
    compiled = compile_draft_documents(params_document, guard_document, answer_expression, plan)

    fixtures = [
        ProposedFixture(
            kind="positive", expected_outcome="accept",
            observation_id="obs-draft-1-0", params={"n": 5},
        ),
        ProposedFixture(kind="negative", expected_outcome="reject", params={"n": -1}),
    ]
    fixture_results = validate_proposed_fixtures(fixtures, compiled, observations_by_id={})

    report = build_validation_report(
        compiled=compiled,
        fixture_results=fixture_results,
        preview_artifact_hash="preview-hash",
        artifact_hash=draft.artifact_hash,
    )
    draft.validation_report_json = json.dumps(report)
    session.commit()

    version = approve_draft_service(
        draft_id="draft-1", template_name="apples_count",
        reviewer_label="dev", math_semantics_confirmed=True,
    )
    assert version.status == TEMPLATE_VERSION_ENABLED


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


def test_missing_quality_report_raises_precondition(engine, session):
    _seed_draft(session, draft_id="draft-1", include_quality_report=False)
    with pytest.raises(ApprovalPreconditionError, match="pedagogical quality report"):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_failed_quality_report_raises_precondition(engine, session):
    _seed_draft(session, draft_id="draft-1", quality_passed=False)
    with pytest.raises(ApprovalPreconditionError, match="pedagogical quality report"):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_stale_quality_hash_raises_precondition(engine, session):
    _seed_draft(session, draft_id="draft-1", quality_hash="sha256:stale-quality")
    with pytest.raises(ApprovalPreconditionError, match="Quality report is stale"):
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


@pytest.mark.parametrize("runtime_key", ["compiler_version", "renderer_version"])
def test_previous_runtime_versions_are_stale_after_rendered_values_and_geometry_fix(
    engine, session, runtime_key
):
    draft = _seed_draft(session, draft_id="draft-1")
    report = json.loads(draft.validation_report_json)
    report[runtime_key] = 1
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


def test_duplicate_observation_fixtures_count_once(engine, session):
    draft = _seed_draft(session, draft_id="draft-1", positive_count=5)
    fixtures = (
        session.query(models.TemplateDraftFixture)
        .filter_by(draft_id=draft.id, kind="positive")
        .all()
    )
    for fixture in fixtures:
        fixture.observation_id = "obs-draft-1-0"
    session.commit()

    with pytest.raises(ApprovalPreconditionError, match="too few verified real fixtures"):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


def test_missing_expected_result_not_counted_raises_precondition(engine, session):
    # Fixtures with no human-confirmed expected_result must not count toward the
    # minimum-real-fixture threshold even though observation_id is set. This
    # trips ONLY precondition 8: both reports are present, passing and
    # hash-matching (see the assertions below), so approval reaches the
    # verified-fixture count query and is stopped by its
    # `expected_result_json.isnot(None)` clause and nothing else.
    draft = _seed_draft(session, draft_id="draft-1", set_expected_result=False)
    assert json.loads(draft.validation_report_json)["artifact_hash"] == draft.artifact_hash
    assert json.loads(draft.quality_report_json)["artifact_hash"] == draft.artifact_hash

    with pytest.raises(ApprovalPreconditionError, match="too few verified real fixtures"):
        approve_draft_service(
            draft_id="draft-1", template_name="x", reviewer_label="dev",
            math_semantics_confirmed=True,
        )


@pytest.mark.parametrize("structural_state", [False, None])
def test_unconfirmed_structural_check_not_counted_raises_precondition(
    engine, session, structural_state
):
    """Precondition 8's ``structural_check_passed.is_(True)`` clause is the
    security-relevant half of the Task 12.5 repair: ``update_fixture`` nulls
    ``structural_check_passed`` when a reviewer changes a fixture's params, and
    this clause is the *only* thing that then stops the draft from being
    approvable. Nothing tested it -- the two tests that do produce that state
    (``test_review_api.py``, ``test_review_api_v3.py``) simultaneously null
    ``validation_report_json``, so approval stops at precondition 3 and never
    reaches 8, and ``_seed_draft``'s ``structural_ok`` knob was never
    overridden. Drop the clause and the suite stayed green, silently making
    params-changed drafts approvable again.

    Both reports are left intact, passing and hash-matching, so this trips
    precondition 8 and only precondition 8. ``None`` is the state
    ``update_fixture`` actually writes; ``False`` is a failed structural check.
    """
    draft = _seed_draft(session, draft_id="draft-1", structural_ok=structural_state)
    assert json.loads(draft.validation_report_json)["passed"] is True
    assert json.loads(draft.validation_report_json)["artifact_hash"] == draft.artifact_hash
    assert json.loads(draft.quality_report_json)["artifact_hash"] == draft.artifact_hash
    assert all(
        fixture.structural_check_passed is structural_state
        for fixture in session.query(models.TemplateDraftFixture)
        .filter_by(draft_id="draft-1", kind="positive").all()
    )

    with pytest.raises(ApprovalPreconditionError, match="too few verified real fixtures"):
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


def test_static_template_name_raises_name_conflict(engine, session):
    """A dynamic template published under a static enum name (e.g. 'number_line')
    would be silently shadowed by the static dispatch in classification.py.
    Approval must reject the collision so it cannot enter the DB."""
    from app.models.scene import TemplateName

    static_names = [member.value for member in TemplateName]
    assert static_names, "TemplateName enum is empty; test would trivially pass"
    for i, name in enumerate(static_names):
        draft_id = f"static-collision-{i}"
        _seed_draft(session, draft_id=draft_id, fingerprint_key=f"k-{i}")
        with pytest.raises(TemplateNameConflictError, match="reserved by a static template"):
            approve_draft_service(
                draft_id=draft_id, template_name=name, reviewer_label="dev",
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


# ------------------------------------------------- owner-scoped approval


def test_owner_approval_publishes_a_session_scoped_version(engine, session):
    _seed_draft(session, draft_id="draft-own", fingerprint_key="k-own", job_owner="session-a")

    version = approve_draft_service(
        draft_id="draft-own", template_name="apples_count",
        reviewer_label="teacher", math_semantics_confirmed=True,
        owner_session_id="session-a",
    )

    assert version.owner_session_id == "session-a"
    assert version.status == TEMPLATE_VERSION_ENABLED


def test_owner_approval_accepts_a_draft_built_from_one_real_example(engine, session):
    """A single-observation build is approvable by its owner.

    The floor is min(meta_required_fixture_count, examples the draft was built
    from) so a teacher who hit one novel problem is not held to evidence that
    cannot exist yet.
    """
    _seed_draft(
        session, draft_id="draft-one", fingerprint_key="k-one",
        positive_count=1, trigger_count=1, job_owner="session-a",
    )

    version = approve_draft_service(
        draft_id="draft-one", template_name="one_example",
        reviewer_label="teacher", math_semantics_confirmed=True,
        owner_session_id="session-a",
    )

    assert version.owner_session_id == "session-a"


def test_owner_approval_still_demands_a_fixture_per_example_built_from(engine, session):
    """Relaxed is not waived: five examples in, five verified fixtures needed."""
    _seed_draft(
        session, draft_id="draft-short", fingerprint_key="k-short",
        positive_count=3, trigger_count=5, job_owner="session-a",
    )

    with pytest.raises(ApprovalPreconditionError, match="too few verified real fixtures"):
        approve_draft_service(
            draft_id="draft-short", template_name="too_short",
            reviewer_label="teacher", math_semantics_confirmed=True,
            owner_session_id="session-a",
        )


def test_shared_approval_is_not_relaxed_by_a_small_build(engine, session):
    """Promotion to everyone always demands the full configured count."""
    _seed_draft(
        session, draft_id="draft-shared", fingerprint_key="k-shared",
        positive_count=1, trigger_count=1,
    )

    with pytest.raises(ApprovalPreconditionError, match="too few verified real fixtures"):
        approve_draft_service(
            draft_id="draft-shared", template_name="shared_one",
            reviewer_label="dev", math_semantics_confirmed=True,
            owner_session_id=None,
        )


def test_one_owners_approval_leaves_another_owners_version_enabled(engine, session):
    _seed_draft(session, draft_id="draft-a", fingerprint_key="k1", job_owner="session-a")
    _seed_draft(session, draft_id="draft-b", fingerprint_key="k1", job_owner="session-b")

    approve_draft_service(
        draft_id="draft-a", template_name="name_a", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-a",
    )
    approve_draft_service(
        draft_id="draft-b", template_name="name_b", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-b",
    )

    check = _fresh(engine)
    enabled = {
        version.owner_session_id
        for version in check.query(models.TemplateVersion)
        .filter_by(fingerprint_key="k1", status=TEMPLATE_VERSION_ENABLED)
        .all()
    }
    assert enabled == {"session-a", "session-b"}


def test_two_owners_may_choose_the_same_template_name(engine, session):
    _seed_draft(session, draft_id="draft-a", fingerprint_key="k-a", job_owner="session-a")
    _seed_draft(session, draft_id="draft-b", fingerprint_key="k-b", job_owner="session-b")

    approve_draft_service(
        draft_id="draft-a", template_name="pair_elimination", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-a",
    )
    approve_draft_service(
        draft_id="draft-b", template_name="pair_elimination", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-b",
    )

    check = _fresh(engine)
    assert check.query(models.TemplateVersion).filter_by(
        template_name="pair_elimination", status=TEMPLATE_VERSION_ENABLED
    ).count() == 2


def test_a_shared_name_still_blocks_another_shared_approval(engine, session):
    _seed_draft(session, draft_id="draft-a", fingerprint_key="k-a")
    _seed_draft(session, draft_id="draft-b", fingerprint_key="k-b")

    approve_draft_service(
        draft_id="draft-a", template_name="pair_elimination", reviewer_label="dev",
        math_semantics_confirmed=True, owner_session_id=None,
    )

    with pytest.raises(TemplateNameConflictError):
        approve_draft_service(
            draft_id="draft-b", template_name="pair_elimination", reviewer_label="dev",
            math_semantics_confirmed=True, owner_session_id=None,
        )


def test_owner_approval_does_not_disable_the_shared_version(engine, session):
    _seed_draft(session, draft_id="draft-shared", fingerprint_key="k1")
    _seed_draft(session, draft_id="draft-own", fingerprint_key="k1", job_owner="session-a")

    approve_draft_service(
        draft_id="draft-shared", template_name="shared_name", reviewer_label="dev",
        math_semantics_confirmed=True, owner_session_id=None,
    )
    approve_draft_service(
        draft_id="draft-own", template_name="own_name", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-a",
    )

    check = _fresh(engine)
    shared = check.query(models.TemplateVersion).filter_by(template_name="shared_name").one()
    assert shared.status == TEMPLATE_VERSION_ENABLED


def test_re_approving_for_one_owner_disables_that_owners_prior_version(engine, session):
    _seed_draft(session, draft_id="draft-1", fingerprint_key="k1", job_owner="session-a")
    _seed_draft(session, draft_id="draft-2", fingerprint_key="k1", job_owner="session-a")

    approve_draft_service(
        draft_id="draft-1", template_name="first", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-a",
    )
    approve_draft_service(
        draft_id="draft-2", template_name="second", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-a",
    )

    check = _fresh(engine)
    assert check.query(models.TemplateVersion).filter_by(template_name="first").one().status == (
        TEMPLATE_VERSION_DISABLED
    )
    assert check.query(models.TemplateVersion).filter_by(template_name="second").one().status == (
        TEMPLATE_VERSION_ENABLED
    )


# ------------------------------- names across the shared/private boundary
#
# The invariant: for any session S, {shared versions} union {S's private
# versions} must have unique template_names. Anything else puts two identical
# keys into one session's snapshot dict, where query order silently decides
# which template that name resolves to.


def test_a_private_approval_cannot_take_a_shared_name(engine, session):
    _seed_draft(session, draft_id="draft-shared", fingerprint_key="k-shared")
    _seed_draft(session, draft_id="draft-own", fingerprint_key="k-own", job_owner="session-a")

    approve_draft_service(
        draft_id="draft-shared", template_name="pair_elimination", reviewer_label="dev",
        math_semantics_confirmed=True, owner_session_id=None,
    )

    with pytest.raises(TemplateNameConflictError):
        approve_draft_service(
            draft_id="draft-own", template_name="pair_elimination",
            reviewer_label="teacher", math_semantics_confirmed=True,
            owner_session_id="session-a",
        )


def test_a_shared_approval_cannot_take_a_name_a_teacher_holds(engine, session):
    """The same collision from the other side.

    A shared version taking a name some session already holds privately would
    give that one session two templates under one name.
    """
    _seed_draft(session, draft_id="draft-own", fingerprint_key="k-own", job_owner="session-a")
    _seed_draft(session, draft_id="draft-shared", fingerprint_key="k-shared")

    approve_draft_service(
        draft_id="draft-own", template_name="pair_elimination", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-a",
    )

    with pytest.raises(TemplateNameConflictError):
        approve_draft_service(
            draft_id="draft-shared", template_name="pair_elimination",
            reviewer_label="dev", math_semantics_confirmed=True, owner_session_id=None,
        )


def test_two_teachers_may_still_share_a_name_with_each_other(engine, session):
    """Unchanged, and safe: neither can see the other, so no snapshot holds both."""
    _seed_draft(session, draft_id="draft-a", fingerprint_key="k-a", job_owner="session-a")
    _seed_draft(session, draft_id="draft-b", fingerprint_key="k-b", job_owner="session-b")

    approve_draft_service(
        draft_id="draft-a", template_name="pair_elimination", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-a",
    )
    approve_draft_service(
        draft_id="draft-b", template_name="pair_elimination", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-b",
    )

    check = _fresh(engine)
    assert check.query(models.TemplateVersion).filter_by(
        template_name="pair_elimination", status=TEMPLATE_VERSION_ENABLED
    ).count() == 2


def test_a_disabled_version_does_not_reserve_its_name(engine, session):
    """Only live versions can collide in a snapshot."""
    _seed_draft(session, draft_id="draft-shared", fingerprint_key="k-shared")
    _seed_draft(session, draft_id="draft-own", fingerprint_key="k-own", job_owner="session-a")

    approve_draft_service(
        draft_id="draft-shared", template_name="pair_elimination", reviewer_label="dev",
        math_semantics_confirmed=True, owner_session_id=None,
    )
    with _fresh(engine) as disabler:
        version = disabler.query(models.TemplateVersion).filter_by(
            template_name="pair_elimination"
        ).one()
        version.status = TEMPLATE_VERSION_DISABLED
        disabler.commit()

    version = approve_draft_service(
        draft_id="draft-own", template_name="pair_elimination", reviewer_label="teacher",
        math_semantics_confirmed=True, owner_session_id="session-a",
    )

    assert version.owner_session_id == "session-a"
