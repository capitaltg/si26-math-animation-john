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


# --- registry cleanup / quota / sweep ---------------------------------------


def _make_session_with_file(store, tmp_path, name: str, size: int = 8):
    session = store.create([_candidate("x")])
    p = session.output_dir / name
    p.write_bytes(b"y" * size)
    return session, p


def test_clip_eviction_deletes_file(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_clips=2)
    _, a = _make_session_with_file(store, tmp_path, "a.mp4")
    _, b = _make_session_with_file(store, tmp_path, "b.mp4")
    _, c = _make_session_with_file(store, tmp_path, "c.mp4")

    store.register_clip(a)
    store.register_clip(b)
    store.register_clip(c)

    assert not a.exists(), "evicted clip file must be removed from disk"
    assert b.exists() and c.exists()


def test_thumbnail_eviction_deletes_file(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_thumbnails=2)
    _, a = _make_session_with_file(store, tmp_path, "a.png")
    _, b = _make_session_with_file(store, tmp_path, "b.png")
    _, c = _make_session_with_file(store, tmp_path, "c.png")

    store.register_thumbnail(a)
    store.register_thumbnail(b)
    store.register_thumbnail(c)

    assert not a.exists()
    assert b.exists() and c.exists()


def test_per_session_byte_quota_evicts_oldest_in_session(tmp_path):
    from app.session import SessionStore

    # 30 bytes total: two 12-byte clips fit, third pushes us over.
    store = SessionStore(tmp_path, max_bytes_per_session=30)
    session = store.create([_candidate("x")])
    a = session.output_dir / "a.mp4"; a.write_bytes(b"a" * 12)
    b = session.output_dir / "b.mp4"; b.write_bytes(b"b" * 12)
    c = session.output_dir / "c.mp4"; c.write_bytes(b"c" * 12)

    aid = store.register_clip(a, session_id=session.session_id)
    store.register_clip(b, session_id=session.session_id)
    store.register_clip(c, session_id=session.session_id)

    assert store.get_clip(aid) is None
    assert not a.exists(), "byte-quota eviction must remove file too"
    assert b.exists() and c.exists()


def test_ttl_evicts_expired_entry_on_next_register(tmp_path, monkeypatch):
    from app import session as session_mod
    from app.session import SessionStore

    fake_now = [1000.0]
    monkeypatch.setattr(session_mod.time, "time", lambda: fake_now[0])

    store = SessionStore(tmp_path, ttl_seconds=100.0)
    session = store.create([_candidate("x")])
    old = session.output_dir / "old.mp4"; old.write_bytes(b"z")
    new = session.output_dir / "new.mp4"; new.write_bytes(b"z")

    old_id = store.register_clip(old, session_id=session.session_id)
    fake_now[0] += 200.0  # past TTL
    store.register_clip(new, session_id=session.session_id)

    assert store.get_clip(old_id) is None
    assert not old.exists()


def test_reserve_returns_path_in_session_dir_and_marks_in_progress(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([_candidate("x")])

    reserved = store.reserve(session, suffix=".mp4")

    assert reserved.parent == session.output_dir
    assert reserved.suffix == ".mp4"
    assert reserved in store.reserved_paths()


def test_abort_deletes_partial_file_and_unmarks(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([_candidate("x")])
    reserved = store.reserve(session)
    reserved.write_bytes(b"partial")

    store.abort(reserved)

    assert not reserved.exists()
    assert reserved not in store.reserved_paths()


def test_register_clip_after_reserve_unmarks(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([_candidate("x")])
    reserved = store.reserve(session)
    reserved.write_bytes(b"final")

    cid = store.register_clip(reserved, session_id=session.session_id)

    assert store.get_clip(cid) == reserved
    assert reserved not in store.reserved_paths()


def test_sweep_orphans_deletes_unregistered_files(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([_candidate("x")])
    orphan = session.output_dir / "orphan.mp4"; orphan.write_bytes(b"z")

    store.sweep_orphans()

    assert not orphan.exists()


def test_sweep_orphans_skips_reserved_paths(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([_candidate("x")])
    reserved = store.reserve(session)
    reserved.write_bytes(b"in-progress")

    store.sweep_orphans()

    assert reserved.exists(), "sweep must not touch a path a writer has reserved"


def test_sweep_orphans_skips_registered_paths(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path)
    session = store.create([_candidate("x")])
    kept = session.output_dir / "kept.mp4"; kept.write_bytes(b"z")
    store.register_clip(kept, session_id=session.session_id)

    store.sweep_orphans()

    assert kept.exists()


def test_eviction_keeps_file_when_a_newer_entry_still_points_at_it(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_thumbnails=1)
    session = store.create([_candidate("x")])
    thumb = session.output_dir / "t.png"; thumb.write_bytes(b"z")

    store.register_thumbnail(thumb)
    newest_id = store.register_thumbnail(thumb)  # evicts the first row

    assert thumb.exists(), "eviction must not delete a path still owned by another entry"
    assert store.get_thumbnail(newest_id) == thumb


def test_eviction_keeps_file_when_a_reservation_still_holds_it(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_clips=1)
    session = store.create([_candidate("x")])
    p = session.output_dir / "clip.mp4"; p.write_bytes(b"z")

    store.register_clip(p, session_id=session.session_id)
    # Same path is now reserved for a re-render in flight; eviction of the
    # first entry must not blow away the writer's target.
    with store._lock:
        store._reserved.add(p)
    q = session.output_dir / "other.mp4"; q.write_bytes(b"z")
    store.register_clip(q, session_id=session.session_id)  # evicts first entry

    assert p.exists()


def test_session_thumbnails_evicted_when_session_evicted(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_sessions=1)
    first = store.create([_candidate("a")])
    thumb = first.output_dir / "t.png"; thumb.write_bytes(b"z")
    tid = store.register_thumbnail(thumb, session_id=first.session_id)

    store.create([_candidate("b")])  # evicts first

    assert store.get_thumbnail(tid) is None


def test_session_eviction_purges_its_registry_entries(tmp_path):
    from app.session import SessionStore

    store = SessionStore(tmp_path, max_sessions=1)
    first = store.create([_candidate("a")])
    p = first.output_dir / "a.mp4"; p.write_bytes(b"z")
    cid = store.register_clip(p, session_id=first.session_id)

    store.create([_candidate("b")])  # evicts first

    assert store.get_clip(cid) is None, (
        "clip entries pointing into a rmtree'd session dir must be dropped"
    )
