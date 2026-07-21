import tempfile
from pathlib import Path

from fastapi import APIRouter, Cookie, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.models.scene import TemplateName
from app.pipeline.classification import classify_candidate
from app.pipeline.discovery import discover_candidates_for_document
from app.pipeline.parsing import extract_slide_texts
from app.pipeline.process_scene import process_scene
from app.session import SessionStore

MAX_SLIDES = 50
MAX_BATCH_SIZE = 50
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB, generous for a 50-slide PPTX with images

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


class RenderRequest(BaseModel):
    picks: list[RenderPick] = Field(max_length=MAX_BATCH_SIZE)


class ClipResult(BaseModel):
    candidate_id: str
    status: str
    clip_url: str | None = None
    fallback_reason: str | None = None


class RenderResponse(BaseModel):
    clips: list[ClipResult]


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
    response.set_cookie("session_id", session.session_id, httponly=True, samesite="lax")
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
def render(request: RenderRequest, session_id: str | None = Cookie(default=None)):
    session = store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=400, detail="No active session; upload a document first")

    candidate_ids = [pick.candidate_id for pick in request.picks]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise HTTPException(status_code=400, detail="Duplicate candidate ids are not allowed")

    validated_picks = []
    for pick in request.picks:
        candidate = session.candidates.get(pick.candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown candidate {pick.candidate_id}",
            )

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
        selected_template = TemplateName(pick.template)
        validated_picks.append((pick, candidate, classification, selected_template))

    results: list[ClipResult] = []
    for pick, candidate, classification, selected_template in validated_picks:
        scene = process_scene(
            candidate,
            session.output_dir,
            template=selected_template,
            grade=classification.grade_level,
        )
        clip_url = None
        if scene.render_path is not None:
            clip_id = store.register_clip(scene.render_path)
            clip_url = f"/clips/{clip_id}"
        results.append(
            ClipResult(
                candidate_id=pick.candidate_id,
                status=scene.status,
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
