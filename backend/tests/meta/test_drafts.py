import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.meta import db, models
from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.expression import LiteralNode
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument
from app.meta.draft_generation import DraftProposal, ProposedFixture
from app.meta.drafts import create_generated_draft, load_draft_documents, record_review, supersede_and_refine


@pytest.fixture
def session(tmp_path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    db.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _now():
    return datetime(2026, 7, 28, tzinfo=timezone.utc)


def _job(session):
    job = models.GenerationJob(
        id="job-1", fingerprint_key="k1", fingerprint_version=1, fingerprint_json="{}",
        trigger_observation_ids="[]", status=models.JOB_RUNNING, created_at=_now(), updated_at=_now(),
    )
    session.add(job)
    session.flush()
    return job


def _proposal():
    return DraftProposal(
        params_document=ParamsDocument(
            params_version=1,
            fields=[IntegerFieldSpec(name="n", label="N", description="", minimum=1, maximum=10)],
        ),
        guard_document=GuardDocument(
            guard_version=1,
            predicates=[PositivePredicate(value=LiteralNode(value=1))],
        ),
        answer_expression=LiteralNode(value=1),
        animation_document=AnimationDocument(root={"kind": "label", "text": "x"}),
        classifier_bullet="use for X",
        fixtures=[
            ProposedFixture(kind="positive", expected_outcome="accept", params={"n": 5}),
            ProposedFixture(kind="negative", expected_outcome="reject", params={"n": 0}),
        ],
    )


def test_create_generated_draft_persists_documents_and_fixtures(session):
    job = _job(session)
    draft = create_generated_draft(
        session, new_id="draft-1", job=job, proposal=_proposal(), now=_now(),
        fixture_ids=["fx-1", "fx-2"],
    )
    assert draft.status == models.DRAFT_GENERATED
    assert draft.revision == 1
    assert draft.parent_draft_id is None
    assert draft.job_id == "job-1"
    assert draft.artifact_hash.startswith("sha256:")
    assert json.loads(draft.params_document_json)["fields"][0]["name"] == "n"

    fixtures = session.query(models.TemplateDraftFixture).filter_by(draft_id=draft.id).all()
    assert {f.id for f in fixtures} == {"fx-1", "fx-2"}
    assert {f.kind for f in fixtures} == {"positive", "negative"}


def test_create_generated_draft_is_deterministic_hash_for_same_proposal(session):
    job = _job(session)
    draft_a = create_generated_draft(
        session, new_id="draft-a", job=job, proposal=_proposal(), now=_now(), fixture_ids=["a1", "a2"]
    )
    draft_b = create_generated_draft(
        session, new_id="draft-b", job=job, proposal=_proposal(), now=_now(), fixture_ids=["b1", "b2"]
    )
    assert draft_a.artifact_hash == draft_b.artifact_hash


def test_supersede_and_refine_marks_old_draft_superseded_and_bumps_revision(session):
    job = _job(session)
    original = create_generated_draft(
        session, new_id="draft-1", job=job, proposal=_proposal(), now=_now(), fixture_ids=["fx-1", "fx-2"]
    )
    refined = supersede_and_refine(
        session, draft=original, proposal=_proposal(), new_id="draft-2", now=_now(),
        fixture_ids=["fx-3", "fx-4"],
    )
    session.flush()
    assert original.status == models.DRAFT_SUPERSEDED
    assert refined.revision == 2
    assert refined.parent_draft_id == "draft-1"
    assert refined.job_id == "draft-1" and False or refined.job_id == job.id


def test_record_review_appends_row(session):
    job = _job(session)
    draft = create_generated_draft(
        session, new_id="draft-1", job=job, proposal=_proposal(), now=_now(), fixture_ids=["fx-1", "fx-2"]
    )
    review = record_review(
        session, new_id="review-1", draft_id=draft.id, decision="reject",
        reviewer_label="dev", feedback="too loose", now=_now(),
    )
    assert review.decision == "reject"
    assert session.query(models.TemplateReview).count() == 1


def test_load_draft_documents_round_trips_proposal_shape(session):
    job = _job(session)
    proposal = _proposal()
    draft = create_generated_draft(
        session, new_id="draft-1", job=job, proposal=proposal, now=_now(), fixture_ids=["fx-1", "fx-2"]
    )
    loaded = load_draft_documents(draft)
    assert loaded.params_document.fields[0].name == "n"
    assert loaded.classifier_bullet == "use for X"
    assert loaded.fixtures == []
