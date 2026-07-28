import json
from datetime import datetime
from fractions import Fraction
from math import isfinite

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.config import get_settings
from app.meta.artifacts import artifact_path
from app.meta.db import meta_session
from app.meta.models import FallbackObservation, TemplateDraft, TemplateDraftFixture
from app.meta.review_actions import (
    DraftNotRefinableError,
    DraftRefinementFailedError,
    reject_and_refine,
)
from app.meta.dsl.animation import AnimationDocument
from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import ExpressionNode, compile_expression
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.validation import compile_draft_documents

router = APIRouter(prefix="/meta")


class DraftSummaryOut(BaseModel):
    id: str
    fingerprint_key: str
    revision: int
    status: str
    created_at: datetime


class FixtureOut(BaseModel):
    id: str
    kind: str
    expected_outcome: str
    generation_method: str
    params: dict
    expected_result: dict | None
    structural_check_passed: bool | None
    structural_check_detail: str | None
    source_excerpt: str | None


class DraftDetailOut(BaseModel):
    id: str
    fingerprint_key: str
    revision: int
    status: str
    params_document: dict
    guard_document: dict
    answer_expression: dict
    animation_document: dict
    classifier_bullet: str
    artifact_hash: str
    validation_report: dict | None
    preview_url: str | None
    fixtures: list[FixtureOut]
    reviewer_feedback: str | None


class RejectRequest(BaseModel):
    feedback: str
    reviewer_label: str = "dev-reviewer"


class RejectResponse(BaseModel):
    new_draft: DraftSummaryOut | None
    needs_manual_authoring: bool


class FixtureUpdateRequest(BaseModel):
    params: dict
    expected_result: dict


def _draft_summary(draft: TemplateDraft) -> DraftSummaryOut:
    return DraftSummaryOut(
        id=draft.id, fingerprint_key=draft.fingerprint_key,
        revision=draft.revision, status=draft.status, created_at=draft.created_at,
    )


def _fixture_out(session, fixture: TemplateDraftFixture) -> FixtureOut:
    source_excerpt = None
    if fixture.observation_id:
        observation = session.get(FallbackObservation, fixture.observation_id)
        source_excerpt = observation.source_excerpt if observation else None
    return FixtureOut(
        id=fixture.id, kind=fixture.kind, expected_outcome=fixture.expected_outcome,
        generation_method=fixture.generation_method, params=json.loads(fixture.params_json),
        expected_result=json.loads(fixture.expected_result_json) if fixture.expected_result_json else None,
        structural_check_passed=fixture.structural_check_passed,
        structural_check_detail=fixture.structural_check_detail,
        source_excerpt=source_excerpt,
    )


def _draft_detail(session, draft: TemplateDraft) -> DraftDetailOut:
    fixtures = session.query(TemplateDraftFixture).filter_by(draft_id=draft.id).all()
    preview_url = f"/meta/preview/{draft.preview_artifact_hash}" if draft.preview_artifact_hash else None
    return DraftDetailOut(
        id=draft.id, fingerprint_key=draft.fingerprint_key, revision=draft.revision,
        status=draft.status, params_document=json.loads(draft.params_document_json),
        guard_document=json.loads(draft.guard_document_json),
        answer_expression=json.loads(draft.answer_expression_json),
        animation_document=json.loads(draft.animation_document_json),
        classifier_bullet=draft.classifier_bullet, artifact_hash=draft.artifact_hash,
        validation_report=json.loads(draft.validation_report_json) if draft.validation_report_json else None,
        preview_url=preview_url,
        fixtures=[_fixture_out(session, fixture) for fixture in fixtures],
        reviewer_feedback=draft.reviewer_feedback,
    )


@router.get("/drafts", response_model=list[DraftSummaryOut])
def list_drafts(status: str | None = None):
    with meta_session() as session:
        query = session.query(TemplateDraft)
        if status is not None:
            query = query.filter(TemplateDraft.status == status)
        rows = query.order_by(TemplateDraft.created_at.desc()).all()
        return [_draft_summary(row) for row in rows]


@router.get("/drafts/{draft_id}", response_model=DraftDetailOut)
def get_draft(draft_id: str):
    with meta_session() as session:
        draft = session.get(TemplateDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Unknown draft {draft_id}")
        return _draft_detail(session, draft)


@router.get("/preview/{artifact_hash}")
def get_preview(artifact_hash: str):
    path = artifact_path(get_settings().meta_artifact_root, artifact_hash)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Preview artifact not found")
    return FileResponse(path, media_type="image/png", filename=f"{artifact_hash}.png")


def _requested_answer(expected_result: dict) -> Fraction:
    value = expected_result.get("answer")
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise HTTPException(status_code=422, detail="Expected result answer must be a finite number")
    if isinstance(value, float) and not isfinite(value):
        raise HTTPException(status_code=422, detail="Expected result answer must be a finite number")
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise HTTPException(status_code=422, detail="Expected result answer must be a finite number") from exc


@router.post("/drafts/{draft_id}/fixtures/{fixture_id}", response_model=FixtureOut)
def update_fixture(draft_id: str, fixture_id: str, request: FixtureUpdateRequest):
    with meta_session() as session:
        fixture = session.get(TemplateDraftFixture, fixture_id)
        if fixture is None or fixture.draft_id != draft_id:
            raise HTTPException(status_code=404, detail=f"Unknown fixture {fixture_id}")
        draft = session.get(TemplateDraft, draft_id)
        params_document = ParamsDocument.model_validate(json.loads(draft.params_document_json))
        guard_document = GuardDocument.model_validate(json.loads(draft.guard_document_json))
        answer_expression = TypeAdapter(ExpressionNode).validate_python(
            json.loads(draft.answer_expression_json)
        )
        animation_document = AnimationDocument.model_validate(json.loads(draft.animation_document_json))
        compiled = compile_draft_documents(
            params_document,
            guard_document,
            answer_expression,
            animation_document,
        )
        try:
            params = compiled.params_cls.model_validate(request.params)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Fixture params are invalid") from exc

        try:
            computed_answer = compile_expression(
                answer_expression, compiled.known_fields
            ).evaluate(params.model_dump())
        except DslValidationError as exc:
            raise HTTPException(
                status_code=422, detail="Fixture params cannot be evaluated"
            ) from exc
        if _requested_answer(request.expected_result) != computed_answer:
            raise HTTPException(
                status_code=422, detail="Expected result does not match answer expression"
            )

        fixture.params_json = json.dumps(request.params)
        fixture.expected_result_json = json.dumps({"answer": str(computed_answer)})
        session.flush()
        return _fixture_out(session, fixture)


@router.post("/drafts/{draft_id}/reject", response_model=RejectResponse)
def reject_draft(draft_id: str, request: RejectRequest):
    settings = get_settings()
    try:
        new_draft = reject_and_refine(
            draft_id, feedback=request.feedback, reviewer_label=request.reviewer_label,
            max_refinements=settings.meta_draft_max_refinements,
        )
    except DraftNotRefinableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DraftRefinementFailedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if new_draft is None:
        return RejectResponse(new_draft=None, needs_manual_authoring=True)
    return RejectResponse(new_draft=_draft_summary(new_draft), needs_manual_authoring=False)


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: str):
    raise HTTPException(
        status_code=409,
        detail="Approval is disabled in this phase; it is enabled once the publication-gate tests pass (Phase 5)",
    )
