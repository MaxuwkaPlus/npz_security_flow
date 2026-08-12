from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.application.tick import run_tick
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import OperatorDiagnosis, TrainingSession
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


async def observe(client: AsyncClient, session_id: str, **payload: Any) -> Any:
    body = {"request_id": str(uuid4())} | payload
    return await client.post(f"/api/v1/sessions/{session_id}/observations", json=body)


async def tick(database: Database, session_id: str, times: int = 1) -> None:
    for _ in range(times):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)


async def test_observation_is_recorded(client: AsyncClient, configuration: SeededConfiguration) -> None:
    session_id = await running_session(client, configuration)

    response = await observe(
        client, session_id, observation_type="inspect_equipment", target_code="FEED-SYSTEM"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["observation_type"] == "inspect_equipment"
    assert body["sequence_no"] > 0


async def test_unknown_observation_type_is_rejected(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)

    response = await observe(client, session_id, observation_type="peek", target_code="FEED-SYSTEM")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_OBSERVATION_TYPE"


async def test_observation_target_outside_policy_is_rejected(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)

    response = await observe(client, session_id, observation_type="verify_result", target_code="N-1")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OBSERVATION_TARGET_NOT_ALLOWED"


async def test_repeated_request_id_returns_the_same_observation(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)
    payload = {
        "request_id": str(uuid4()),
        "observation_type": "compare_flows",
        "target_code": "FEED-SYSTEM",
    }

    first = await client.post(f"/api/v1/sessions/{session_id}/observations", json=payload)
    second = await client.post(f"/api/v1/sessions/{session_id}/observations", json=payload)

    assert first.json() == second.json()


async def test_precheck_closes_when_operator_inspects_every_section(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    """Этап осмотра больше не ждёт таймаута: его закрывают явные проверки оператора."""

    session_id = await running_session(client, configuration)

    for target in ("FEED-SYSTEM", "T-1_T-11", "ELOU", "K-2"):
        assert (
            await observe(client, session_id, observation_type="inspect_equipment", target_code=target)
        ).status_code == 201
    await tick(database, session_id, times=2)

    state = (await client.get(f"/api/v1/sessions/{session_id}/state")).json()
    assert state["sim_time_ms"] < 120_000
    assert state["current_stage_code"] == "feed_preparation"


async def test_diagnosis_response_hides_correctness(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    session_id = await running_session(client, configuration)

    response = await client.post(
        f"/api/v1/sessions/{session_id}/diagnoses",
        json={
            "request_id": str(uuid4()),
            "affected_area_code": "FEED-SYSTEM",
            "deviation_code": "branch_flow_loss",
            "suspected_cause_code": "pump_capacity_loss",
        },
    )

    assert response.status_code == 201
    assert "is_correct" not in response.text
    assert "correct" not in response.json()

    async with database.session_factory() as session:
        stored = await session.scalar(select(OperatorDiagnosis))
        training_session = await session.get(TrainingSession, session_id)
    assert stored is not None and training_session is not None
    hidden_cause = training_session.hidden_runtime_config_json["disturbance"]["cause_code"]
    assert stored.is_correct == (hidden_cause == "pump_capacity_loss")


async def test_observation_on_paused_session_is_refused(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)
    await client.post(f"/api/v1/sessions/{session_id}/pause", json={"request_id": str(uuid4())})

    response = await observe(client, session_id, observation_type="compare_flows", target_code="FEED-SYSTEM")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SESSION_NOT_RUNNING"
