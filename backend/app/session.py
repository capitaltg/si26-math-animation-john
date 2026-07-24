import shutil
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from app.models.candidate import Candidate
from app.models.scene import Scene, TemplateName
from app.pipeline.classification import ClassificationResult

DEFAULT_MAX_SESSIONS = 200
DEFAULT_MAX_CLIPS = 1000
DEFAULT_MAX_THUMBNAILS = 1000


@dataclass
class Session:
    session_id: str
    candidates: dict[str, Candidate]
    output_dir: Path
    options: dict[str, ClassificationResult] = field(default_factory=dict)
    scenes: dict[str, Scene] = field(default_factory=dict)
    scene_order: list[str] = field(default_factory=list)
    scene_requested_template: dict[str, TemplateName] = field(default_factory=dict)
    scene_chain_members: dict[str, list[str]] = field(default_factory=dict)


class SessionStore:
    def __init__(
        self,
        root_dir: Path,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_clips: int = DEFAULT_MAX_CLIPS,
        max_thumbnails: int = DEFAULT_MAX_THUMBNAILS,
    ):
        self._root = Path(root_dir)
        self._max_sessions = max_sessions
        self._max_clips = max_clips
        self._max_thumbnails = max_thumbnails
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._clips: OrderedDict[str, Path] = OrderedDict()
        self._thumbnails: OrderedDict[str, Path] = OrderedDict()

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

    def register_thumbnail(self, path: Path) -> str:
        thumb_id = str(uuid4())
        self._thumbnails[thumb_id] = Path(path)
        if len(self._thumbnails) > self._max_thumbnails:
            self._thumbnails.popitem(last=False)
        return thumb_id

    def get_thumbnail(self, thumb_id: str) -> Path | None:
        return self._thumbnails.get(thumb_id)
