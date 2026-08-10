from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Файловая SQLite во временном каталоге: in-memory не проверяет блокировки и миграции."""

    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db", log_level="WARNING")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
