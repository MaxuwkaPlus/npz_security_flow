from sqlalchemy import text

from app.infrastructure.db.engine import Database
from app.settings import Settings


async def test_working_connection_enables_foreign_keys_and_wal(settings: Settings) -> None:
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            foreign_keys = await session.scalar(text("PRAGMA foreign_keys"))
            journal_mode = await session.scalar(text("PRAGMA journal_mode"))
            busy_timeout = await session.scalar(text("PRAGMA busy_timeout"))
    finally:
        await database.dispose()

    assert foreign_keys == 1
    assert journal_mode == "wal"
    assert busy_timeout == settings.sqlite_busy_timeout_ms
