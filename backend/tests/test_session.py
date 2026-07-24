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


def test_create_evicts_least_recently_used_session_and_removes_its_dir(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_sessions=2)
    first = store.create([_candidate("a")])
    store.create([_candidate("b")])
    store.create([_candidate("c")])

    assert store.get(first.session_id) is None
    assert not first.output_dir.exists()


def test_get_marks_session_as_recently_used(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_sessions=2)
    first = store.create([_candidate("a")])
    second = store.create([_candidate("b")])
    store.get(first.session_id)  # first is now most-recently-used
    store.create([_candidate("c")])  # evicts the LRU, which is now second

    assert store.get(first.session_id) is first
    assert store.get(second.session_id) is None


def test_clip_registry_is_bounded(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_clips=2)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")

    first_id = store.register_clip(clip)
    store.register_clip(clip)
    store.register_clip(clip)

    assert store.get_clip(first_id) is None


def test_new_sessions_have_independent_empty_option_caches(tmp_path):
    from app.models.scene import TemplateName
    from app.pipeline.classification import ClassificationResult, TemplateOption
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    first = store.create([_candidate("a")])
    second = store.create([_candidate("b")])

    assert first.options == {}
    assert second.options == {}

    first.options["a"] = ClassificationResult(
        options=[
            TemplateOption(
                template=TemplateName.NUMBER_LINE,
                rationale="shows one jump",
            )
        ],
        grade_level=1,
    )

    assert "a" in first.options
    assert second.options == {}


def test_session_starts_with_empty_storyboard(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([])
    assert session.scenes == {}
    assert session.scene_order == []
    assert session.scene_requested_template == {}


def test_register_and_get_thumbnail_round_trips(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    png = tmp_path / "thumb.png"
    png.write_bytes(b"fake-png")
    thumb_id = store.register_thumbnail(png)
    assert store.get_thumbnail(thumb_id) == png


def test_get_unknown_thumbnail_is_none(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    assert store.get_thumbnail("nope") is None


def test_thumbnail_registry_evicts_oldest_over_cap(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_thumbnails=2)
    first = store.register_thumbnail(tmp_path / "a.png")
    store.register_thumbnail(tmp_path / "b.png")
    store.register_thumbnail(tmp_path / "c.png")
    assert store.get_thumbnail(first) is None


def test_session_starts_with_empty_chain_members(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([])
    assert session.scene_chain_members == {}
