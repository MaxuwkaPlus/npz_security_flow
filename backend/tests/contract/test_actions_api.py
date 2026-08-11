from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.application.tick import run_tick
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import OperatorAction, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration


async def running_session(client: AsyncClient, configuration: SeededConfiguration) -> str:
    created = await client.post(
        "/api/v1/sessions",
        json={
            "request_id": str(uuid4()),
            "operator_id": "operator-1",
            "scenario_version_id": configuration.scenario_version_id,
            "level_no": 1,
            "random_seed": 42,
        },
    )
    session_id: str = created.json()["id"]
    await client.post(f"/api/v1/sessions/{session_id}/start", json={"request_id": str(uuid4())})
    return session_id


async def submit(client: AsyncClient, session_id: str, **payload: Any) -> Any:
    body = {"request_id": str(uuid4())} | payload
    return await client.post(f"/api/v1/sessions/{session_id}/actions", json=body)


async def tick(database: Database, session_id: str, times: int = 1) -> None:
    for _ in range(times):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)


async def test_allowed_command_is_accepted(client: AsyncClient, configuration: SeededConfiguration) -> None:
    session_id = await running_session(client, configuration)

    response = await submit(client, session_id, action_type="start_feed_pump", target_code="N-1")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["rejection_reason"] is None


async def test_accepted_command_is_applied_by_the_next_tick(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    session_id = await running_session(client, configuration)
    await submit(client, session_id, action_type="start_feed_pump", target_code="N-1")

    await tick(database, session_id, times=30)

    async with database.session_factory() as session:
        action = await session.scalar(select(OperatorAction))
        stored = await session.get(TrainingSession, session_id)
    assert action is not None and stored is not None
    assert action.status == "applied"
    assert action.before_state_json["branch_1_flow_tph"] == 0.0
    assert action.after_state_json["feed_pump_state"] == "RUNNING"
    assert stored.runtime_state_json["plant"]["branches"][0]["flow_tph"] > 20.0


async def test_valve_command_changes_branch_flow(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    session_id = await running_session(client, configuration)
    await submit(client, session_id, action_type="start_feed_pump", target_code="N-1")
    await tick(database, session_id, times=300)

    await submit(
        client,
        session_id,
        action_type="set_control_valve",
        target_code="FRC-405",
        value={"opening_pct": 40.0},
    )
    await tick(database, session_id, times=300)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
    assert stored is not None
    branches = stored.runtime_state_json["plant"]["branches"]
    assert branches[1]["flow_tph"] < 45.0
    assert branches[0]["flow_tph"] > 95.0


async def test_unknown_action_type_is_rejected_and_recorded(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)

    response = await submit(client, session_id, action_type="open_secret_bypass", target_code="N-1")

    assert response.status_code == 202
    assert response.json()["status"] == "rejected"
    assert response.json()["rejection_reason"] == "unknown_action_type"


async def test_target_outside_allowlist_is_rejected(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)

    response = await submit(client, session_id, action_type="set_control_valve", target_code="K-2")

    assert response.json()["rejection_reason"] == "target_not_allowed"


async def test_value_outside_range_is_rejected(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)

    response = await submit(
        client,
        session_id,
        action_type="set_control_valve",
        target_code="FRC-404",
        value={"opening_pct": 140.0},
    )

    assert response.json()["rejection_reason"] == "value_out_of_range"


async def test_rejected_command_does_not_change_the_plant(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    session_id = await running_session(client, configuration)

    await submit(client, session_id, action_type="open_secret_bypass", target_code="N-1")
    await tick(database, session_id, times=10)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
    assert stored is not None
    assert stored.runtime_state_json["plant"]["pump_running"] is False


async def test_repeated_request_id_does_not_create_second_action(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    session_id = await running_session(client, configuration)
    request_id = str(uuid4())
    payload = {"request_id": request_id, "action_type": "start_feed_pump", "target_code": "N-1"}

    first = await client.post(f"/api/v1/sessions/{session_id}/actions", json=payload)
    second = await client.post(f"/api/v1/sessions/{session_id}/actions", json=payload)

    assert first.json() == second.json()
    async with database.session_factory() as session:
        actions = (await session.scalars(select(OperatorAction))).all()
    assert len(actions) == 1


async def test_command_on_paused_session_is_refused(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)
    await client.post(f"/api/v1/sessions/{session_id}/pause", json={"request_id": str(uuid4())})

    response = await submit(client, session_id, action_type="start_feed_pump", target_code="N-1")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SESSION_NOT_RUNNING"
