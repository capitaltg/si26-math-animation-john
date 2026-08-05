import hmac
import json
from datetime import datetime, timezone
from fractions import Fraction
from math import isfinite

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.config import get_settings
from app.meta.artifacts import artifact_path
from app.meta.db import meta_session
from app.meta.models import (
    DRAFT_PENDING_REVIEW,
    FallbackObservation,
    GenerationJob,
    TemplateDraft,
    TemplateDraftFixture,
)
from app.meta.approval import (
    ApprovalConflictError,
    ApprovalPreconditionError,
    DraftNotApprovableError,
    DraftNotFoundError,
    RevokedConflictError,
    TemplateNameConflictError,
    approve_draft_service,
)
from app.meta.promotion import (
    PromotionEvidenceError,
    PromotionNameConflictError,
    VersionNotFoundError,
    VersionNotPromotableError,
    enabled_versions,
    promote_version,
)
from app.meta.review_actions import (
    DraftNotRefinableError,
    DraftRefinementFailedError,
    reject_and_refine,
)
from app.meta.revalidation import (
    DraftNotRevalidatableError,
    RevalidationDraftNotFoundError,
    RevalidationFailedError,
    revalidate_draft as revalidate_draft_service,
)
from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import ExpressionNode, compile_expression
from app.meta.dsl.guard import GuardDocument
from app.meta.dsl.params import ParamsDocument
from app.meta.dsl.teaching_plan import TeachingPlanDocument
from app.meta.validation import compile_draft_documents

_FIXTURE_EDITABLE_STATUSES = {DRAFT_PENDING_REVIEW}

router = APIRouter(prefix="/meta")


def require_reviewer_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.meta_reviewer_token:
        raise HTTPException(status_code=401, detail="meta_reviewer_token is not configured")
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(token, settings.meta_reviewer_token):
        raise HTTPException(status_code=401, detail="Invalid bearer token")


class DraftSummaryOut(BaseModel):
    id: str
    fingerprint_key: str
    revision: int
    status: str
    created_at: datetime


class FixtureOut(BaseModel):
    id: str
    observation_id: str | None
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
    teaching_plan: dict
    timeline: list[dict]
    total_duration_seconds: float
    quality_report: dict | None
    classifier_bullet: str
    artifact_hash: str
    validation_report: dict | None
    preview_url: str | None
    fixtures: list[FixtureOut]
    required_fixture_count: int
    reviewer_feedback: str | None


class GenerationJobOut(BaseModel):
    id: str
    fingerprint_key: str
    status: str
    attempt: int
    error_summary: str | None


class RejectRequest(BaseModel):
    feedback: str
    reviewer_label: str = "dev-reviewer"


class RejectResponse(BaseModel):
    new_draft: DraftSummaryOut | None
    needs_manual_authoring: bool


class FixtureUpdateRequest(BaseModel):
    params: dict
    expected_result: dict


class ApproveRequest(BaseModel):
    template_name: str
    reviewer_label: str = "dev-reviewer"
    math_semantics_confirmed: bool


class ApproveResponse(BaseModel):
    template_version_id: str
    template_name: str
    status: str


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
        id=fixture.id, observation_id=fixture.observation_id,
        kind=fixture.kind, expected_outcome=fixture.expected_outcome,
        generation_method=fixture.generation_method, params=json.loads(fixture.params_json),
        expected_result=json.loads(fixture.expected_result_json) if fixture.expected_result_json else None,
        structural_check_passed=fixture.structural_check_passed,
        structural_check_detail=fixture.structural_check_detail,
        source_excerpt=source_excerpt,
    )


def _draft_detail(session, draft: TemplateDraft) -> DraftDetailOut:
    fixtures = session.query(TemplateDraftFixture).filter_by(draft_id=draft.id).all()
    preview_url = f"/meta/preview/{draft.preview_artifact_hash}" if draft.preview_artifact_hash else None
    # scene_program_json is nullable at the DB level (a draft can, in
    # principle, exist before a scene program is compiled for it), so this
    # falls back to an empty timeline and a 0-second duration rather than
    # crashing detail serialization -- consistent with "nothing compiled yet"
    # rather than fabricating a fake duration.
    scene_program = json.loads(draft.scene_program_json) if draft.scene_program_json else {}
    timeline = scene_program.get("timeline", [])
    total_duration_seconds = scene_program.get("total_duration_seconds", 0.0)
    return DraftDetailOut(
        id=draft.id, fingerprint_key=draft.fingerprint_key, revision=draft.revision,
        status=draft.status, params_document=json.loads(draft.params_document_json),
        guard_document=json.loads(draft.guard_document_json),
        answer_expression=json.loads(draft.answer_expression_json),
        teaching_plan=json.loads(draft.teaching_plan_json),
        timeline=timeline,
        total_duration_seconds=total_duration_seconds,
        quality_report=json.loads(draft.quality_report_json) if draft.quality_report_json else None,
        classifier_bullet=draft.classifier_bullet, artifact_hash=draft.artifact_hash,
        validation_report=json.loads(draft.validation_report_json) if draft.validation_report_json else None,
        preview_url=preview_url,
        fixtures=[_fixture_out(session, fixture) for fixture in fixtures],
        required_fixture_count=get_settings().meta_required_fixture_count,
        reviewer_feedback=draft.reviewer_feedback,
    )


def _generation_job_out(job: GenerationJob) -> GenerationJobOut:
    return GenerationJobOut(
        id=job.id,
        fingerprint_key=job.fingerprint_key,
        status=job.status,
        attempt=job.attempt,
        error_summary=job.error_summary,
    )


@router.get(
    "/drafts", response_model=list[DraftSummaryOut], dependencies=[Depends(require_reviewer_token)]
)
def list_drafts():
    # Invalid, failed, or already-decided candidates must never leak into the
    # reviewer's list -- this always returns pending_review drafts only,
    # regardless of any `status` a caller might pass in the query string.
    with meta_session() as session:
        rows = (
            session.query(TemplateDraft)
            .filter(TemplateDraft.status == DRAFT_PENDING_REVIEW)
            .order_by(TemplateDraft.created_at.desc())
            .all()
        )
        return [_draft_summary(row) for row in rows]


@router.get(
    "/drafts/{draft_id}", response_model=DraftDetailOut, dependencies=[Depends(require_reviewer_token)]
)
def get_draft(draft_id: str):
    # A draft ID is proof the candidate is already approvable, subject only to
    # explicit human math confirmation. Once a draft leaves pending_review
    # (approved, rejected, superseded, or never reached review), direct access
    # 404s exactly like an unknown draft -- no endpoint in this API reads a
    # decided draft by id, so there is no carve-out to make here.
    with meta_session() as session:
        draft = session.get(TemplateDraft, draft_id)
        if draft is None or draft.status != DRAFT_PENDING_REVIEW:
            raise HTTPException(status_code=404, detail=f"Unknown draft {draft_id}")
        return _draft_detail(session, draft)


@router.get(
    "/jobs/{job_id}", response_model=GenerationJobOut, dependencies=[Depends(require_reviewer_token)]
)
def get_generation_job(job_id: str):
    with meta_session() as session:
        job = session.get(GenerationJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown generation job {job_id}")
        return _generation_job_out(job)


@router.get("/preview/{artifact_hash}", dependencies=[Depends(require_reviewer_token)])
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


@router.post(
    "/drafts/{draft_id}/fixtures/{fixture_id}",
    response_model=FixtureOut,
    dependencies=[Depends(require_reviewer_token)],
)
def update_fixture(draft_id: str, fixture_id: str, request: FixtureUpdateRequest):
    with meta_session() as session:
        fixture = session.get(TemplateDraftFixture, fixture_id)
        if fixture is None or fixture.draft_id != draft_id:
            raise HTTPException(status_code=404, detail=f"Unknown fixture {fixture_id}")
        draft = session.get(TemplateDraft, draft_id)
        if draft is None or draft.status not in _FIXTURE_EDITABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Draft {draft_id} fixtures are not editable in status "
                f"{draft.status if draft else 'unknown'}",
            )
        params_document = ParamsDocument.model_validate(json.loads(draft.params_document_json))
        guard_document = GuardDocument.model_validate(json.loads(draft.guard_document_json))
        answer_expression = TypeAdapter(ExpressionNode).validate_python(
            json.loads(draft.answer_expression_json)
        )
        teaching_plan_document = TeachingPlanDocument.model_validate(
            json.loads(draft.teaching_plan_json)
        )
        compiled = compile_draft_documents(
            params_document,
            guard_document,
            answer_expression,
            teaching_plan_document,
        )
        try:
            params = compiled.params_cls.model_validate(request.params)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Fixture params are invalid") from exc

        try:
            computed_answer = compile_expression(
                answer_expression, compiled.field_contract
            ).evaluate(params.model_dump())
        except DslValidationError as exc:
            raise HTTPException(
                status_code=422, detail="Fixture params cannot be evaluated"
            ) from exc
        if _requested_answer(request.expected_result) != computed_answer:
            raise HTTPException(
                status_code=422, detail="Expected result does not match answer expression"
            )

        # Only an actual change to the fixture's params stales the render
        # evidence. Supplying the human-verified answer for UNCHANGED params
        # is a confirmation, not a new candidate -- it must not destroy the
        # `structural_check_passed` / validation / quality / preview evidence
        # that approval precondition 8 requires, or no production path could
        # ever both confirm an answer and stay approvable. Compare parsed
        # values (not the raw JSON string) so key order or numeric formatting
        # differences can never masquerade as a real change.
        if request.params != json.loads(fixture.params_json):
            fixture.structural_check_passed = None
            fixture.structural_check_detail = None
            draft.validation_report_json = None
            draft.quality_report_json = None
            draft.preview_artifact_hash = None
        fixture.params_json = json.dumps(request.params)
        fixture.expected_result_json = json.dumps({"answer": str(computed_answer)})
        draft.updated_at = datetime.now(timezone.utc)
        session.flush()

        return _fixture_out(session, fixture)


@router.post(
    "/drafts/{draft_id}/revalidate",
    response_model=DraftDetailOut,
    dependencies=[Depends(require_reviewer_token)],
)
def revalidate_draft(draft_id: str):
    """Rebuild the approval evidence a fixture edit cleared (issue #63).

    Returns the whole refreshed draft rather than just the reports, so the
    review panel can render the restored preview and fixture checks without a
    second round trip.
    """
    try:
        revalidate_draft_service(draft_id)
    except RevalidationDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftNotRevalidatableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RevalidationFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with meta_session() as session:
        draft = session.get(TemplateDraft, draft_id)
        if draft is None or draft.status != DRAFT_PENDING_REVIEW:
            raise HTTPException(status_code=404, detail=f"Unknown draft {draft_id}")
        return _draft_detail(session, draft)


@router.post(
    "/drafts/{draft_id}/reject", response_model=RejectResponse, dependencies=[Depends(require_reviewer_token)]
)
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


class TemplateVersionOut(BaseModel):
    id: str
    template_name: str
    fingerprint_key: str
    owner_session_id: str | None
    created_at: datetime


@router.get(
    "/versions",
    response_model=list[TemplateVersionOut],
    dependencies=[Depends(require_reviewer_token)],
)
def list_versions():
    """The live template library, showing which versions are private to a session."""
    return [TemplateVersionOut(**row) for row in enabled_versions()]


@router.post(
    "/versions/{version_id}/promote",
    response_model=TemplateVersionOut,
    dependencies=[Depends(require_reviewer_token)],
)
def promote(version_id: str):
    """Share one teacher's template with everyone.

    Re-checks the full fixture floor: a session-scoped approval is allowed a
    relaxed one, and that allowance must not travel with the template.
    """
    try:
        version = promote_version(version_id)
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PromotionEvidenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (VersionNotPromotableError, PromotionNameConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return TemplateVersionOut(
        id=version.id,
        template_name=version.template_name,
        fingerprint_key=version.fingerprint_key,
        owner_session_id=version.owner_session_id,
        created_at=version.created_at,
    )


@router.post(
    "/drafts/{draft_id}/approve", response_model=ApproveResponse, dependencies=[Depends(require_reviewer_token)]
)
def approve_draft(draft_id: str, request: ApproveRequest):
    settings = get_settings()
    if not settings.meta_approval_enabled:
        raise HTTPException(status_code=409, detail="Approval is disabled in this environment")

    try:
        version = approve_draft_service(
            draft_id=draft_id,
            template_name=request.template_name,
            reviewer_label=request.reviewer_label,
            math_semantics_confirmed=request.math_semantics_confirmed,
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftNotApprovableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalPreconditionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RevokedConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TemplateNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ApproveResponse(
        template_version_id=version.id,
        template_name=version.template_name,
        status=version.status,
    )
