import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.infrastructure.db.engine import Database
from app.main import create_app
from app.settings import Settings
from tests.support import alembic_config


@pytest.fixture
async def settings(tmp_path: Path) -> Settings:
    """Файловая SQLite во временном каталоге со схемой, накатанной миграциями."""

    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db", log_level="WARNING")
    # env.py вызывает asyncio.run, поэтому миграции запускаются в отдельном потоке.
    await asyncio.to_thread(command.upgrade, alembic_config(settings.database_url), "head")
    return settings


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings)
    yield database
    await database.dispose()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
