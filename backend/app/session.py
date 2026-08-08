import shutil
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateRef
from app.pipeline.classification import ClassificationResult

DEFAULT_MAX_SESSIONS = 200
DEFAULT_MAX_CLIPS = 1000
DEFAULT_MAX_PREVIEWS = 1000


@dataclass
class TemplateRequest:
    """One teacher's request to build a template for one candidate.

    ``fingerprint_key`` stays None until the background task has tagged the
    problem successfully, which is what separates "filed" from "queued". If that
    task cannot get as far as a queued job it writes a teacher-readable sentence
    into ``error``; without it a request whose background work died would report
    progress forever, since there would be no job row to derive a stage from.
    """

    candidate_id: str
    requested_at: datetime
    fingerprint_key: str | None = None
    error: str | None = None
    #: True when the request was declined because this session can already reach
    #: a template for the shape. Nothing went wrong, so it must not be reported
    #: as a failure.
    already_available: bool = False


@dataclass
class Session:
    session_id: str
    candidates: dict[str, Candidate]
    output_dir: Path
    options: dict[str, ClassificationResult] = field(default_factory=dict)
    scenes: dict[str, Scene] = field(default_factory=dict)
    scene_order: list[str] = field(default_factory=list)
    scene_requested_template: dict[str, TemplateRef] = field(default_factory=dict)
    scene_chain_members: dict[str, list[str]] = field(default_factory=dict)
    template_requests: dict[str, TemplateRequest] = field(default_factory=dict)
    #: Guards read-modify-write of `scenes` so a concurrent edit and approve
    #: can't silently overwrite one another; see `_write_scene_cas` in routes.py.
    scenes_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)


class SessionStore:
    def __init__(
        self,
        root_dir: Path,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_clips: int = DEFAULT_MAX_CLIPS,
        max_previews: int = DEFAULT_MAX_PREVIEWS,
    ):
        self._root = Path(root_dir)
        self._max_sessions = max_sessions
        self._max_clips = max_clips
        self._max_previews = max_previews
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._clips: OrderedDict[str, Path] = OrderedDict()
        self._previews: OrderedDict[str, Path] = OrderedDict()

    def create(self, candidates: list[Candidate]) -> Session:
        session_id = str(uuid4())
        output_dir = self._root / session_id
        output_dir.mkdir(parents=True, exist_ok=True)
        session = Session(
            session_id=session_id,
            candidates={c.candidate_id: c for c in candidates},
            output_dir=output_dir,
        )
        self._sessions[session_id] = session
        if len(self._sessions) > self._max_sessions:
            _, evicted = self._sessions.popitem(last=False)
            shutil.rmtree(evicted.output_dir, ignore_errors=True)
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session is not None:
            self._sessions.move_to_end(session_id)
        return session

    def register_clip(self, path: Path) -> str:
        clip_id = str(uuid4())
        self._clips[clip_id] = Path(path)
        if len(self._clips) > self._max_clips:
            self._clips.popitem(last=False)
        return clip_id

    def get_clip(self, clip_id: str) -> Path | None:
        return self._clips.get(clip_id)

    def register_preview(self, path: Path) -> str:
        preview_id = str(uuid4())
        self._previews[preview_id] = Path(path)
        if len(self._previews) > self._max_previews:
            self._previews.popitem(last=False)
        return preview_id

    def get_preview(self, preview_id: str) -> Path | None:
        return self._previews.get(preview_id)
