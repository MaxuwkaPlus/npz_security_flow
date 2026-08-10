import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.application.configuration import publish_installation, publish_scenario, publish_scoring_policy
from app.infrastructure.db.engine import Database
from app.infrastructure.seed.installation import build_installation_spec
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


@dataclass(frozen=True)
class SeededConfiguration:
    installation_version_id: str
    scenario_version_id: str
    scoring_policy_version_id: str
    level_ids: dict[int, str]


@pytest.fixture
async def configuration(database: Database) -> SeededConfiguration:
    """Опубликованная демонстрационная конфигурация — предпосылка любой сессии."""

    async with database.session_factory() as session, session.begin():
        installation = await publish_installation(session, build_installation_spec())
        scenario = await publish_scenario(session, installation)
        policy = await publish_scoring_policy(session)
        return SeededConfiguration(
            installation_version_id=installation.id,
            scenario_version_id=scenario.id,
            scoring_policy_version_id=policy.id,
            level_ids={level.level_no: level.id for level in scenario.levels},
        )
