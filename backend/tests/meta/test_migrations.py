from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.meta.db import Base
from app.meta import models  # noqa: F401  (register tables on Base.metadata)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_head_matches_model_tables(tmp_path: Path):
    db_file = tmp_path / "meta.db"
    url = f"sqlite:///{db_file}"
    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url, future=True)
    migrated = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert migrated == set(Base.metadata.tables.keys())
