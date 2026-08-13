from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _resolve_url() -> str:
    """Return the effective SQLAlchemy URL.

    Precedence: settings.database_url (Docker/production) → sqlite at
    settings.meta_db_path (local dev, tests).
    """
    settings = get_settings()
    if settings.database_url:
        return settings.database_url
    db_path = Path(settings.meta_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


def make_engine(url_or_path: str | Path) -> Engine:
    # Back-compat: callers still pass a Path for sqlite (tests).
    if isinstance(url_or_path, Path):
        url_or_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{url_or_path}"
    else:
        url = str(url_or_path)

    is_sqlite = make_url(url).drivername.startswith("sqlite")
    kwargs: dict = {"future": True}
    if is_sqlite:
        kwargs["connect_args"] = {"timeout": 30}
    else:
        # Postgres: modest pool sized for a single-worker demo backend + one worker.
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 5

    engine = create_engine(url, **kwargs)

    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


@lru_cache
def get_engine() -> Engine:
    return make_engine(_resolve_url())


def create_all(engine: Engine) -> None:
    # Import models so their tables register on Base.metadata before create_all.
    from app.meta import models  # noqa: F401

    Base.metadata.create_all(engine)


@contextmanager
def meta_session() -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(), future=True, expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
