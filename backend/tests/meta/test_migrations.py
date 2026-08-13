from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.meta.db import Base
from app.meta import models  # noqa: F401  (register tables on Base.metadata)
from app.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_head_matches_model_tables(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "meta.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("META_DB_PATH", str(db_file))
    get_settings.cache_clear()
    try:
        command.upgrade(_alembic_config(url), "head")
    finally:
        get_settings.cache_clear()

    engine = create_engine(url, future=True)
    inspector = inspect(engine)
    migrated = set(inspector.get_table_names()) - {"alembic_version"}
    assert migrated == set(Base.metadata.tables.keys())
    tag_indexes = {index["name"] for index in inspector.get_indexes("fingerprint_tags")}
    assert "uq_current_tag_per_observation" in tag_indexes


def test_upgrade_uses_configured_meta_db_path(tmp_path: Path, monkeypatch):
    configured_db = tmp_path / "configured % path" / "meta.db"
    ignored_db = tmp_path / "ignored.db"
    monkeypatch.setenv("META_DB_PATH", str(configured_db))
    get_settings.cache_clear()
    try:
        command.upgrade(_alembic_config(f"sqlite:///{ignored_db}"), "head")
    finally:
        get_settings.cache_clear()

    assert configured_db.exists()
    engine = create_engine(f"sqlite:///{configured_db}", future=True)
    migrated = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert migrated == set(Base.metadata.tables.keys())
    assert not ignored_db.exists()


def test_upgrade_from_0001_preserves_tags_and_replaces_constraint(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "upgrade" / "meta.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("META_DB_PATH", str(db_file))
    get_settings.cache_clear()
    cfg = _alembic_config(url)
    try:
        command.upgrade(cfg, "0001_initial")
        engine = create_engine(url, future=True)
        before = inspect(engine)
        assert {
            constraint["name"]
            for constraint in before.get_unique_constraints("fingerprint_tags")
        } == {"uq_tag_observation_version"}
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO fallback_observations "
                    "(id, candidate_id, source_excerpt, grade_level, observation_kind, "
                    "excluded, created_at) "
                    "VALUES ('obs-1', 'cand-1', '2/5 + 1/5', 3, "
                    "'unsupported_shape', 0, '2026-07-27 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO fingerprint_tags "
                    "(id, observation_id, fingerprint_version, fingerprint_json, "
                    "fingerprint_key, tagger_model_id, tagger_prompt_version, "
                    "is_current, created_at) "
                    "VALUES ('tag-1', 'obs-1', 1, '{}', 'k1', 'm1', 'v1', 1, "
                    "'2026-07-27 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO fingerprint_tags "
                    "(id, observation_id, fingerprint_version, fingerprint_json, "
                    "fingerprint_key, tagger_model_id, tagger_prompt_version, "
                    "is_current, created_at) "
                    "VALUES ('tag-2', 'obs-1', 2, '{}', 'k2', 'm2', 'v2', 1, "
                    "'2026-07-27 00:30:00')"
                )
            )

        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()

    engine = create_engine(url, future=True)
    after = inspect(engine)
    assert after.get_unique_constraints("fingerprint_tags") == []
    assert "uq_current_tag_per_observation" in {
        index["name"] for index in after.get_indexes("fingerprint_tags")
    }
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT id, is_current FROM fingerprint_tags ORDER BY id")
        ).all() == [("tag-1", 0), ("tag-2", 1)]
        connection.execute(
            text("UPDATE fingerprint_tags SET is_current = 0 WHERE id = 'tag-2'")
        )
        connection.execute(
            text(
                "INSERT INTO fingerprint_tags "
                "(id, observation_id, fingerprint_version, fingerprint_json, "
                "fingerprint_key, tagger_model_id, tagger_prompt_version, "
                "is_current, created_at) "
                "VALUES ('tag-3', 'obs-1', 1, '{}', 'k1', 'm3', 'v3', 1, "
                "'2026-07-27 01:00:00')"
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO fingerprint_tags "
                "(id, observation_id, fingerprint_version, fingerprint_json, "
                "fingerprint_key, tagger_model_id, tagger_prompt_version, "
                "is_current, created_at) "
                "VALUES ('tag-4', 'obs-1', 3, '{}', 'k1', 'm4', 'v4', 1, "
                "'2026-07-27 02:00:00')"
            )
        )


def test_0002_downgrade_is_explicitly_irreversible(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "downgrade" / "meta.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("META_DB_PATH", str(db_file))
    get_settings.cache_clear()
    cfg = _alembic_config(url)
    try:
        command.upgrade(cfg, "0002_retag_history")
        with pytest.raises(RuntimeError, match="append-only retag history"):
            command.downgrade(cfg, "0001_initial")
    finally:
        get_settings.cache_clear()


def test_head_uses_dedicated_v3_draft_document_columns(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "v3" / "meta.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("META_DB_PATH", str(db_file))
    get_settings.cache_clear()
    cfg = _alembic_config(url)
    try:
        command.upgrade(cfg, "head")
        engine = create_engine(url, future=True)
        columns = {column["name"] for column in inspect(engine).get_columns("template_drafts")}
        assert {"teaching_plan_json", "scene_program_json", "quality_report_json"} <= columns
        assert "animation_document_json" not in columns
    finally:
        get_settings.cache_clear()


def test_0006_downgrade_is_explicitly_irreversible(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "v3-downgrade" / "meta.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("META_DB_PATH", str(db_file))
    get_settings.cache_clear()
    cfg = _alembic_config(url)
    try:
        # Pinned to 0006 rather than head: a later irreversible migration would
        # otherwise raise first and this test would pass for the wrong reason.
        command.upgrade(cfg, "0006_meta_template_v3")
        with pytest.raises(RuntimeError, match="0006_meta_template_v3 is intentionally irreversible"):
            command.downgrade(cfg, "0005_approval_gate")
    finally:
        get_settings.cache_clear()


def _insert_enabled_version(
    connection, *, version_id: str, fingerprint_key: str, template_name: str, owner: str | None
) -> None:
    connection.execute(
        text(
            "INSERT INTO template_versions "
            "(id, fingerprint_key, template_name, artifact_hash, status, "
            "owner_session_id, created_at, updated_at) "
            "VALUES (:id, :key, :name, 'hash', 'enabled', :owner, "
            "'2026-08-04 00:00:00', '2026-08-04 00:00:00')"
        ),
        {"id": version_id, "key": fingerprint_key, "name": template_name, "owner": owner},
    )


def _migrate_to_head_with_a_shared_version(tmp_path: Path, monkeypatch, name: str):
    """Upgrade 0006 -> head with one pre-existing shared enabled version."""
    db_file = tmp_path / name / "meta.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("META_DB_PATH", str(db_file))
    get_settings.cache_clear()
    cfg = _alembic_config(url)
    try:
        command.upgrade(cfg, "0006_meta_template_v3")
        engine = create_engine(url, future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO template_versions "
                    "(id, fingerprint_key, template_name, artifact_hash, status, "
                    "created_at, updated_at) "
                    "VALUES ('v-shared', 'k1', 'pair_elimination', 'hash', 'enabled', "
                    "'2026-08-04 00:00:00', '2026-08-04 00:00:00')"
                )
            )
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()
    return create_engine(url, future=True)


def test_0007_preserves_existing_versions_as_shared(tmp_path: Path, monkeypatch):
    engine = _migrate_to_head_with_a_shared_version(tmp_path, monkeypatch, "own-preserve")

    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT id, owner_session_id FROM template_versions")
        ).all() == [("v-shared", None)]


def test_0007_lets_two_owners_hold_one_fingerprint(tmp_path: Path, monkeypatch):
    engine = _migrate_to_head_with_a_shared_version(tmp_path, monkeypatch, "own-fingerprint")

    with engine.begin() as connection:
        _insert_enabled_version(
            connection, version_id="v-a", fingerprint_key="k1",
            template_name="pair_elimination_a", owner="session-a",
        )
        _insert_enabled_version(
            connection, version_id="v-b", fingerprint_key="k1",
            template_name="pair_elimination_b", owner="session-b",
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_enabled_version(
            connection, version_id="v-a2", fingerprint_key="k1",
            template_name="pair_elimination_a2", owner="session-a",
        )


def test_0007_lets_two_owners_reuse_one_template_name(tmp_path: Path, monkeypatch):
    engine = _migrate_to_head_with_a_shared_version(tmp_path, monkeypatch, "own-name")

    with engine.begin() as connection:
        _insert_enabled_version(
            connection, version_id="v-a", fingerprint_key="k-a",
            template_name="boundary_trace", owner="session-a",
        )
        _insert_enabled_version(
            connection, version_id="v-b", fingerprint_key="k-b",
            template_name="boundary_trace", owner="session-b",
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_enabled_version(
            connection, version_id="v-a2", fingerprint_key="k-c",
            template_name="boundary_trace", owner="session-a",
        )


def test_0007_records_the_owner_of_a_generation_job(tmp_path: Path, monkeypatch):
    engine = _migrate_to_head_with_a_shared_version(tmp_path, monkeypatch, "own-job")

    columns = {column["name"] for column in inspect(engine).get_columns("generation_jobs")}
    assert "owner_session_id" in columns


def test_0007_downgrade_is_explicitly_irreversible(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "own-downgrade" / "meta.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("META_DB_PATH", str(db_file))
    get_settings.cache_clear()
    cfg = _alembic_config(url)
    try:
        # Pinned to 0007, not head: a later irreversible migration would raise
        # first and this test would pass for the wrong reason.
        command.upgrade(cfg, "0007_template_ownership")
        with pytest.raises(
            RuntimeError, match="0007_template_ownership is intentionally irreversible"
        ):
            command.downgrade(cfg, "0006_meta_template_v3")
    finally:
        get_settings.cache_clear()


def test_0007_still_allows_only_one_shared_version_per_fingerprint(tmp_path: Path, monkeypatch):
    """NULL owners must still collide with each other.

    SQLite treats NULLs as distinct in a UNIQUE index, so indexing
    `owner_session_id` directly would silently drop the single-shared-version
    invariant 0005 established. The index is on coalesce(owner_session_id, '')
    for exactly this reason.
    """
    engine = _migrate_to_head_with_a_shared_version(tmp_path, monkeypatch, "own-shared-dup")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_enabled_version(
            connection, version_id="v-shared-2", fingerprint_key="k1",
            template_name="pair_elimination_two", owner=None,
        )


def test_0007_still_allows_only_one_shared_version_per_template_name(tmp_path: Path, monkeypatch):
    engine = _migrate_to_head_with_a_shared_version(tmp_path, monkeypatch, "own-shared-name-dup")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_enabled_version(
            connection, version_id="v-shared-2", fingerprint_key="k-other",
            template_name="pair_elimination", owner=None,
        )


def test_0008_scopes_the_active_job_index_to_the_owner(tmp_path: Path, monkeypatch):
    engine = _migrate_to_head_with_a_shared_version(tmp_path, monkeypatch, "own-active-job")

    def insert_active(connection, *, job_id, owner):
        connection.execute(
            text(
                "INSERT INTO generation_jobs "
                "(id, fingerprint_key, fingerprint_version, fingerprint_json, "
                "trigger_observation_ids, status, owner_session_id, attempt, "
                "created_at, updated_at) "
                "VALUES (:id, 'k-job', 1, '{}', '[]', 'queued', :owner, 0, "
                "'2026-08-04 00:00:00', '2026-08-04 00:00:00')"
            ),
            {"id": job_id, "owner": owner},
        )

    with engine.begin() as connection:
        insert_active(connection, job_id="job-a", owner="session-a")
        insert_active(connection, job_id="job-b", owner="session-b")
        insert_active(connection, job_id="job-shared", owner=None)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_active(connection, job_id="job-a2", owner="session-a")


def test_0008_still_allows_only_one_ownerless_active_job(tmp_path: Path, monkeypatch):
    """Two NULL owners must still collide, as they did before 0008."""
    engine = _migrate_to_head_with_a_shared_version(tmp_path, monkeypatch, "own-active-null")

    def insert_active(connection, job_id):
        connection.execute(
            text(
                "INSERT INTO generation_jobs "
                "(id, fingerprint_key, fingerprint_version, fingerprint_json, "
                "trigger_observation_ids, status, attempt, created_at, updated_at) "
                "VALUES (:id, 'k-null', 1, '{}', '[]', 'queued', 0, "
                "'2026-08-04 00:00:00', '2026-08-04 00:00:00')"
            ),
            {"id": job_id},
        )

    with engine.begin() as connection:
        insert_active(connection, "job-1")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_active(connection, "job-2")


def test_0008_downgrade_is_explicitly_irreversible(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "active-job-downgrade" / "meta.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("META_DB_PATH", str(db_file))
    get_settings.cache_clear()
    cfg = _alembic_config(url)
    try:
        # Pinned to 0008 rather than head for the same reason 0006's test is:
        # 0009 is now head and its own guard would raise first.
        command.upgrade(cfg, "0008_owner_scoped_active_job")
        with pytest.raises(
            RuntimeError, match="0008_owner_scoped_active_job is intentionally irreversible"
        ):
            command.downgrade(cfg, "0007_template_ownership")
    finally:
        get_settings.cache_clear()


def test_0009_declares_a_fixture_id_wide_enough_for_the_derived_id(tmp_path: Path, monkeypatch):
    """Guards the ORM declaration, which is what 0009 brings the DB in line with.

    ``drafts.py`` derives fixture ids as f"{draft_id}-fixture-{index}" -- 42
    chars for a 32-char draft id. This asserts against ``Base.metadata`` rather
    than a migrated database on purpose: the migration harness here is
    SQLite-only, SQLite does not enforce VARCHAR lengths, and 0009 is therefore
    a deliberate no-op on it. Only Postgres rejected the long id, so a
    SQLite-backed schema assertion could not fail either way.
    """
    del tmp_path, monkeypatch
    fixture_id = f"{'c108d4a6193f4a8c87b0a0da35cd236e'}-fixture-0"
    declared = Base.metadata.tables["template_draft_fixtures"].columns["id"].type.length
    assert len(fixture_id) == 42
    assert declared >= len(fixture_id)


def test_0009_downgrade_is_explicitly_irreversible(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "fixture-id-downgrade" / "meta.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("META_DB_PATH", str(db_file))
    get_settings.cache_clear()
    cfg = _alembic_config(url)
    try:
        command.upgrade(cfg, "head")
        with pytest.raises(RuntimeError, match="0009_widen_fixture_id is intentionally irreversible"):
            command.downgrade(cfg, "0008_owner_scoped_active_job")
    finally:
        get_settings.cache_clear()
