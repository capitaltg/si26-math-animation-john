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
        command.upgrade(cfg, "head")
        with pytest.raises(RuntimeError, match="append-only retag history"):
            command.downgrade(cfg, "0001_initial")
    finally:
        get_settings.cache_clear()
