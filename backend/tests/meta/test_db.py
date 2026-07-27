from pathlib import Path

from sqlalchemy import text

from app.meta import db


def test_make_engine_sets_sqlite_pragmas(tmp_path: Path):
    engine = db.make_engine(tmp_path / "meta.db")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"


def test_meta_session_commits_and_rolls_back(tmp_path: Path, monkeypatch):
    engine = db.make_engine(tmp_path / "meta.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)"))
    monkeypatch.setattr(db, "get_engine", lambda: engine)

    with db.meta_session() as session:
        session.execute(text("INSERT INTO t (v) VALUES (1)"))
    with db.meta_session() as session:
        assert session.execute(text("SELECT count(*) FROM t")).scalar() == 1

    try:
        with db.meta_session() as session:
            session.execute(text("INSERT INTO t (v) VALUES (2)"))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with db.meta_session() as session:
        assert session.execute(text("SELECT count(*) FROM t")).scalar() == 1
