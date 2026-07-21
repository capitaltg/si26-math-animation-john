from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from app.models.candidate import Candidate
from app.pipeline.classification import ClassificationResult


@dataclass
class Session:
    session_id: str
    candidates: dict[str, Candidate]
    output_dir: Path
    options: dict[str, ClassificationResult] = field(default_factory=dict)


class SessionStore:
    def __init__(self, root_dir: Path):
        self._root = Path(root_dir)
        self._sessions: dict[str, Session] = {}
        self._clips: dict[str, Path] = {}

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
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def register_clip(self, path: Path) -> str:
        clip_id = str(uuid4())
        self._clips[clip_id] = Path(path)
        return clip_id

    def get_clip(self, clip_id: str) -> Path | None:
        return self._clips.get(clip_id)
