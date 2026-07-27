from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import URL, engine_from_config, pool

from app.config import get_settings
from app.meta.db import Base
from app.meta import models  # noqa: F401  (register tables on Base.metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_path = Path(get_settings().meta_db_path)
db_path.parent.mkdir(parents=True, exist_ok=True)
database_url = URL.create("sqlite", database=str(db_path)).render_as_string(
    hide_password=False
)
# ConfigParser treats percent signs as interpolation markers.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
