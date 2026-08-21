"""Контракт WebSocket-канала.

Тесты синхронные: `TestClient` поднимает приложение вместе с lifespan и умеет
подключаться по WebSocket, чего не делает httpx-транспорт остальных контрактных тестов.
"""

import asyncio
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.v1.realtime import CLOSE_FORBIDDEN, CLOSE_UNAUTHENTICATED
from app.application.configuration import publish_installation, publish_scenario, publish_scoring_policy
from app.domain.rbac import Role
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import User, UserRoleAssignment
from app.infrastructure.security.passwords import hash_password
from app.infrastructure.seed.installation import build_installation_spec
from app.main import create_app
from app.settings import Settings
from tests.support import alembic_config

# Симуляция идёт в 100 раз быстрее реального времени, иначе тест ждал бы секунды.
SPEED_FACTOR = 100.0
PASSWORD = secrets.token_urlsafe(16)


async def seed(settings: Settings) -> None:
    database = Database(settings)
    try:
        async with database.session_factory() as session, session.begin():
            installation = await publish_installation(session, build_installation_spec())
            await publish_scenario(session, installation)
            await publish_scoring_policy(session)
            # Канал закрыт так же, как REST: без учётной записи подключиться нельзя.
            user = User(
                username="operator-1", display_name="operator-1", password_hash=hash_password(PASSWORD)
            )
            session.add(user)
            await session.flush()
            session.add(UserRoleAssignment(user_id=user.id, role=Role.TRAINEE.value))
            session.add(UserRoleAssignment(user_id=user.id, role=Role.INSTRUCTOR.value))
            other = User(
                username="operator-2", display_name="operator-2", password_hash=hash_password(PASSWORD)
            )
            session.add(other)
            await session.flush()
            session.add(UserRoleAssignment(user_id=other.id, role=Role.TRAINEE.value))
    finally:
        await database.dispose()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/ws.db",
        log_level="WARNING",
        simulation_speed_factor=SPEED_FACTOR,
    )
    command.upgrade(alembic_config(settings.database_url), "head")
    asyncio.run(seed(settings))
    with TestClient(create_app(settings)) as test_client:
        response = test_client.post(
            "/api/v1/auth/login", json={"username": "operator-1", "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        test_client.headers["authorization"] = f"Bearer {response.json()['access_token']}"
        yield test_client


def start_session(client: TestClient) -> str:
    scenario_id = client.get("/api/v1/scenarios").json()[0]["id"]
    created = client.post(
        "/api/v1/sessions",
        json={
            "request_id": str(uuid4()),
            "operator_id": "operator-1",
            "scenario_version_id": scenario_id,
            "level_no": 1,
            "random_seed": 42,
        },
    )
    session_id: str = created.json()["id"]
    client.post(f"/api/v1/sessions/{session_id}/start", json={"request_id": str(uuid4())})
    return session_id


def ws_url(client: TestClient, session_id: str, **params: Any) -> str:
    """Адрес канала с токеном: браузерный WebSocket не умеет задавать заголовки."""

    token = client.headers["authorization"].removeprefix("Bearer ")
    return f"/ws/v1/sessions/{session_id}?{urlencode({'token': token, **params})}"


def receive_until(websocket: Any, message_type: str, limit: int = 60) -> dict[str, Any]:
    for _ in range(limit):
        message: dict[str, Any] = websocket.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"сообщение {message_type} не пришло за {limit} сообщений")


def test_client_receives_missed_events_from_the_journal(client: TestClient) -> None:
    session_id = start_session(client)

    with client.websocket_connect(ws_url(client, session_id)) as websocket:
        first = websocket.receive_json()

    assert first["schema_version"] == 1
    assert first["session_id"] == session_id
    assert first["sequence_no"] == 1
    assert first["type"] == "session_state"
    assert first["payload"]["event_type"] == "session_created"


def test_client_can_continue_from_last_known_sequence_no(client: TestClient) -> None:
    session_id = start_session(client)

    with client.websocket_connect(ws_url(client, session_id, last_sequence_no=2)) as websocket:
        message = websocket.receive_json()

    assert message["sequence_no"] == 3
    assert message["payload"]["event_type"] == "session_started"


def test_live_snapshots_carry_visible_values_only(client: TestClient) -> None:
    session_id = start_session(client)

    with client.websocket_connect(ws_url(client, session_id)) as websocket:
        snapshot = receive_until(websocket, "process_snapshot")

    assert snapshot["sim_time_ms"] % 5_000 == 0
    assert "branch_1_flow_tph" in snapshot["payload"]["values"]
    assert "min_branch_flow_ratio" in snapshot["payload"]["derived"]
    # Скрытое состояние двойника в канал не уходит.
    assert "severity" not in snapshot["payload"]["values"]
    assert "severity" not in snapshot["payload"]["derived"]
    assert "internal_state" not in snapshot["payload"]


def test_operator_command_produces_action_message(client: TestClient) -> None:
    session_id = start_session(client)

    with client.websocket_connect(ws_url(client, session_id)) as websocket:
        client.post(
            f"/api/v1/sessions/{session_id}/actions",
            json={
                "request_id": str(uuid4()),
                "action_type": "start_feed_pump",
                "target_code": "N-1",
            },
        )
        message = receive_until(websocket, "action_status_changed")

    assert message["payload"]["action_type"] == "start_feed_pump"
    assert message["payload"]["event_type"] in ("action_accepted", "action_applied")


def test_sequence_numbers_arrive_without_gaps(client: TestClient) -> None:
    session_id = start_session(client)

    with client.websocket_connect(ws_url(client, session_id)) as websocket:
        numbers = [websocket.receive_json()["sequence_no"] for _ in range(6)]

    assert numbers == list(range(1, 7))


def test_channel_without_token_is_not_opened(client: TestClient) -> None:
    """Канал отдаёт обстановку на установке, поэтому закрыт так же, как REST."""

    session_id = start_session(client)

    with (
        pytest.raises(WebSocketDisconnect) as failure,
        client.websocket_connect(f"/ws/v1/sessions/{session_id}") as websocket,
    ):
        websocket.receive_json()

    # Отсутствие обязательного параметра отклоняется до проверки прав.
    assert failure.value.code in {CLOSE_UNAUTHENTICATED, 1008}


def test_foreign_session_is_not_streamed_to_another_trainee(client: TestClient) -> None:
    session_id = start_session(client)
    token = client.post("/api/v1/auth/login", json={"username": "operator-2", "password": PASSWORD}).json()[
        "access_token"
    ]

    with (
        pytest.raises(WebSocketDisconnect) as failure,
        client.websocket_connect(f"/ws/v1/sessions/{session_id}?{urlencode({'token': token})}") as websocket,
    ):
        websocket.receive_json()

    assert failure.value.code == CLOSE_FORBIDDEN
