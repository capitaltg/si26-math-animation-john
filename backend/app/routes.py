import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Cookie, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from typing import Literal

from app.config import get_settings
from app.meta.db import meta_session
from app.meta.dynamic_templates import load_enabled_snapshot, resolve_dynamic_ref
from app.meta.ingest import record_unsupported_shape
from app.models.candidate import Candidate
from app.models.scene import (
    Scene,
    TemplateName,
    TemplateRef,
    TemplateVersionMismatchError,
)
from app.pipeline.classification import ClassificationResult, classify_candidate
from app.pipeline.discovery import discover_candidates_for_document
from app.pipeline.mismatch import format_answer, scene_mismatch
from app.pipeline.parsing import extract_slide_blocks
from app.pipeline.process_scene import assemble_scene
from app.render.full_render import (
    render_chained_scene_thumbnail,
    render_chained_scene_to_mp4,
    render_scene_thumbnail,
    render_scene_to_mp4,
)
from app.session import SessionStore
from app.templates.registry import (
    get_chained_template,
    get_template,
    is_static_template_name,
    resolve_static_ref,
)

MAX_SLIDES = 50
MAX_BATCH_SIZE = 50
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB, generous for a 50-slide PPTX with images

logger = logging.getLogger(__name__)

router = APIRouter()
store = SessionStore(Path(tempfile.gettempdir()) / "math_anim_sessions")


class CandidateOut(BaseModel):
    candidate_id: str
    source_excerpt: str
    slide_index: int
    one_line_summary: str


class UploadResponse(BaseModel):
    session_id: str
    candidates: list[CandidateOut]


class OptionsRequest(BaseModel):
    candidate_ids: list[str] = Field(max_length=MAX_BATCH_SIZE)


class TemplateOptionOut(BaseModel):
    template: str
    version_id: str
    rationale: str


class RejectedTemplateOut(BaseModel):
    template: str
    reason: Literal["not_applicable", "schema_fail", "low_confidence"]


class CandidateOptionsOut(BaseModel):
    candidate_id: str
    grade_level: int
    ambiguous: bool
    templates: list[TemplateOptionOut]
    vocabulary_size: int
    rejected: list[RejectedTemplateOut]


class OptionsResponse(BaseModel):
    options: list[CandidateOptionsOut]


class RenderPick(BaseModel):
    candidate_id: str
    template: str


class ClipResult(BaseModel):
    scene_id: str
    candidate_id: str | None
    candidate_ids: list[str] | None = None
    status: str
    clip_url: str | None = None
    fallback_reason: str | None = None


class RenderResponse(BaseModel):
    clips: list[ClipResult]


class SceneOut(BaseModel):
    scene_id: str
    candidate_id: str | None
    candidate_ids: list[str] | None = None
    template: str | None
    grade_level: int
    grade_overridden: bool
    params: dict
    params_schema: dict
    status: str
    fallback_reason: str | None = None
    thumbnail_url: str | None = None
    source_excerpt: str
    detected_summary: str
    stated_answer: str | None = None
    stated_answer_source: str | None = None
    mismatch: dict | None = None
    mismatch_acknowledged: bool = False


class StoryboardRequest(BaseModel):
    picks: list[RenderPick] = Field(max_length=MAX_BATCH_SIZE)


class ChainRequest(BaseModel):
    scene_ids: list[str]


class StoryboardResponse(BaseModel):
    scenes: list[SceneOut]


class UngroupResponse(BaseModel):
    scenes: list[SceneOut]


class SceneEditRequest(BaseModel):
    params: dict | None = None
    grade_level: int | None = None


@router.post("/upload", response_model=UploadResponse)
async def upload(response: Response, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Only .pptx uploads are supported")

    contents = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        contents.extend(chunk)
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Upload exceeds the {MAX_UPLOAD_BYTES}-byte limit",
            )

    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        try:
            slide_blocks = extract_slide_blocks(tmp_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Could not parse .pptx file") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if len(slide_blocks) > MAX_SLIDES:
        raise HTTPException(status_code=400, detail=f"Document exceeds the {MAX_SLIDES}-slide cap")

    candidates = discover_candidates_for_document(slide_blocks)
    session = store.create(candidates)
    response.set_cookie(
        "session_id",
        session.session_id,
        httponly=True,
        samesite="lax",
        secure=get_settings().session_cookie_secure,
    )
    return UploadResponse(
        session_id=session.session_id,
        candidates=[CandidateOut(**c.model_dump()) for c in candidates],
    )


@router.post("/options", response_model=OptionsResponse)
def get_options(
    request: OptionsRequest,
    session_id: str | None = Cookie(default=None),
):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    if len(request.candidate_ids) != len(set(request.candidate_ids)):
        raise HTTPException(status_code=400, detail="Duplicate candidate ids are not allowed")

    candidates = []
    for candidate_id in request.candidate_ids:
        candidate = session.candidates.get(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"Unknown candidate {candidate_id}")
        candidates.append((candidate_id, candidate))

    results: list[CandidateOptionsOut] = []
    settings = get_settings()
    snapshot = None
    if settings.meta_dynamic_classifier_enabled:
        with meta_session() as meta_db_session:
            # Scoped to this session: a template this teacher approved privately
            # is theirs to be offered, and another teacher's is not.
            snapshot = load_enabled_snapshot(
                meta_db_session, owner_session_id=session.session_id
            )

    static_names = {member.value for member in TemplateName}
    dynamic_names = set(snapshot.names()) if snapshot is not None else set()
    vocabulary = static_names | dynamic_names

    for candidate_id, candidate in candidates:
        if snapshot is not None:
            classification = classify_candidate(candidate.source_excerpt, snapshot=snapshot)
        else:
            classification = classify_candidate(candidate.source_excerpt)
        session.options[candidate_id] = classification
        matched = {option.template for option in classification.options}
        # Ambiguity or a non-problem input suppresses every structural option
        # regardless of the model's per-template rationale, so the rejection is
        # about confidence in the input, not applicability of the template.
        low_confidence = (
            classification.ambiguous or classification.problem_kind == "not_a_problem"
        )
        rejected = [
            RejectedTemplateOut(
                template=name,
                reason="low_confidence" if low_confidence else "not_applicable",
            )
            for name in sorted(vocabulary - matched)
        ]
        results.append(
            CandidateOptionsOut(
                candidate_id=candidate_id,
                grade_level=classification.grade_level,
                ambiguous=classification.ambiguous,
                templates=[
                    TemplateOptionOut(
                        template=option.template,
                        version_id=option.version_id,
                        rationale=option.rationale,
                    )
                    for option in classification.options
                ],
                vocabulary_size=len(vocabulary),
                rejected=rejected,
            )
        )
    return OptionsResponse(options=results)


def _is_render_ready(scene: Scene) -> bool:
    if scene.status != "approved":
        return False
    # `approved_revision` is only absent for scenes that never went through the
    # approve endpoint (e.g. seeded directly in tests); those are trusted as-is.
    return scene.approved_revision is None or scene.approved_revision == scene.revision


@router.post("/render", response_model=RenderResponse)
def render(session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    approved = [
        session.scenes[sid]
        for sid in session.scene_order
        if _is_render_ready(session.scenes[sid])
    ]
    if not approved:
        raise HTTPException(status_code=400, detail="No approved scenes to render")

    results: list[ClipResult] = []
    for scene in approved:
        clip_url = None
        try:
            output_path = session.output_dir / f"{scene.scene_id}-{uuid4()}.mp4"
            if scene.candidate_ids:
                _, params_cls = get_chained_template(scene.template)
                params = params_cls.model_validate(scene.params)
                render_chained_scene_to_mp4(scene.template, params, output_path)
            else:
                _, params_cls = get_template(scene.template)
                params = params_cls.model_validate(scene.params)
                render_scene_to_mp4(scene.template, params, output_path)
            clip_id = store.register_clip(output_path)
            clip_url = f"/clips/{clip_id}"
            status = "fallback" if scene.fallback_reason else "approved"
        except Exception:
            logger.exception("Full render failed for scene %s", scene.scene_id)
            status = "error"
        results.append(
            ClipResult(
                scene_id=scene.scene_id,
                candidate_id=scene.candidate_id,
                candidate_ids=scene.candidate_ids,
                status=status,
                clip_url=clip_url,
                fallback_reason=scene.fallback_reason,
            )
        )
    return RenderResponse(clips=results)


@router.get("/clips/{clip_id}")
def get_clip(clip_id: str):
    path = store.get_clip(clip_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


def _scene_out(scene: Scene, candidates: list[Candidate]) -> SceneOut:
    schema: dict = {}
    if scene.template is not None:
        if scene.candidate_ids:
            _, params_cls = get_chained_template(scene.template)
        else:
            _, params_cls = get_template(scene.template)
        schema = params_cls.model_json_schema()
    thumbnail_url = None
    if scene.thumbnail_path is not None:
        thumb_id = store.register_thumbnail(scene.thumbnail_path)
        thumbnail_url = f"/thumbnails/{thumb_id}"
    if candidates:
        source_excerpt = " / ".join(c.source_excerpt for c in candidates)
        detected_summary = " / ".join(c.one_line_summary for c in candidates)
    else:
        source_excerpt = scene.manual_source_text or ""
        detected_summary = ""
    stated_answer_display = (
        format_answer(scene.stated_answer) if scene.stated_answer is not None else None
    )
    mismatch = scene_mismatch(scene)
    return SceneOut(
        scene_id=scene.scene_id,
        candidate_id=scene.candidate_id,
        candidate_ids=scene.candidate_ids,
        template=scene.template.name if scene.template else None,
        grade_level=scene.grade_level,
        grade_overridden=scene.grade_overridden,
        params=scene.params,
        params_schema=schema,
        status=scene.status,
        fallback_reason=scene.fallback_reason,
        thumbnail_url=thumbnail_url,
        source_excerpt=source_excerpt,
        detected_summary=detected_summary,
        stated_answer=stated_answer_display,
        stated_answer_source=scene.stated_answer_source,
        mismatch=mismatch,
        mismatch_acknowledged=scene.mismatch_acknowledged,
    )


def _lookup_candidate(session, scene: Scene):
    if not scene.candidate_id:
        return None
    candidate = session.candidates.get(scene.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate no longer available for this scene")
    return candidate


def _lookup_candidates(session, scene: Scene) -> list[Candidate]:
    if scene.candidate_ids:
        candidates = []
        for candidate_id in scene.candidate_ids:
            candidate = session.candidates.get(candidate_id)
            if candidate is None:
                raise HTTPException(
                    status_code=404, detail="Candidate no longer available for this scene"
                )
            candidates.append(candidate)
        return candidates
    candidate = _lookup_candidate(session, scene)
    return [candidate] if candidate else []


def _lookup_active_scene(session, scene_id: str) -> Scene:
    scene = session.scenes.get(scene_id)
    if scene is None or scene_id not in session.scene_order:
        raise HTTPException(status_code=404, detail=f"Unknown scene {scene_id}")
    return scene


@router.post("/storyboard", response_model=StoryboardResponse)
def build_storyboard(request: StoryboardRequest, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    candidate_ids = [pick.candidate_id for pick in request.picks]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise HTTPException(status_code=400, detail="Duplicate candidate ids are not allowed")

    validated: list[tuple[Candidate, ClassificationResult, TemplateRef]] = []
    for pick in request.picks:
        candidate = session.candidates.get(pick.candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"Unknown candidate {pick.candidate_id}")
        classification = session.options.get(pick.candidate_id)
        if classification is None:
            raise HTTPException(
                status_code=400,
                detail=f"No options cached for candidate {pick.candidate_id}",
            )
        offered = {option.template for option in classification.options}
        if pick.template not in offered:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Template {pick.template} was not offered for "
                    f"candidate {pick.candidate_id}"
                ),
            )
        selected_option = next(
            option for option in classification.options if option.template == pick.template
        )
        try:
            if is_static_template_name(selected_option.template):
                template = resolve_static_ref(selected_option.template, selected_option.version_id)
            else:
                with meta_session() as meta_db_session:
                    template = resolve_dynamic_ref(
                        meta_db_session, selected_option.template, selected_option.version_id
                    )
        except TemplateVersionMismatchError as exc:
            raise HTTPException(
                status_code=409,
                detail="The selected template contract changed; request options again",
            ) from exc
        validated.append((candidate, classification, template))

    session.scenes.clear()
    session.scene_order.clear()
    session.scene_requested_template.clear()
    session.scene_chain_members.clear()

    scenes_out: list[SceneOut] = []
    for candidate, classification, template in validated:
        scene = assemble_scene(
            candidate,
            session.output_dir,
            template=template,
            grade=classification.grade_level,
        )
        session.scenes[scene.scene_id] = scene
        session.scene_order.append(scene.scene_id)
        session.scene_requested_template[scene.scene_id] = template
        scenes_out.append(_scene_out(scene, [candidate]))
        record_unsupported_shape(
            candidate_id=candidate.candidate_id,
            source_excerpt=candidate.source_excerpt,
            classification=classification,
            picked_template=template.name,
            scene_status=scene.status,
            failure_kind=scene.failure_kind,
        )
    return StoryboardResponse(scenes=scenes_out)


@router.post("/storyboard/chain", response_model=SceneOut)
def chain_scenes(request: ChainRequest, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    if not 2 <= len(request.scene_ids) <= 4:
        raise HTTPException(
            status_code=400,
            detail="A chain must contain between 2 and 4 scenes",
        )

    if len(request.scene_ids) != len(set(request.scene_ids)):
        raise HTTPException(status_code=400, detail="Duplicate scene ids are not allowed")

    scenes = []
    for scene_id in request.scene_ids:
        scene = session.scenes.get(scene_id)
        if scene is None:
            raise HTTPException(status_code=400, detail=f"Unknown scene {scene_id}")
        if scene.status != "pending_review":
            raise HTTPException(
                status_code=400,
                detail=f"Scene {scene_id} must be pending_review to combine",
            )
        if not scene.candidate_id:
            raise HTTPException(
                status_code=400,
                detail=f"Scene {scene_id} cannot be combined into a chain",
            )
        if scene_id not in session.scene_order:
            raise HTTPException(
                status_code=400,
                detail=f"Scene {scene_id} is no longer available for combining",
            )
        if scene_mismatch(scene) is not None and not scene.mismatch_acknowledged:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "stated_answer_mismatch_in_chain",
                    "scene_id": scene_id,
                },
            )
        scenes.append(scene)

    template = scenes[0].template
    if any(scene.template != template for scene in scenes):
        raise HTTPException(status_code=400, detail="All combined scenes must share one template")

    try:
        _, chained_params_cls = get_chained_template(template)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Template {template.name} cannot be combined into a chain",
        )

    _, params_cls = get_template(template)
    items = [params_cls.model_validate(scene.params) for scene in scenes]
    chained_params = chained_params_cls(items=items)

    thumb_path = session.output_dir / f"chain-{uuid4()}.png"
    try:
        render_chained_scene_thumbnail(template, chained_params, thumb_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Thumbnail render failed") from exc

    new_scene = Scene(
        scene_id=str(uuid4()),
        candidate_ids=[scene.candidate_id for scene in scenes],
        template=template,
        grade_level=scenes[0].grade_level,
        grade_overridden=scenes[0].grade_overridden,
        params=chained_params.model_dump(mode="json"),
        status="pending_review",
        thumbnail_path=thumb_path,
    )

    screen_order_ids = sorted(request.scene_ids, key=session.scene_order.index)
    earliest_index = min(session.scene_order.index(sid) for sid in request.scene_ids)
    for sid in request.scene_ids:
        session.scene_order.remove(sid)
    session.scene_order.insert(earliest_index, new_scene.scene_id)
    session.scenes[new_scene.scene_id] = new_scene
    session.scene_chain_members[new_scene.scene_id] = screen_order_ids

    candidates = _lookup_candidates(session, new_scene)
    return _scene_out(new_scene, candidates)


@router.post("/storyboard/{scene_id}/ungroup", response_model=UngroupResponse)
def ungroup_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    members = session.scene_chain_members.get(scene_id)
    if members is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} is not a combined scene")

    index = session.scene_order.index(scene_id)
    session.scene_order.pop(index)
    for offset, member_id in enumerate(members):
        session.scene_order.insert(index + offset, member_id)

    del session.scenes[scene_id]
    del session.scene_chain_members[scene_id]

    restored = []
    for member_id in members:
        member_scene = session.scenes[member_id]
        candidates = _lookup_candidates(session, member_scene)
        restored.append(_scene_out(member_scene, candidates))
    return UngroupResponse(scenes=restored)


@router.get("/thumbnails/{thumb_id}")
def get_thumbnail(thumb_id: str):
    path = store.get_thumbnail(thumb_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path, media_type="image/png", filename=path.name)


# Pydantic tags every @model_validator / @field_validator raise as
# value_error / assertion_error; everything else is a primitive schema check.
_SEMANTIC_ERROR_TYPES = frozenset({"value_error", "assertion_error"})


def _semantic_rule_id(err: dict) -> str:
    # For a `raise ValueError("<msg>")` in a validator, pydantic sets
    # ctx.error to the original exception and prepends "Value error, " to
    # `msg`. The exception's own string is the stable per-rule identifier
    # (the literal we typed at the raise site); fall back to the prefixed
    # `msg` if pydantic omitted the ctx.
    ctx = err.get("ctx") or {}
    exc = ctx.get("error")
    if exc is not None:
        return str(exc)
    return err.get("msg", err["type"])


def _classify_error(err: dict) -> tuple[str, str]:
    err_type = err["type"]
    if err_type in _SEMANTIC_ERROR_TYPES:
        return "semantic", _semantic_rule_id(err)
    return "schema", err_type


def _field_errors(exc: ValidationError) -> dict:
    # Each entry carries the raw pydantic `type`, plus `category`
    # (schema|semantic) and a stable `rule` label — the UI routes by
    # category and renders `rule` instead of a shared "value_error" tag.
    out = []
    for e in exc.errors():
        category, rule = _classify_error(e)
        out.append(
            {
                "loc": list(e["loc"]),
                "msg": e["msg"],
                "type": e["type"],
                "rule": rule,
                "category": category,
            }
        )
    return {"errors": out}


def _write_scene_cas(
    session, scene_id: str, base_revision: int, updates: dict, *, bump_revision: bool = True
) -> Scene:
    """Commit `updates` to a scene, rejecting the write if it raced another one.

    Both the initial read and this write must agree on `revision`, so a request
    that read stale data (e.g. it raced a concurrent edit or approve) gets a 409
    instead of silently clobbering the other request's change. `bump_revision`
    is False for writes that don't change render-affecting content (e.g. a
    no-op PATCH), so they can't drift `revision` away from `approved_revision`
    and invalidate an approval that nothing actually changed.
    """
    with session.scenes_lock:
        current = session.scenes[scene_id]
        if current.revision != base_revision:
            raise HTTPException(
                status_code=409,
                detail="Scene was modified by another request; reload and try again",
            )
        next_revision = base_revision + 1 if bump_revision else base_revision
        updated = current.model_copy(update={**updates, "revision": next_revision})
        session.scenes[scene_id] = updated
    return updated


@router.patch("/storyboard/{scene_id}", response_model=SceneOut)
def edit_scene(
    scene_id: str,
    request: SceneEditRequest,
    session_id: str | None = Cookie(default=None),
):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = _lookup_active_scene(session, scene_id)
    candidates = _lookup_candidates(session, scene)
    if scene.template is None:
        raise HTTPException(status_code=400, detail="Cannot edit a scene without a template")

    if request.grade_level is not None and not (0 <= request.grade_level <= 8):
        # Route range check, not a cross-field rule — the UI splits by
        # category and treats this as a Schema failure.
        raise HTTPException(
            status_code=422,
            detail={
                "errors": [
                    {
                        "loc": ["grade_level"],
                        "msg": "grade_level must be between 0 and 8",
                        "type": "grade_range",
                        "rule": "grade_range",
                        "category": "schema",
                    }
                ]
            },
        )

    new_params = scene.params
    new_thumb = scene.thumbnail_path
    params_changed = False
    if request.params is not None:
        if scene.candidate_ids:
            _, params_cls = get_chained_template(scene.template)
        else:
            _, params_cls = get_template(scene.template)
        try:
            params = params_cls.model_validate(request.params)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=_field_errors(exc))
        out = session.output_dir / f"{scene.scene_id}-{uuid4()}.png"
        try:
            if scene.candidate_ids:
                render_chained_scene_thumbnail(scene.template, params, out)
            else:
                render_scene_thumbnail(scene.template, params, out)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Thumbnail render failed") from exc
        new_params = params.model_dump(mode="json")
        new_thumb = out
        params_changed = new_params != scene.params

    grade = request.grade_level if request.grade_level is not None else scene.grade_level
    grade_overridden = scene.grade_overridden or request.grade_level is not None
    grade_changed = request.grade_level is not None and request.grade_level != scene.grade_level

    updates = {
        "params": new_params,
        "thumbnail_path": new_thumb,
        "grade_level": grade,
        "grade_overridden": grade_overridden,
    }
    # A real content change invalidates any prior review decision; the teacher
    # must re-review before it can render again. A no-op PATCH (empty body, or
    # a field resent unchanged) must not revoke a standing approval.
    content_changed = params_changed or grade_changed
    if content_changed and scene.status in ("approved", "rejected"):
        updates["status"] = "pending_review"
    if content_changed:
        updates["mismatch_acknowledged"] = False

    updated = _write_scene_cas(
        session, scene_id, scene.revision, updates, bump_revision=content_changed
    )
    return _scene_out(updated, candidates)


def _guard_approval_mismatch(scene: Scene) -> None:
    mismatch = scene_mismatch(scene)
    if mismatch is None or scene.mismatch_acknowledged:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "error": "stated_answer_mismatch",
            "stated": mismatch["stated"],
            "computed": mismatch["computed"],
        },
    )


def _set_scene_status(session_id: str | None, scene_id: str, status: str) -> SceneOut:
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = _lookup_active_scene(session, scene_id)
    candidates = _lookup_candidates(session, scene)
    updates = {"status": status}
    if status == "approved":
        # Pins the approval to the revision it was granted for; render checks
        # this so a later edit (or a lost race) can't ride on a stale approval.
        updates["approved_revision"] = scene.revision + 1
    updated = _write_scene_cas(session, scene_id, scene.revision, updates)
    return _scene_out(updated, candidates)


@router.post("/storyboard/{scene_id}/approve", response_model=SceneOut)
def approve_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = _lookup_active_scene(session, scene_id)
    _guard_approval_mismatch(scene)
    return _set_scene_status(session_id, scene_id, "approved")


@router.post("/storyboard/{scene_id}/acknowledge-mismatch", response_model=SceneOut)
def acknowledge_mismatch(scene_id: str, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = _lookup_active_scene(session, scene_id)
    if scene_mismatch(scene) is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "no_mismatch_to_acknowledge"},
        )
    candidates = _lookup_candidates(session, scene)
    updated = _write_scene_cas(
        session, scene_id, scene.revision, {"mismatch_acknowledged": True}
    )
    return _scene_out(updated, candidates)


@router.post("/storyboard/{scene_id}/reject", response_model=SceneOut)
def reject_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    return _set_scene_status(session_id, scene_id, "rejected")


@router.post("/storyboard/{scene_id}/retry", response_model=SceneOut)
def retry_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = _lookup_active_scene(session, scene_id)
    candidate = _lookup_candidate(session, scene)
    if candidate is None:
        raise HTTPException(status_code=400, detail="This scene cannot be retried")
    template = session.scene_requested_template.get(scene_id)
    if template is None:
        raise HTTPException(status_code=400, detail="This scene cannot be retried")

    fresh = assemble_scene(
        candidate,
        session.output_dir,
        template=template,
        grade=scene.grade_level,
    )
    updated = fresh.model_copy(
        update={"scene_id": scene_id, "grade_overridden": scene.grade_overridden}
    )
    session.scenes[scene_id] = updated
    return _scene_out(updated, [candidate])
