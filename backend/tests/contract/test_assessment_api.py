from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.application.tick import run_tick
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ScenarioVersion, SessionEvent
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration
from tests.support import speed_up_process_model

TLX = {
    "mental_demand": 7.0,
    "physical_demand": 2.0,
    "temporal_demand": 6.0,
    "performance": 3.0,
    "effort": 5.0,
    "frustration": 4.0,
}


async def running_session(
    client: AsyncClient, configuration: SeededConfiguration, database: Database | None = None
) -> str:
    if database is not None:
        async with database.session_factory() as session, session.begin():
            scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
            assert scenario is not None
            scenario.config_json = speed_up_process_model(scenario.config_json)
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


async def force_stage(database: Database, session_id: str, stage_code: str) -> None:
    """Ставит сессию на нужный этап: SAGAT привязан к завершению stable_mode."""

    async with UnitOfWork(database.session_factory) as uow:
        training_session = await uow.sessions.get(session_id)
        assert training_session is not None
        training_session.current_stage_code = stage_code
        uow.sessions.open_stage(training_session, stage_code)


async def open_sagat(client: AsyncClient, database: Database, session_id: str) -> dict[str, Any]:
    """Доводит установку до подтверждения устойчивого режима и открывает контрольную точку."""

    for action_type, target, value in (
        ("start_feed_pump", "N-1", {}),
        ("set_wash_water", "ELOU", {"ratio": 0.075}),
        ("start_transfer_pump", "N-20", {}),
    ):
        await client.post(
            f"/api/v1/sessions/{session_id}/actions",
            json={
                "request_id": str(uuid4()),
                "action_type": action_type,
                "target_code": target,
                "value": value,
            },
        )
    async with UnitOfWork(database.session_factory) as uow:
        await run_tick(uow, session_id)
    await client.post(
        f"/api/v1/sessions/{session_id}/actions",
        json={
            "request_id": str(uuid4()),
            "action_type": "set_furnace_heat_load",
            "target_code": "FURNACES",
            "value": {"heat_load_pct": 100.0},
        },
    )
    for _ in range(400):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)
    await force_stage(database, session_id, "stable_mode")
    for _ in range(60):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)

    response = await client.get(f"/api/v1/sessions/{session_id}/sagat/current")
    assert response.status_code == 200
    checkpoint: dict[str, Any] | None = response.json()
    assert checkpoint is not None, "контрольная точка должна открыться после устойчивого режима"
    return checkpoint


async def test_no_checkpoint_before_its_stage(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)

    response = await client.get(f"/api/v1/sessions/{session_id}/sagat/current")

    assert response.status_code == 200
    assert response.json() is None


async def test_checkpoint_exposes_questions_without_expected_answers(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    session_id = await running_session(client, configuration, database)

    checkpoint = await open_sagat(client, database, session_id)

    assert checkpoint["checkpoint_code"] == "after_stable_mode"
    kinds = {question["kind"] for question in checkpoint["questions"]}
    assert kinds == {"what_changed", "what_it_means", "what_happens_next"}
    for leaked in ("expected", "metric", "threshold", "answer"):
        assert leaked not in str(checkpoint["questions"])


async def test_answers_are_scored_against_the_plant_state(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    session_id = await running_session(client, configuration, database)
    checkpoint = await open_sagat(client, database, session_id)

    response = await client.post(
        f"/api/v1/sessions/{session_id}/sagat/{checkpoint['id']}/answers",
        json={
            "request_id": str(uuid4()),
            # Установка в норме: температура ниже предела, подача стабильна.
            "answers": {"lowest_flow_branch": "1", "t11_over_limit": "no", "k1_feed_trend": "steady"},
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "answered"
    assert result["maximum"] == 3.0
    assert result["scores"]["t11_over_limit"] == 1.0
    assert result["earned"] >= 1.0

    async with database.session_factory() as session:
        events = (
            await session.scalars(select(SessionEvent).where(SessionEvent.event_type == "sagat_requested"))
        ).all()
    assert len(events) == 1


async def test_answered_checkpoint_is_not_offered_again(
    client: AsyncClient, configuration: SeededConfiguration, database: Database
) -> None:
    session_id = await running_session(client, configuration, database)
    checkpoint = await open_sagat(client, database, session_id)

    await client.post(
        f"/api/v1/sessions/{session_id}/sagat/{checkpoint['id']}/answers",
        json={"request_id": str(uuid4()), "answers": {"t11_over_limit": "no"}},
    )

    assert (await client.get(f"/api/v1/sessions/{session_id}/sagat/current")).json() is None


async def test_nasa_tlx_is_averaged_and_accepted_once(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)

    first = await client.post(f"/api/v1/sessions/{session_id}/nasa-tlx", json=TLX)
    second = await client.post(f"/api/v1/sessions/{session_id}/nasa-tlx", json=TLX)

    assert first.status_code == 201
    # Успешность инвертируется: 7+2+6+7+5+4 = 31.
    assert first.json()["raw_tlx_score"] == round(31 / 6, 2)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "NASA_TLX_ALREADY_SUBMITTED"


async def test_nasa_tlx_rejects_values_outside_the_scale(
    client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(client, configuration)

    response = await client.post(f"/api/v1/sessions/{session_id}/nasa-tlx", json=TLX | {"effort": 42.0})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_scenario_version_is_used_for_questions(
    configuration: SeededConfiguration, database: Database
) -> None:
    """Состав вопросов берётся из опубликованной версии сценария."""

    async with database.session_factory() as session:
        scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
    assert scenario is not None
    codes = [item["code"] for item in scenario.config_json["sagat"]["checkpoints"]]
    assert codes == ["after_stable_mode", "after_correction"]
