from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import TrainingSession
from tests.conftest import SeededConfiguration


def new_request_id() -> str:
    return str(uuid4())


async def create_session(
    client: AsyncClient, configuration: SeededConfiguration, **overrides: Any
) -> dict[str, Any]:
    payload = {
        "request_id": new_request_id(),
        "operator_id": "operator-1",
        "scenario_version_id": configuration.scenario_version_id,
        "level_no": 2,
        "random_seed": 12345,
    } | overrides
    response = await client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 201, response.text
    session: dict[str, Any] = response.json()
    return session


async def command(client: AsyncClient, session_id: str, name: str, **body: Any) -> Any:
    payload = {"request_id": new_request_id()} | body
    return await client.post(f"/api/v1/sessions/{session_id}/{name}", json=payload)


async def test_created_session_is_ready_to_start(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    """Конфигурация фиксируется при создании, поэтому сессия сразу готова к запуску."""

    session = await create_session(client, configuration)

    assert session["status"] == "ready"
    assert session["sim_time_ms"] == 0
    assert session["current_stage_code"] == "precheck"
    assert session["level_no"] == 2


async def test_session_response_never_exposes_hidden_configuration(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session = await create_session(client, configuration)

    response = await client.get(f"/api/v1/sessions/{session['id']}")

    assert set(response.json()) == {
        "id",
        "operator_id",
        "instructor_id",
        "scenario_version_id",
        "level_no",
        "status",
        "sim_time_ms",
        "sequence_no",
        "current_stage_code",
        "version_no",
        "final_outcome",
    }
    for leaked in ("random_seed", "hidden", "target_branch", "pump_capacity_loss", "valve_stiction"):
        assert leaked not in response.text


async def test_lifecycle_transitions_are_applied_in_order(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session = await create_session(client, configuration)
    session_id = session["id"]

    assert (await command(client, session_id, "start")).json()["status"] == "running"
    assert (await command(client, session_id, "pause")).json()["status"] == "paused"
    assert (await command(client, session_id, "resume")).json()["status"] == "running"
    assert (await command(client, session_id, "abort")).json()["status"] == "aborted"


async def test_forbidden_transition_returns_conflict(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session = await create_session(client, configuration)

    response = await command(client, session["id"], "pause")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "SESSION_TRANSITION_NOT_ALLOWED"
    assert error["details"]["status"] == "ready"


async def test_repeated_request_id_returns_the_same_result(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session = await create_session(client, configuration)
    session_id = session["id"]
    request_id = new_request_id()
    payload = {"request_id": request_id}

    first = await client.post(f"/api/v1/sessions/{session_id}/start", json=payload)
    second = await client.post(f"/api/v1/sessions/{session_id}/start", json=payload)

    assert first.json() == second.json()
    events = (await client.get(f"/api/v1/sessions/{session_id}")).json()
    assert events["sequence_no"] == first.json()["sequence_no"]


async def test_repeated_create_request_id_does_not_create_second_session(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    request_id = new_request_id()

    first = await create_session(client, configuration, request_id=request_id)
    second = await create_session(client, configuration, request_id=request_id)

    assert first["id"] == second["id"]


async def test_stale_expected_version_is_rejected(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session = await create_session(client, configuration)
    session_id = session["id"]
    await command(client, session_id, "start")

    response = await command(client, session_id, "pause", expected_version=1)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SESSION_VERSION_MISMATCH"


@pytest.mark.parametrize("level_no", [0, 4])
async def test_unknown_level_is_rejected(
    client: AsyncClient, configuration: SeededConfiguration, level_no: int
) -> None:
    payload = {
        "request_id": new_request_id(),
        "operator_id": "operator-1",
        "scenario_version_id": configuration.scenario_version_id,
        "level_no": level_no,
    }

    response = await client.post("/api/v1/sessions", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_unknown_session_returns_stable_error_code(client: AsyncClient) -> None:
    response = await client.get("/api/v1/sessions/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


async def test_same_seed_produces_the_same_hidden_disturbance(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    """Воспроизводимость: seed однозначно задаёт скрытое возмущение."""

    first = await create_session(client, configuration, random_seed=777)
    second = await create_session(client, configuration, random_seed=777)
    other = await create_session(client, configuration, random_seed=778)

    async with database.session_factory() as session:
        hidden = {}
        for created in (first, second, other):
            stored = await session.get(TrainingSession, created["id"])
            assert stored is not None
            hidden[created["id"]] = stored.hidden_runtime_config_json["disturbance"]

    assert hidden[first["id"]] == hidden[second["id"]]
    assert hidden[first["id"]]["target_branch"] in (1, 2, 3)
    assert hidden[first["id"]] != hidden[other["id"]]
