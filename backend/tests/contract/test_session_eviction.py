"""Contract: session eviction leaves no state behind.

Per-mechanism eviction tests live in tests/test_session.py — clip file
unlinked, thumbnail entry cleared, LRU dir removed, etc. The invariant that
binds them together is total absence: after `SessionStore.create` pops the
LRU session, nothing that session put anywhere is still reachable through
the store.

This test seeds one session with an entry in every known state layer, then
triggers LRU eviction, then asserts the union of "state layers a session
can leave behind" is empty for that session id. A new state layer added to
`SessionStore` without a matching cleanup path leaves the seeded entry
behind and the test fails, forcing the author to extend eviction.
"""

from app.models.candidate import Candidate
from app.session import SessionStore


def _candidate(cid: str) -> Candidate:
    return Candidate(
        candidate_id=cid,
        source_excerpt="4 + 3",
        slide_index=0,
        one_line_summary="Detected: 4 + 3",
    )


def test_lru_eviction_clears_every_known_state_location(tmp_path):
    """State layers enumerated here are the full list a Session touches:

    1. ``store._sessions`` — the Session object index.
    2. ``store._clips`` — clip registry entries tagged with the session id.
    3. ``store._thumbnails`` — thumbnail registry entries tagged with the
       session id.
    4. ``session.output_dir`` — the session's directory under root.
    5. Any file the session wrote under its output_dir but never registered
       (e.g. an aborted render that survived the crash) must be gone with
       the directory tree.

    ``rendering_scene_ids`` and the session lock live on the Session dataclass
    and vanish when the Session object is dropped from ``_sessions`` — they
    are per-Session in-memory state, not a shared registry, so they are
    covered by (1).
    """
    store = SessionStore(tmp_path, max_sessions=1)

    victim = store.create([_candidate("a")])
    session_id = victim.session_id
    output_dir = victim.output_dir

    clip_path = output_dir / "clip.mp4"
    clip_path.write_bytes(b"clip")
    clip_id = store.register_clip(clip_path, session_id=session_id)

    thumb_path = output_dir / "thumb.png"
    thumb_path.write_bytes(b"thumb")
    thumb_id = store.register_thumbnail(thumb_path, session_id=session_id)

    orphan_in_dir = output_dir / "half-render.tmp"
    orphan_in_dir.write_bytes(b"partial")

    assert store.get(session_id) is victim
    assert store.get_clip(clip_id, caller_session_id=session_id) == clip_path
    assert (
        store.get_thumbnail(thumb_id, caller_session_id=session_id) == thumb_path
    )
    assert output_dir.is_dir()

    store.create([_candidate("b")])

    assert store.get(session_id) is None
    assert session_id not in store._sessions

    surviving_clip_owners = {e.session_id for e in store._clips.values()}
    assert session_id not in surviving_clip_owners

    surviving_thumb_owners = {e.session_id for e in store._thumbnails.values()}
    assert session_id not in surviving_thumb_owners

    assert not output_dir.exists()

    assert not clip_path.exists()
    assert not thumb_path.exists()
    assert not orphan_in_dir.exists()
