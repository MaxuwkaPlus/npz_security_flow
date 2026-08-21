import asyncio
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.application.configuration import publish_installation, publish_scenario, publish_scoring_policy
from app.domain.rbac import Role
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import User, UserRoleAssignment
from app.infrastructure.runtime.session_runner import SessionRunner
from app.infrastructure.security.passwords import hash_password
from app.infrastructure.seed.installation import build_installation_spec
from app.main import create_app
from app.settings import Settings
from tests.support import alembic_config


@pytest.fixture
async def settings(tmp_path: Path) -> Settings:
    """Файловая SQLite во временном каталоге со схемой, накатанной миграциями."""

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        log_level="WARNING",
        # Фоновая симуляция в тестах молчит: шаги делает сам тест, иначе два писателя
        # одной сессии наталкиваются на optimistic locking.
        simulation_speed_factor=0.001,
    )
    # env.py вызывает asyncio.run, поэтому миграции запускаются в отдельном потоке.
    await asyncio.to_thread(command.upgrade, alembic_config(settings.database_url), "head")
    return settings


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings)
    yield database
    await database.dispose()


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    # ASGITransport не выполняет lifespan, поэтому фоновые задачи и пул соединений
    # гасит сама фикстура. Без dispose каждый тест оставлял бы открытый engine:
    # соединения копятся до конца прогона и мешают нагрузочным тестам.
    application = create_app(settings)
    yield application
    runner: SessionRunner = application.state.session_runner
    await runner.stop_all()
    app_database: Database = application.state.database
    await app_database.dispose()


# Учётные записи тестов. `operator-1` намеренно совмещает две роли: тесты
# технологической части проверяют расчёт, тревоги и оценку, и не должны каждый раз
# разыгрывать передачу сессии от инструктора оператору. Разделение прав проверяется
# отдельно, в tests/contract/test_access_api.py.
TEST_ACCOUNTS: dict[str, tuple[Role, ...]] = {
    "operator-1": (Role.TRAINEE, Role.INSTRUCTOR),
    "operator-2": (Role.TRAINEE,),
    "instructor-1": (Role.INSTRUCTOR,),
    "expert-1": (Role.EXPERT,),
    "iso-1": (Role.SECURITY_ADMIN,),
}


@pytest.fixture(scope="session")
def test_password() -> str:
    """Пароль тестовых учётных записей генерируется, а не хранится в репозитории."""

    return secrets.token_urlsafe(16)


@pytest.fixture
async def accounts(database: Database, test_password: str) -> dict[str, str]:
    """Заводит тестовые учётные записи и возвращает соответствие «логин — идентификатор»."""

    password_hash = hash_password(test_password)
    created: dict[str, str] = {}
    async with database.session_factory() as session, session.begin():
        for username, roles in TEST_ACCOUNTS.items():
            user = User(username=username, display_name=username, password_hash=password_hash)
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(UserRoleAssignment(user_id=user.id, role=role.value))
            created[username] = user.id
    return created


@pytest.fixture
async def anonymous_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Клиент без токена: нужен, чтобы проверять отказ неаутентифицированному запросу."""

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


async def login_as(app: FastAPI, username: str, password: str) -> AsyncClient:
    """Клиент с токеном указанной учётной записи.

    Закрывать его должен вызывающий: первый запрос уже открыл клиента, и повторный
    вход в `async with` httpx запрещает.
    """

    transport = ASGITransport(app=app)
    http_client = AsyncClient(transport=transport, base_url="http://test")
    response = await http_client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    http_client.headers["authorization"] = f"Bearer {response.json()['access_token']}"
    return http_client


@pytest.fixture
async def client(app: FastAPI, accounts: dict[str, str], test_password: str) -> AsyncIterator[AsyncClient]:
    """Клиент по умолчанию: обучаемый `operator-1` с правами инструктора."""

    http_client = await login_as(app, "operator-1", test_password)
    try:
        yield http_client
    finally:
        await http_client.aclose()


@pytest.fixture
async def trainee_client(
    app: FastAPI, accounts: dict[str, str], test_password: str
) -> AsyncIterator[AsyncClient]:
    """Чистый обучаемый `operator-2` без инструкторских прав."""

    http_client = await login_as(app, "operator-2", test_password)
    try:
        yield http_client
    finally:
        await http_client.aclose()


@pytest.fixture
async def instructor_client(
    app: FastAPI, accounts: dict[str, str], test_password: str
) -> AsyncIterator[AsyncClient]:
    http_client = await login_as(app, "instructor-1", test_password)
    try:
        yield http_client
    finally:
        await http_client.aclose()


@pytest.fixture
async def expert_client(
    app: FastAPI, accounts: dict[str, str], test_password: str
) -> AsyncIterator[AsyncClient]:
    http_client = await login_as(app, "expert-1", test_password)
    try:
        yield http_client
    finally:
        await http_client.aclose()


@pytest.fixture
async def security_client(
    app: FastAPI, accounts: dict[str, str], test_password: str
) -> AsyncIterator[AsyncClient]:
    http_client = await login_as(app, "iso-1", test_password)
    try:
        yield http_client
    finally:
        await http_client.aclose()


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
