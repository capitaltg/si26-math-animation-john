import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Cookie, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings
from app.models.scene import Scene, TemplateName
from app.pipeline.classification import classify_candidate
from app.pipeline.discovery import discover_candidates_for_document
from app.pipeline.parsing import extract_slide_texts
from app.pipeline.process_scene import assemble_scene
from app.render.full_render import render_scene_thumbnail, render_scene_to_mp4
from app.session import SessionStore
from app.templates.registry import get_template

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
    template: TemplateName
    rationale: str


class CandidateOptionsOut(BaseModel):
    candidate_id: str
    grade_level: int
    ambiguous: bool
    templates: list[TemplateOptionOut]


class OptionsResponse(BaseModel):
    options: list[CandidateOptionsOut]


class RenderPick(BaseModel):
    candidate_id: str
    template: str


class ClipResult(BaseModel):
    candidate_id: str
    status: str
    clip_url: str | None = None
    fallback_reason: str | None = None


class RenderResponse(BaseModel):
    clips: list[ClipResult]


class SceneOut(BaseModel):
    scene_id: str
    candidate_id: str | None
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


class StoryboardRequest(BaseModel):
    picks: list[RenderPick] = Field(max_length=MAX_BATCH_SIZE)


class StoryboardResponse(BaseModel):
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
            slide_texts = extract_slide_texts(tmp_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Could not parse .pptx file") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if len(slide_texts) > MAX_SLIDES:
        raise HTTPException(status_code=400, detail=f"Document exceeds the {MAX_SLIDES}-slide cap")

    candidates = discover_candidates_for_document(slide_texts)
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
    for candidate_id, candidate in candidates:
        classification = classify_candidate(candidate.source_excerpt)
        session.options[candidate_id] = classification
        results.append(
            CandidateOptionsOut(
                candidate_id=candidate_id,
                grade_level=classification.grade_level,
                ambiguous=classification.ambiguous,
                templates=[
                    TemplateOptionOut(
                        template=option.template,
                        rationale=option.rationale,
                    )
                    for option in classification.options
                ],
            )
        )
    return OptionsResponse(options=results)


@router.post("/render", response_model=RenderResponse)
def render(session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    approved = [
        session.scenes[sid]
        for sid in session.scene_order
        if session.scenes[sid].status == "approved"
    ]
    if not approved:
        raise HTTPException(status_code=400, detail="No approved scenes to render")

    results: list[ClipResult] = []
    for scene in approved:
        clip_url = None
        try:
            _, params_cls = get_template(scene.template)
            params = params_cls.model_validate(scene.params)
            output_path = session.output_dir / f"{scene.candidate_id}-{uuid4()}.mp4"
            render_scene_to_mp4(scene.template, params, output_path)
            clip_id = store.register_clip(output_path)
            clip_url = f"/clips/{clip_id}"
            status = "fallback" if scene.fallback_reason else "approved"
        except Exception:
            logger.exception("Full render failed for scene %s", scene.scene_id)
            status = "error"
        results.append(
            ClipResult(
                candidate_id=scene.candidate_id,
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


def _scene_out(scene: Scene, candidate) -> SceneOut:
    schema: dict = {}
    if scene.template is not None:
        _, params_cls = get_template(scene.template)
        schema = params_cls.model_json_schema()
    thumbnail_url = None
    if scene.thumbnail_path is not None:
        thumb_id = store.register_thumbnail(scene.thumbnail_path)
        thumbnail_url = f"/thumbnails/{thumb_id}"
    source_excerpt = candidate.source_excerpt if candidate else (scene.manual_source_text or "")
    detected_summary = candidate.one_line_summary if candidate else ""
    return SceneOut(
        scene_id=scene.scene_id,
        candidate_id=scene.candidate_id,
        template=scene.template.value if scene.template else None,
        grade_level=scene.grade_level,
        grade_overridden=scene.grade_overridden,
        params=scene.params,
        params_schema=schema,
        status=scene.status,
        fallback_reason=scene.fallback_reason,
        thumbnail_url=thumbnail_url,
        source_excerpt=source_excerpt,
        detected_summary=detected_summary,
    )


def _lookup_candidate(session, scene: Scene):
    if not scene.candidate_id:
        return None
    candidate = session.candidates.get(scene.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate no longer available for this scene")
    return candidate


@router.post("/storyboard", response_model=StoryboardResponse)
def build_storyboard(request: StoryboardRequest, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    candidate_ids = [pick.candidate_id for pick in request.picks]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise HTTPException(status_code=400, detail="Duplicate candidate ids are not allowed")

    validated = []
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
        offered = {option.template.value for option in classification.options}
        if pick.template not in offered:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Template {pick.template} was not offered for "
                    f"candidate {pick.candidate_id}"
                ),
            )
        validated.append((candidate, classification, TemplateName(pick.template)))

    session.scenes.clear()
    session.scene_order.clear()
    session.scene_requested_template.clear()

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
        scenes_out.append(_scene_out(scene, candidate))
    return StoryboardResponse(scenes=scenes_out)


@router.get("/thumbnails/{thumb_id}")
def get_thumbnail(thumb_id: str):
    path = store.get_thumbnail(thumb_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path, media_type="image/png", filename=path.name)


def _field_errors(exc: ValidationError) -> dict:
    return {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}


@router.patch("/storyboard/{scene_id}", response_model=SceneOut)
def edit_scene(
    scene_id: str,
    request: SceneEditRequest,
    session_id: str | None = Cookie(default=None),
):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = session.scenes.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Unknown scene {scene_id}")
    candidate = _lookup_candidate(session, scene)
    if scene.template is None:
        raise HTTPException(status_code=400, detail="Cannot edit a scene without a template")

    if request.grade_level is not None and not (0 <= request.grade_level <= 8):
        raise HTTPException(
            status_code=422,
            detail={
                "errors": [
                    {"loc": ["grade_level"], "msg": "grade_level must be between 0 and 8"}
                ]
            },
        )

    new_params = scene.params
    new_thumb = scene.thumbnail_path
    if request.params is not None:
        _, params_cls = get_template(scene.template)
        try:
            params = params_cls.model_validate(request.params)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=_field_errors(exc))
        out = session.output_dir / f"{scene.candidate_id}-{uuid4()}.png"
        try:
            render_scene_thumbnail(scene.template, params, out)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Thumbnail render failed") from exc
        new_params = params.model_dump(mode="json")
        new_thumb = out

    grade = request.grade_level if request.grade_level is not None else scene.grade_level
    grade_overridden = scene.grade_overridden or request.grade_level is not None

    updated = scene.model_copy(
        update={
            "params": new_params,
            "thumbnail_path": new_thumb,
            "grade_level": grade,
            "grade_overridden": grade_overridden,
        }
    )
    session.scenes[scene_id] = updated
    return _scene_out(updated, candidate)


def _set_scene_status(session_id: str | None, scene_id: str, status: str) -> SceneOut:
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = session.scenes.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Unknown scene {scene_id}")
    candidate = _lookup_candidate(session, scene)
    updated = scene.model_copy(update={"status": status})
    session.scenes[scene_id] = updated
    return _scene_out(updated, candidate)


@router.post("/storyboard/{scene_id}/approve", response_model=SceneOut)
def approve_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    return _set_scene_status(session_id, scene_id, "approved")


@router.post("/storyboard/{scene_id}/reject", response_model=SceneOut)
def reject_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    return _set_scene_status(session_id, scene_id, "rejected")


@router.post("/storyboard/{scene_id}/retry", response_model=SceneOut)
def retry_scene(scene_id: str, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")
    scene = session.scenes.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Unknown scene {scene_id}")
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
    return _scene_out(updated, candidate)
