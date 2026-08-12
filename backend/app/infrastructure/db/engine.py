from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.settings import Settings


def sqlite_file_path(database_url: str) -> Path | None:
    """Путь к файлу БД для файловой SQLite; None для остальных URL."""

    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return None
    path = database_url[len(prefix) :]
    return None if path in ("", ":memory:") else Path(path)


def apply_sqlite_pragmas(engine: Engine, busy_timeout_ms: int) -> None:
    """PRAGMA задаются на каждом соединении: пула соединений это касается напрямую."""

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        cursor.close()


def ensure_sqlite_directory(database_url: str) -> None:
    """Каталог файловой БД создаётся до подключения: SQLite сам его не заводит."""

    file_path = sqlite_file_path(database_url)
    if file_path is not None:
        file_path.parent.mkdir(parents=True, exist_ok=True)


class Database:
    """Async engine и фабрика сессий для файловой SQLite."""

    def __init__(self, settings: Settings) -> None:
        ensure_sqlite_directory(settings.database_url)
        self.engine: AsyncEngine = create_async_engine(settings.database_url)
        apply_sqlite_pragmas(self.engine.sync_engine, settings.sqlite_busy_timeout_ms)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def dispose(self) -> None:
        await self.engine.dispose()
