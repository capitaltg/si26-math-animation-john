"""Per-process session store.

``SessionStore`` and its clip/thumbnail registries live in the memory of the
Python process that instantiated them. They are **not** shared across
``uvicorn --workers N`` processes or across multiple backend instances: a
cookie routed to a worker that never saw the upload gets a 400. The demo runs
a single ``uvicorn`` worker on purpose; do not raise ``--workers`` or scale
horizontally without first moving session state to a durable, versioned store
(Redis, Postgres row lock, etc.). See README "Deployment" note.
"""

import shutil
import threading
import time
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
DEFAULT_MAX_THUMBNAILS = 1000
#: Per-session cap covering clip and thumbnail bytes together. Sized so a deck
#: of ~200 ten-MiB clips fits before the LRU-by-session eviction kicks in.
DEFAULT_MAX_BYTES_PER_SESSION = 2 * 1024 * 1024 * 1024


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
    #: Guards read-modify-write of every mutable session field a concurrent
    #: request can reach: `scenes`, `scene_order`, `scene_chain_members`,
    #: `options`, and `template_requests`. A single lock keeps the invariants
    #: between these fields intact — e.g. group/ungroup rewrites both
    #: `scene_order` and `scenes` at once, and must not be observed torn by a
    #: concurrent render or approve. See `_write_scene_cas` in routes.py.
    session_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    #: Scene IDs currently being rendered by an in-flight /render call.
    #: Guarded by `session_lock`. Prevents duplicate subprocess launches when a
    #: client retries before the first request returns.
    rendering_scene_ids: set[str] = field(default_factory=set, repr=False, compare=False)
    #: scene_id -> clip_id last handed to the client for a successful render.
    #: Lets an idempotent re-render return the same URL without re-registering.
    scene_clip_id: dict[str, str] = field(default_factory=dict, repr=False, compare=False)


@dataclass
class _Entry:
    path: Path
    session_id: str | None
    size: int
    created_at: float


class SessionStore:
    def __init__(
        self,
        root_dir: Path,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_clips: int = DEFAULT_MAX_CLIPS,
        max_thumbnails: int = DEFAULT_MAX_THUMBNAILS,
        max_bytes_per_session: int = DEFAULT_MAX_BYTES_PER_SESSION,
        ttl_seconds: float | None = None,
    ):
        self._root = Path(root_dir)
        self._max_sessions = max_sessions
        self._max_clips = max_clips
        self._max_thumbnails = max_thumbnails
        self._max_bytes_per_session = max_bytes_per_session
        self._ttl_seconds = ttl_seconds
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._clips: OrderedDict[str, _Entry] = OrderedDict()
        self._thumbnails: OrderedDict[str, _Entry] = OrderedDict()
        # Paths a writer has claimed but not yet registered. Sweeps must not
        # touch these — deleting a partial render mid-write leaves the caller
        # writing into a hole.
        self._reserved: set[Path] = set()
        # Single lock guards registries, reservations, and the session index
        # together so eviction paths can't observe half-updated state.
        self._lock = threading.Lock()

    def create(self, candidates: list[Candidate]) -> Session:
        session_id = str(uuid4())
        output_dir = self._root / session_id
        output_dir.mkdir(parents=True, exist_ok=True)
        session = Session(
            session_id=session_id,
            candidates={c.candidate_id: c for c in candidates},
            output_dir=output_dir,
        )
        with self._lock:
            self._sessions[session_id] = session
            evicted: Session | None = None
            if len(self._sessions) > self._max_sessions:
                _, evicted = self._sessions.popitem(last=False)
                self._drop_session_entries_locked(evicted.session_id)
        if evicted is not None:
            shutil.rmtree(evicted.output_dir, ignore_errors=True)
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                self._sessions.move_to_end(session_id)
        return session

    def reserve(self, session: Session, suffix: str = ".mp4") -> Path:
        """Return a unique in-session path that sweeps will skip until commit."""
        path = session.output_dir / f"{uuid4()}{suffix}"
        with self._lock:
            self._reserved.add(path)
        return path

    def abort(self, path: Path) -> None:
        """Release a reservation and delete any partial file written to it."""
        path = Path(path)
        with self._lock:
            self._reserved.discard(path)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def reserved_paths(self) -> set[Path]:
        with self._lock:
            return set(self._reserved)

    def register_clip(self, path: Path, *, session_id: str | None = None) -> str | None:
        """Register `path` and return an id. Returns None if the file no longer
        exists — eviction may have removed it since the caller last saw the
        path, and registering a dead path would hand back a guaranteed-404 URL.
        """
        path = Path(path)
        if not path.exists():
            return None
        clip_id = str(uuid4())
        entry = _Entry(
            path=path,
            session_id=session_id,
            size=_safe_size(path),
            created_at=time.time(),
        )
        evicted: list[_Entry] = []
        with self._lock:
            self._reserved.discard(path)
            self._clips[clip_id] = entry
            self._expire_ttl_locked(evicted)
            self._enforce_global_cap_locked(self._clips, self._max_clips, evicted)
            self._enforce_session_bytes_locked(session_id, evicted)
            self._delete_orphaned_files_locked(evicted)
        return clip_id

    def get_clip(
        self, clip_id: str, *, caller_session_id: str | None = None
    ) -> Path | None:
        with self._lock:
            entry = self._clips.get(clip_id)
        if entry is None:
            return None
        if entry.session_id is not None and entry.session_id != caller_session_id:
            return None
        return entry.path

    def register_thumbnail(self, path: Path, *, session_id: str | None = None) -> str | None:
        """See `register_clip` — same missing-file guard."""
        path = Path(path)
        if not path.exists():
            return None
        thumb_id = str(uuid4())
        entry = _Entry(
            path=path,
            session_id=session_id,
            size=_safe_size(path),
            created_at=time.time(),
        )
        evicted: list[_Entry] = []
        with self._lock:
            self._reserved.discard(path)
            self._thumbnails[thumb_id] = entry
            self._expire_ttl_locked(evicted)
            self._enforce_global_cap_locked(self._thumbnails, self._max_thumbnails, evicted)
            self._enforce_session_bytes_locked(session_id, evicted)
            self._delete_orphaned_files_locked(evicted)
        return thumb_id

    def get_thumbnail(
        self, thumb_id: str, *, caller_session_id: str | None = None
    ) -> Path | None:
        with self._lock:
            entry = self._thumbnails.get(thumb_id)
        if entry is None:
            return None
        if entry.session_id is not None and entry.session_id != caller_session_id:
            return None
        return entry.path

    def sweep_orphans(self) -> int:
        """Delete files under root_dir that no live entry or reservation owns.

        Registries live in memory only, so on process boot every file under
        root_dir is by definition orphaned — this reclaims disk left behind by
        the previous run. Also safe to call at runtime: registered and reserved
        paths are skipped, so an in-flight render is never disturbed.
        """
        if not self._root.exists():
            return 0
        with self._lock:
            keep = {e.path for e in self._clips.values()}
            keep.update(e.path for e in self._thumbnails.values())
            keep.update(self._reserved)
        removed = 0
        for session_dir in self._root.iterdir():
            if not session_dir.is_dir():
                continue
            for f in session_dir.iterdir():
                if f.is_dir() or f in keep:
                    continue
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    def enforce_global_cap(self, max_bytes: int) -> int:
        """Evict oldest clips/thumbs across all sessions until total ≤ max_bytes.

        Complements `_enforce_session_bytes_locked` (per-session cap) with a
        volume-wide ceiling: on a public demo the sum of per-session budgets
        can still eat the whole disk. Returns the count of registrations
        dropped (not bytes freed). A cap of 0 disables the check.
        """
        if max_bytes <= 0:
            return 0
        evicted: list[_Entry] = []
        with self._lock:
            total = sum(
                e.size
                for reg in (self._clips, self._thumbnails)
                for e in reg.values()
            )
            while total > max_bytes:
                # Pick the globally oldest entry across both registries. Both
                # OrderedDicts are insertion-ordered → first item per reg is
                # its oldest; compare the two heads by created_at.
                candidates = []
                for reg in (self._clips, self._thumbnails):
                    if reg:
                        oldest_id = next(iter(reg))
                        candidates.append((reg[oldest_id].created_at, oldest_id, reg))
                if not candidates:
                    break
                candidates.sort(key=lambda t: t[0])
                _, oldest_id, oldest_reg = candidates[0]
                evicted.append(oldest_reg.pop(oldest_id))
                total = sum(
                    e.size
                    for reg in (self._clips, self._thumbnails)
                    for e in reg.values()
                )
            self._delete_orphaned_files_locked(evicted)
        return len(evicted)

    # --- internal ----------------------------------------------------------

    def _drop_session_entries_locked(self, session_id: str) -> None:
        for reg in (self._clips, self._thumbnails):
            stale = [k for k, e in reg.items() if e.session_id == session_id]
            for k in stale:
                del reg[k]

    def _delete_orphaned_files_locked(self, evicted: list[_Entry]) -> None:
        # The same path may be registered under multiple IDs — _scene_out
        # re-registers a scene's thumbnail every time it serializes the scene,
        # and rev-hash tracking can re-register a clip. Only unlink once no
        # live entry or in-flight reservation still points at the path.
        live = {e.path for e in self._clips.values()}
        live.update(e.path for e in self._thumbnails.values())
        live.update(self._reserved)
        for e in evicted:
            if e.path in live:
                continue
            try:
                e.path.unlink(missing_ok=True)
            except OSError:
                pass

    def _expire_ttl_locked(self, evicted: list[_Entry]) -> None:
        if self._ttl_seconds is None:
            return
        cutoff = time.time() - self._ttl_seconds
        for reg in (self._clips, self._thumbnails):
            stale = [k for k, e in reg.items() if e.created_at < cutoff]
            for k in stale:
                evicted.append(reg.pop(k))

    @staticmethod
    def _enforce_global_cap_locked(
        reg: OrderedDict[str, _Entry], cap: int, evicted: list[_Entry]
    ) -> None:
        while len(reg) > cap:
            _, e = reg.popitem(last=False)
            evicted.append(e)

    def _enforce_session_bytes_locked(
        self, session_id: str | None, evicted: list[_Entry]
    ) -> None:
        if session_id is None:
            return
        cap = self._max_bytes_per_session
        while True:
            total = sum(
                e.size
                for reg in (self._clips, self._thumbnails)
                for e in reg.values()
                if e.session_id == session_id
            )
            if total <= cap:
                return
            oldest_id, oldest_reg = self._oldest_for_session_locked(session_id)
            if oldest_id is None:
                return
            evicted.append(oldest_reg.pop(oldest_id))

    def _oldest_for_session_locked(
        self, session_id: str
    ) -> tuple[str | None, OrderedDict[str, _Entry]]:
        best_id: str | None = None
        best_reg: OrderedDict[str, _Entry] = self._clips
        best_ts = float("inf")
        for reg in (self._clips, self._thumbnails):
            for k, e in reg.items():
                if e.session_id != session_id:
                    continue
                if e.created_at < best_ts:
                    best_id, best_reg, best_ts = k, reg, e.created_at
                break  # OrderedDict is insertion-ordered; first hit per reg is oldest
        return best_id, best_reg


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
