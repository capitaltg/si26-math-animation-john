"""The teacher's half of the meta-template loop.

A teacher who picks the labelled text card for a problem no built-in template
fits can ask for one to be built, watch it being built, judge it, reject it with
a reason, and approve it for their own session. None of that requires the
reviewer bearer token every route in ``review_api`` depends on -- the ordinary
session cookie is the authorization here, and ownership is what separates one
session's draft from another's.

Kept apart from ``review_api`` deliberately. That module is the admin surface and
speaks in fixtures, guard predicates and validation reports; this one shows a
preview, a teaching plan and two buttons, and must never grow the other's
vocabulary.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import or_

from app.config import get_settings
from app.meta.approval import (
    ApprovalConflictError,
    ApprovalPreconditionError,
    DraftNotApprovableError,
    DraftNotFoundError,
    RevokedConflictError,
    TemplateNameConflictError,
    approve_draft_service,
)
from app.meta.artifacts import artifact_path
from app.meta.db import meta_session
from app.meta.fingerprint import Fingerprint
from app.meta.fixture_answers import record_computed_answers
from app.meta.ingest import request_template_build
from app.meta.models import (
    DRAFT_APPROVED,
    DRAFT_PENDING_REVIEW,
    DRAFT_REJECTED,
    DRAFT_SUPERSEDED,
    JOB_FAILED,
    JOB_NEEDS_MANUAL,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    GenerationJob,
    TemplateDraft,
)
from app.meta.review_actions import DraftNotRefinableError, requeue_for_refinement
from app.session import TemplateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meta/my")

#: Stages the band renders. Derived from the job and its drafts on every read --
#: none of this is stored, because every part of it is already recorded
#: somewhere that cannot drift.
STAGE_FILED = "filed"
STAGE_QUEUED = "queued"
STAGE_BUILDING = "building"
STAGE_READY = "ready"
STAGE_APPROVED = "approved"
STAGE_FAILED = "failed"
STAGE_NEEDS_MANUAL = "needs_manual"
#: Nothing went wrong: this session can already reach a template for this
#: problem shape. Separated from STAGE_FAILED so the band can say so without
#: styling a non-event as a failure.
STAGE_ALREADY_AVAILABLE = "already_available"

TERMINAL_STAGES = frozenset({
    STAGE_READY, STAGE_APPROVED, STAGE_FAILED, STAGE_NEEDS_MANUAL,
    STAGE_ALREADY_AVAILABLE,
})

_GENERATION_GAVE_UP = (
    "Automatic generation could not produce a visual for this problem. The "
    "labelled text card still works."
)


class CapabilitiesOut(BaseModel):
    enabled: bool


class BuildRequestIn(BaseModel):
    candidate_id: str


class BuildOut(BaseModel):
    candidate_id: str
    fingerprint_key: str | None
    stage: str
    attempt: int
    max_attempts: int
    elapsed_seconds: int
    draft_id: str | None
    error: str | None


class BeatOut(BaseModel):
    id: str
    kind: str
    intent: str


class AttemptOut(BaseModel):
    revision: int
    feedback: str | None
    preview_url: str | None


class DraftOut(BaseModel):
    id: str
    revision: int
    learning_objective: str
    beats: list[BeatOut]
    total_duration_seconds: float
    preview_url: str | None
    suggested_template_name: str
    attempts: list[AttemptOut]
    attempts_remaining: int


class ApproveIn(BaseModel):
    template_name: str
    math_semantics_confirmed: bool


class ApprovedOut(BaseModel):
    template_name: str
    template_version_id: str


class RejectIn(BaseModel):
    feedback: str


class RejectedOut(BaseModel):
    requeued: bool


def _session(session_id: str | None):
    """The caller's live session, or a 400 telling them to upload first."""
    from app.routes import store

    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(
            status_code=400, detail="No active session; upload a document first"
        )
    return session


def _owned_draft(db_session, draft_id: str, owner_session_id: str) -> TemplateDraft:
    """A draft this session owns, or a 404.

    Ownership lives on the job rather than the draft, so a refinement chain is
    owned as a whole. An ownerless (threshold-triggered) draft is deliberately
    unreachable here: it belongs to the admin panel.
    """
    draft = db_session.get(TemplateDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Unknown draft {draft_id}")
    job = db_session.get(GenerationJob, draft.job_id)
    if job is None or job.owner_session_id != owner_session_id:
        raise HTTPException(status_code=404, detail=f"Unknown draft {draft_id}")
    return draft


def _suggested_template_name(draft: TemplateDraft) -> str:
    """A slug from the problem shape, for the teacher to accept or rewrite."""
    fingerprint = Fingerprint.model_validate_json(draft.fingerprint_json)
    return f"{fingerprint.operation_family}_{fingerprint.representation_family}"


def _preview_url(draft: TemplateDraft) -> str | None:
    if not draft.preview_artifact_hash:
        return None
    return f"/meta/my/drafts/{draft.id}/preview"


def _attempts(db_session, draft: TemplateDraft) -> list[AttemptOut]:
    """Every attempt before this one, oldest first.

    Walks ``parent_draft_id`` rather than querying the job's drafts by revision:
    the chain is what actually links an attempt to the feedback that produced the
    next one.
    """
    chain: list[TemplateDraft] = []
    parent_id = draft.parent_draft_id
    while parent_id is not None:
        parent = db_session.get(TemplateDraft, parent_id)
        if parent is None:
            break
        chain.append(parent)
        parent_id = parent.parent_draft_id
    return [
        AttemptOut(
            revision=attempt.revision,
            feedback=attempt.reviewer_feedback,
            preview_url=_preview_url(attempt),
        )
        for attempt in reversed(chain)
    ]


def _latest_draft_for(db_session, job_id: str) -> TemplateDraft | None:
    """The draft that represents this job's current state.

    Ordered by revision so a refinement chain reports its newest attempt, and
    restricted to the statuses a teacher can act on or has acted on -- a
    superseded or rejected draft is history, not the current state.
    """
    return (
        db_session.query(TemplateDraft)
        .filter(
            TemplateDraft.job_id == job_id,
            or_(
                TemplateDraft.status == DRAFT_PENDING_REVIEW,
                TemplateDraft.status == DRAFT_APPROVED,
            ),
        )
        .order_by(TemplateDraft.revision.desc())
        .first()
    )


def _stage_for(db_session, request: TemplateRequest) -> tuple[str, GenerationJob | None, TemplateDraft | None]:
    if request.already_available:
        return STAGE_ALREADY_AVAILABLE, None, None
    if request.error:
        return STAGE_FAILED, None, None
    if request.fingerprint_key is None:
        return STAGE_FILED, None, None

    job = (
        db_session.query(GenerationJob)
        .filter(GenerationJob.fingerprint_key == request.fingerprint_key)
        .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
        .first()
    )
    if job is None:
        return STAGE_FILED, None, None

    draft = _latest_draft_for(db_session, job.id)
    if draft is not None and draft.status == DRAFT_APPROVED:
        return STAGE_APPROVED, job, draft
    if draft is not None and draft.status == DRAFT_PENDING_REVIEW:
        return STAGE_READY, job, draft
    if job.status == JOB_NEEDS_MANUAL:
        return STAGE_NEEDS_MANUAL, job, None
    if job.status == JOB_RUNNING:
        return STAGE_BUILDING, job, None
    if job.status in (JOB_QUEUED, JOB_FAILED):
        # A failed job with attempts left is between tries, which is still
        # "waiting to be picked up" from where the teacher sits.
        return STAGE_QUEUED, job, None
    if job.status == JOB_SUCCEEDED:
        # Succeeded with no reviewable draft left: the teacher rejected the last
        # attempt and the worker has not started the next one yet.
        return STAGE_QUEUED, job, None
    return STAGE_QUEUED, job, None


def _build_out(db_session, request: TemplateRequest, now: datetime) -> BuildOut:
    stage, job, draft = _stage_for(db_session, request)
    error = request.error
    if stage == STAGE_NEEDS_MANUAL:
        error = _GENERATION_GAVE_UP
    return BuildOut(
        candidate_id=request.candidate_id,
        fingerprint_key=request.fingerprint_key,
        stage=stage,
        attempt=draft.revision if draft is not None else (job.attempt if job else 0),
        max_attempts=get_settings().meta_draft_max_refinements,
        elapsed_seconds=max(0, int((now - request.requested_at).total_seconds())),
        draft_id=draft.id if draft is not None else None,
        error=error,
    )


@router.get("/capabilities", response_model=CapabilitiesOut)
def capabilities():
    """Whether a teacher can complete the whole loop, not merely start it.

    All four flags, because any one of them off leaves a dead end: without
    codegen nothing generates, without approval the approve route refuses, and
    without the dynamic classifier an approved template never reaches /options.
    """
    settings = get_settings()
    return CapabilitiesOut(
        enabled=bool(
            settings.meta_templates_enabled
            and settings.meta_codegen_enabled
            and settings.meta_approval_enabled
            and settings.meta_dynamic_classifier_enabled
        )
    )


@router.post("/builds", status_code=202)
def request_build(
    request: BuildRequestIn,
    background_tasks: BackgroundTasks,
    session_id: str | None = Cookie(default=None),
):
    """Ask for a template for one candidate, and return before the work starts.

    Tagging is a Bedrock round trip and enqueueing follows it, so both run in the
    background; the request is recorded on the session first so the band has
    something to report immediately.
    """
    session = _session(session_id)
    candidate = session.candidates.get(request.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"Unknown candidate {request.candidate_id}")

    classification = session.options.get(request.candidate_id)
    grade_level = classification.grade_level if classification else 0
    pending = TemplateRequest(
        candidate_id=request.candidate_id, requested_at=datetime.now(timezone.utc)
    )
    session.template_requests[request.candidate_id] = pending

    def run_build():
        outcome = request_template_build(
            candidate_id=candidate.candidate_id,
            source_excerpt=candidate.source_excerpt,
            grade_level=grade_level,
            owner_session_id=session.session_id,
        )
        pending.fingerprint_key = outcome.fingerprint_key
        pending.error = outcome.error
        pending.already_available = outcome.already_available

    background_tasks.add_task(run_build)
    return {"candidate_id": request.candidate_id}


@router.get("/builds", response_model=list[BuildOut])
def list_builds(session_id: str | None = Cookie(default=None)):
    session = _session(session_id)
    if not session.template_requests:
        return []
    now = datetime.now(timezone.utc)
    with meta_session() as db_session:
        return [
            _build_out(db_session, request, now)
            for request in session.template_requests.values()
        ]


@router.get("/drafts/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: str, session_id: str | None = Cookie(default=None)):
    """What a teacher needs to judge a template, and nothing else.

    No fixtures, guard cases, params documents or reports: the maths is judged
    from the preview and the beats. Those live in the admin surface.
    """
    session = _session(session_id)
    with meta_session() as db_session:
        draft = _owned_draft(db_session, draft_id, session.session_id)
        scene_program = json.loads(draft.scene_program_json) if draft.scene_program_json else {}
        plan = json.loads(draft.teaching_plan_json)
        return DraftOut(
            id=draft.id,
            revision=draft.revision,
            learning_objective=plan["learning_objective"],
            beats=[
                BeatOut(id=beat["id"], kind=beat["kind"], intent=beat["intent"])
                for beat in plan["beats"]
            ],
            total_duration_seconds=scene_program.get("total_duration_seconds", 0.0),
            preview_url=_preview_url(draft),
            suggested_template_name=_suggested_template_name(draft),
            attempts=_attempts(db_session, draft),
            attempts_remaining=max(
                0, get_settings().meta_draft_max_refinements - draft.revision
            ),
        )


@router.get("/drafts/{draft_id}/preview")
def get_preview(draft_id: str, session_id: str | None = Cookie(default=None)):
    """Serve a draft's preview to the session that owns it.

    Authorized by ownership rather than by the hash being hard to guess, which is
    what the token-gated admin preview route relies on.
    """
    session = _session(session_id)
    with meta_session() as db_session:
        draft = _owned_draft(db_session, draft_id, session.session_id)
        if not draft.preview_artifact_hash:
            raise HTTPException(status_code=404, detail="No preview for this draft")
        path = artifact_path(get_settings().meta_artifact_root, draft.preview_artifact_hash)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Preview artifact not found")
        return FileResponse(
            path, media_type="image/png", filename=f"{draft.preview_artifact_hash}.png"
        )


@router.post("/drafts/{draft_id}/approve", response_model=ApprovedOut)
def approve(
    draft_id: str, request: ApproveIn, session_id: str | None = Cookie(default=None)
):
    session = _session(session_id)
    if not get_settings().meta_approval_enabled:
        raise HTTPException(status_code=409, detail="Approval is disabled in this environment")
    with meta_session() as db_session:
        draft = _owned_draft(db_session, draft_id, session.session_id)
        # Approval precondition 8 needs each grounded fixture's expected answer
        # recorded. That value is determined by the draft's own answer
        # expression -- the admin route recomputes it and rejects any human
        # deviation -- so deriving it here is what lets the teacher confirm the
        # mathematics once instead of retyping Python's arithmetic per fixture.
        record_computed_answers(db_session, draft)

    try:
        version = approve_draft_service(
            draft_id=draft_id,
            template_name=request.template_name,
            reviewer_label=f"teacher:{session.session_id}",
            math_semantics_confirmed=request.math_semantics_confirmed,
            owner_session_id=session.session_id,
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftNotApprovableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalPreconditionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RevokedConflictError, TemplateNameConflictError, ApprovalConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ApprovedOut(template_name=version.template_name, template_version_id=version.id)


@router.post("/drafts/{draft_id}/reject", response_model=RejectedOut)
def reject(
    draft_id: str, request: RejectIn, session_id: str | None = Cookie(default=None)
):
    """Reject this attempt and queue another one.

    A reason is required: it is the only thing the next attempt has to work from.
    """
    session = _session(session_id)
    if not request.feedback.strip():
        raise HTTPException(
            status_code=422, detail="Say what is wrong so the next attempt can fix it"
        )
    with meta_session() as db_session:
        _owned_draft(db_session, draft_id, session.session_id)

    try:
        outcome = requeue_for_refinement(
            draft_id,
            feedback=request.feedback,
            reviewer_label=f"teacher:{session.session_id}",
            max_refinements=get_settings().meta_draft_max_refinements,
        )
    except DraftNotRefinableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RejectedOut(requeued=outcome.requeued)
