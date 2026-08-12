import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.infrastructure.db.engine import apply_sqlite_pragmas, ensure_sqlite_directory
from app.infrastructure.db.models import Base
from app.infrastructure.db.types import UtcDateTime
from app.settings import Settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = Settings()
# URL из alembic.ini имеет приоритет: так тесты подставляют временную файловую БД.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Пользовательские типы пишем их SQL-эквивалентом, чтобы миграция не зависела от кода приложения."""

    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime()"
    return False


def _configure(**kwargs: object) -> None:
    # render_as_batch обязателен: SQLite не поддерживает большинство ALTER TABLE напрямую.
    context.configure(
        target_metadata=target_metadata,
        render_as_batch=True,
        render_item=render_item,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    ensure_sqlite_directory(config.get_main_option("sqlalchemy.url") or "")
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    apply_sqlite_pragmas(connectable.sync_engine, settings.sqlite_busy_timeout_ms)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
