from app.models.candidate import Candidate


def _candidate(cid):
    return Candidate(candidate_id=cid, source_excerpt="4 + 3", slide_index=0, one_line_summary="Detected: 4 + 3")


def test_create_stores_candidates_and_makes_output_dir(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([_candidate("a"), _candidate("b")])

    assert session.session_id
    assert set(session.candidates) == {"a", "b"}
    assert session.output_dir.is_dir()
    assert store.get(session.session_id) is session


def test_get_unknown_session_returns_none(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    assert store.get("nope") is None


def test_clip_registration_round_trips(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"x")

    clip_id = store.register_clip(clip_path)

    assert store.get_clip(clip_id) == clip_path
    assert store.get_clip("unknown") is None
