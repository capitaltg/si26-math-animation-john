import json
from datetime import datetime, timezone

import pytest

from app.config import get_settings
from app.meta import db, jobs, models
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.dsl.expression import AddNode, FieldRefNode, MultiplyNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.dsl.v3_common import CompileContext
from app.meta.fingerprint import Fingerprint
from app.meta.validation import FixtureCheckResult
from app.meta.validation_pipeline import ValidatedCandidate
from app.meta.v3.compiler import compile_teaching_plan
from app.meta.v3.errors import V3Failure, V3ValidationError


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    monkeypatch.setenv("META_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("META_TEMPLATES_ENABLED", "1")
    monkeypatch.setenv("META_CODEGEN_ENABLED", "1")
    get_settings.cache_clear()
    yield engine
    get_settings.cache_clear()


def _now():
    return datetime(2026, 7, 30, tzinfo=timezone.utc)


def _fingerprint():
    return Fingerprint(
        fingerprint_version=1,
        operation_family="measure",
        representation_family="shape",
        number_domain="whole",
        operand_arity=2,
        step_count=2,
        grade_band="6-8",
    )


def _seed_job_and_observation():
    with db.meta_session() as session:
        observation = models.FallbackObservation(
            id="obs-1", candidate_id="candidate-1",
            source_excerpt="The rectangle is 8 cm long and 3 cm wide.",
            grade_level=6, observation_kind="unsupported_shape", excluded=False, created_at=_now(),
        )
        session.add(observation)
        session.flush()
        jobs.evaluate_and_enqueue(
            session,
            fingerprint_key="k1",
            fingerprint_version=1,
            fingerprint_json=_fingerprint().model_dump_json(),
            trigger_observation_ids=[observation.id],
            threshold=0,
            new_id="job-1",
            now=_now(),
        )


def _proposal():
    plan = TeachingPlanDocument.model_validate({
        "plan_version": 3,
        "learning_objective": "Find a rectangle perimeter by tracing its boundary.",
        "primary_visual": {
            "kind": "rectangle_measurement", "ref": "rectangle",
            "length": {"node": "field_ref", "field": "length"},
            "width": {"node": "field_ref", "field": "width"}, "unit": "cm",
        },
        "strategy": "boundary_trace",
        "beats": [
            {"id": "reveal", "kind": "reveal", "targets": [{"visual_ref": "rectangle"}], "intent": "show the rectangle"},
            {"id": "trace", "kind": "derive", "targets": [{"visual_ref": "rectangle"}], "intent": "trace every edge"},
            {"id": "conclude", "kind": "conclude", "targets": [{"visual_ref": "rectangle"}], "intent": "state the perimeter"},
        ],
        "variation_seed": "generation-pipeline",
    })
    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[
                IntegerFieldSpec(name="length", label="Length", description="", minimum=-100, maximum=100),
                IntegerFieldSpec(name="width", label="Width", description="", minimum=-100, maximum=100),
            ],
        ),
        guard_document=GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=FieldRefNode(field="length"))],
        ),
        answer_expression=AddNode(operands=[
            MultiplyNode(operands=[FieldRefNode(field="length"), FieldRefNode(field="length")]),
            MultiplyNode(operands=[FieldRefNode(field="width"), FieldRefNode(field="width")]),
        ]),
        teaching_plan_document=plan,
        classifier_bullet="Use for rectangle perimeter lessons.",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", observation_id="obs-1", params={"length": 8, "width": 3}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"length": -1, "width": 3}),
        ],
    )


def _candidate(proposal):
    scene_program = compile_teaching_plan(
        proposal.teaching_plan_document,
        proposal.answer_expression,
        frozenset({"length", "width"}),
        CompileContext(concept_family="measure_shape", grade_band="6-8"),
    )
    return ValidatedCandidate(
        proposal=proposal,
        scene_program=scene_program,
        validation_report={
            "passed": True,
            "fixture_results": [],
            "preview_ok": True,
            "preview_artifact_hash": "sha256:preview",
            "compiler_version": 3,
            "renderer_version": 3,
            "negative_predicate_coverage": [0],
            # See test_drafts.py: `build_validation_report` always includes
            # `known_fields` and `artifact_hash`; approval precondition 4
            # cross-checks the latter against the draft's stored hash.
            "known_fields": ["length", "width"],
            "artifact_hash": "sha256:candidate",
        },
        quality_report={"passed": True, "checks": [], "artifact_hash": "sha256:candidate"},
        preview_artifact_hash="sha256:preview",
        fixture_results=[
            FixtureCheckResult("fixture-0", True, "accepted"),
            FixtureCheckResult("fixture-1", True, "rejected", frozenset({0})),
        ],
    )


def test_generate_and_validate_revision_retries_structured_candidate_failure(monkeypatch, engine):
    from app.meta.generation_pipeline import generate_and_validate_revision

    proposal = _proposal()
    attempts = []

    monkeypatch.setattr("app.meta.generation_pipeline.propose_template_draft", lambda *args, **kwargs: proposal)

    def validate(*args, **kwargs):
        attempts.append(kwargs["compile_context"])
        if len(attempts) == 1:
            raise V3ValidationError(V3Failure(
                code="serial_simple_reveal",
                path="timeline",
                expected="together",
                observed="stagger",
                hint="reveal values together",
            ))
        return _candidate(proposal)

    monkeypatch.setattr("app.meta.generation_pipeline.validate_candidate", validate)
    _seed_job_and_observation()
    with db.meta_session() as session:
        job = session.get(models.GenerationJob, "job-1")
        job.status = models.JOB_RUNNING
        observations = [session.get(models.FallbackObservation, "obs-1")]

    draft = generate_and_validate_revision(job=job, fingerprint=_fingerprint(), observations=observations)

    assert draft.status == models.DRAFT_PENDING_REVIEW
    assert len(attempts) == 2
    assert attempts[-1] == CompileContext(concept_family="measure_shape", grade_band="6-8")


def test_run_generation_job_marks_retry_exhaustion_manual_with_public_code(monkeypatch, engine):
    from app.meta.generation_pipeline import run_generation_job
    from fastapi.testclient import TestClient

    _seed_job_and_observation()
    # Seed leak-prone text into every V3Failure field. If run_generation_job
    # (or the routes serving job/draft state) ever forwarded any part of the
    # failure onto the reviewer surface, one of these substrings would appear
    # in the response bodies below. Modelled on test_draft_generation.py's
    # reviewer-feedback pattern.
    _LEAK_MARKERS = (
        'File "/app/meta/generation_pipeline.py"',
        "Traceback (most recent call last)",
        "secret internals",
    )
    failure = V3Failure(
        code="serial_simple_reveal",
        path='timeline (File "/app/meta/generation_pipeline.py", line 42)',
        expected="together (secret internals)",
        observed="stagger\nTraceback (most recent call last):\n  raise V3ValidationError(...)",
        hint="reveal values together",
    )
    from app.meta.generation_pipeline import CandidateGenerationExhausted

    monkeypatch.setattr(
        "app.meta.generation_pipeline.generate_and_validate_revision",
        lambda **kwargs: (_ for _ in ()).throw(CandidateGenerationExhausted(failure)),
    )

    assert run_generation_job(owner="worker-1") is None

    monkeypatch.setenv("META_REVIEWER_TOKEN", "test-token")
    get_settings.cache_clear()
    with db.meta_session() as session:
        session.add(models.TemplateDraft(
            id="draft-review",
            job_id="job-1",
            fingerprint_key="k1",
            fingerprint_version=1,
            fingerprint_json=_fingerprint().model_dump_json(),
            revision=1,
            params_document_json="{}",
            guard_document_json="{}",
            answer_expression_json="{}",
            teaching_plan_json='{"plan_version": 3}',
            scene_program_json='{"scene_version": 3}',
            quality_report_json='{"passed": true}',
            classifier_bullet="Use for review payload coverage.",
            dsl_schema_versions_json="{}",
            artifact_hash="sha256:review",
            status=models.DRAFT_PENDING_REVIEW,
            validation_report_json='{"passed": true}',
            created_at=_now(),
            updated_at=_now(),
        ))
    from app.main import create_app
    client = TestClient(create_app(), headers={"Authorization": "Bearer test-token"})

    job_response = client.get("/meta/jobs/job-1")
    draft_response = client.get("/meta/drafts/draft-review")

    assert job_response.status_code == 200
    assert draft_response.status_code == 200
    assert job_response.json()["status"] == models.JOB_NEEDS_MANUAL
    assert job_response.json()["error_summary"] == "automatic_generation_needs_manual_authoring"
    assert draft_response.json()["teaching_plan"] == {"plan_version": 3}
    for payload in (job_response.json(), draft_response.json()):
        reviewer_visible = json.dumps(payload)
        assert "meta-template generation exhausted automatic validation retries" not in reviewer_visible
        # The failure above deliberately embeds substrings that ONLY reach the
        # reviewer surface if some part of `V3Failure` leaks. Vacuous
        # `"traceback"`-not-in checks would pass even when nothing was seeded;
        # this fails the day any of `V3Failure.path/expected/observed` is
        # forwarded onto the wire.
        for marker in _LEAK_MARKERS:
            assert marker not in reviewer_visible, (
                f"{marker!r} leaked into the reviewer-visible payload"
            )


def _running_job_and_observations():
    _seed_job_and_observation()
    with db.meta_session() as session:
        job = session.get(models.GenerationJob, "job-1")
        job.status = models.JOB_RUNNING
        return job, [session.get(models.FallbackObservation, "obs-1")]


def _schema_violation():
    """Raise the same pydantic error the tool call raises on an off-schema draft."""
    raw = _proposal().model_dump()
    raw["teaching_plan_document"]["beats"][0]["intent"] = ""
    DraftProposal.model_validate(raw)


def test_generate_and_validate_revision_retries_off_schema_proposal_with_feedback(monkeypatch, engine):
    from app.meta.generation_pipeline import generate_and_validate_revision

    proposal = _proposal()
    calls = []

    def propose(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            _schema_violation()
        return proposal

    monkeypatch.setattr("app.meta.generation_pipeline.propose_template_draft", propose)
    monkeypatch.setattr("app.meta.generation_pipeline.validate_candidate", lambda *a, **k: _candidate(proposal))
    job, observations = _running_job_and_observations()

    draft = generate_and_validate_revision(job=job, fingerprint=_fingerprint(), observations=observations)

    assert draft.status == models.DRAFT_PENDING_REVIEW
    assert len(calls) == 2
    feedback = calls[-1]["reviewer_feedback"]
    assert feedback["code"] == "draft_schema_invalid"
    assert feedback["path"].startswith("teaching_plan_document")
    assert feedback["hint"]
    assert calls[-1]["prior_proposal"] is None


def test_run_generation_job_marks_persistent_schema_failure_manual_not_generic_error(monkeypatch, engine):
    from app.meta.generation_pipeline import run_generation_job

    monkeypatch.setattr(
        "app.meta.generation_pipeline.propose_template_draft",
        lambda *a, **k: _schema_violation(),
    )
    _seed_job_and_observation()

    assert run_generation_job(owner="worker-1") is None

    with db.meta_session() as session:
        job = session.get(models.GenerationJob, "job-1")
        assert job.status == models.JOB_NEEDS_MANUAL
        assert job.error_summary == "automatic_generation_needs_manual_authoring"


def test_run_generation_job_returns_none_when_nothing_queued(engine):
    from app.meta.generation_pipeline import run_generation_job

    assert run_generation_job(owner="worker-1") is None


def _seed_rejected_draft(*, draft_id="draft-1", revision=1, feedback="the rows aren't labelled"):
    """A rejected draft on job-1, as requeue_for_refinement leaves it."""
    proposal = _proposal()
    with db.meta_session() as session:
        session.add(models.TemplateDraft(
            id=draft_id, job_id="job-1", fingerprint_key="k1", fingerprint_version=1,
            fingerprint_json=_fingerprint().model_dump_json(), revision=revision,
            params_document_json=proposal.params_document.model_dump_json(),
            guard_document_json=proposal.guard_document.model_dump_json(),
            answer_expression_json=proposal.answer_expression.model_dump_json(),
            teaching_plan_json=proposal.teaching_plan_document.model_dump_json(),
            scene_program_json="{}", quality_report_json='{"passed": true}',
            classifier_bullet=proposal.classifier_bullet, dsl_schema_versions_json="{}",
            artifact_hash=f"sha256:{draft_id}", status=models.DRAFT_REJECTED,
            reviewer_feedback=feedback, created_at=_now(), updated_at=_now(),
        ))


def test_run_generation_job_continues_a_rejected_draft_as_the_next_revision(monkeypatch, engine):
    """The worker is what makes a teacher's "try again" asynchronous.

    requeue_for_refinement stores nothing but the rejected draft and a queued
    job, so the worker has to recognise the refinement from the revision chain.
    """
    from app.meta.generation_pipeline import run_generation_job

    _seed_job_and_observation()
    _seed_rejected_draft()
    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        with db.meta_session() as session:
            child = models.TemplateDraft(
                id="draft-2", job_id="job-1", fingerprint_key="k1", fingerprint_version=1,
                fingerprint_json="{}", revision=kwargs["revision"],
                parent_draft_id=kwargs["parent_draft_id"],
                params_document_json="{}", guard_document_json="{}",
                answer_expression_json="{}", teaching_plan_json="{}", scene_program_json="{}",
                quality_report_json='{"passed": true}', classifier_bullet="x",
                dsl_schema_versions_json="{}", artifact_hash="sha256:draft-2",
                status=models.DRAFT_PENDING_REVIEW, validation_report_json='{"passed": true}',
                created_at=_now(), updated_at=_now(),
            )
            session.add(child)
            session.flush()
            return child

    monkeypatch.setattr("app.meta.generation_pipeline.generate_and_validate_revision", generate)

    draft = run_generation_job(owner="worker-1")

    assert draft.revision == 2
    assert draft.parent_draft_id == "draft-1"
    assert captured["reviewer_feedback"] == "the rows aren't labelled"
    assert captured["prior_proposal"] is not None
    assert captured["prior_proposal"].classifier_bullet == "Use for rectangle perimeter lessons."


def test_run_generation_job_continues_from_the_latest_rejection(monkeypatch, engine):
    from app.meta.generation_pipeline import run_generation_job

    _seed_job_and_observation()
    _seed_rejected_draft(draft_id="draft-1", revision=1, feedback="first complaint")
    _seed_rejected_draft(draft_id="draft-2", revision=2, feedback="second complaint")
    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("app.meta.generation_pipeline.generate_and_validate_revision", generate)

    run_generation_job(owner="worker-1")

    assert captured["revision"] == 3
    assert captured["parent_draft_id"] == "draft-2"
    assert captured["reviewer_feedback"] == "second complaint"


def test_run_generation_job_starts_at_revision_one_without_a_rejection(monkeypatch, engine):
    from app.meta.generation_pipeline import run_generation_job

    _seed_job_and_observation()
    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("app.meta.generation_pipeline.generate_and_validate_revision", generate)

    run_generation_job(owner="worker-1")

    assert captured["revision"] == 1
    assert captured["parent_draft_id"] is None
    assert captured["reviewer_feedback"] is None
    assert captured["prior_proposal"] is None
