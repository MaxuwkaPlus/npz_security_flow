from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from app.application.tick import run_tick
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ScenarioVersion
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration
from tests.support import speed_up_process_model


async def prepared_scenario(database: Database, configuration: SeededConfiguration) -> None:
    async with database.session_factory() as session, session.begin():
        scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
        assert scenario is not None
        scenario.config_json = speed_up_process_model(scenario.config_json)


async def run_session(
    client: AsyncClient, database: Database, configuration: SeededConfiguration, level_no: int
) -> str:
    created = await client.post(
        "/api/v1/sessions",
        json={
            "request_id": str(uuid4()),
            "operator_id": "operator-1",
            "scenario_version_id": configuration.scenario_version_id,
            "level_no": level_no,
            "random_seed": 42,
        },
    )
    session_id: str = created.json()["id"]
    await client.post(f"/api/v1/sessions/{session_id}/start", json={"request_id": str(uuid4())})
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
    for _ in range(300):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)
    return session_id


async def test_report_contains_every_required_section(
    client: AsyncClient, database: Database, configuration: SeededConfiguration
) -> None:
    await prepared_scenario(database, configuration)
    session_id = await run_session(client, database, configuration, level_no=1)

    response = await client.get(f"/api/v1/sessions/{session_id}/report")

    assert response.status_code == 200
    report: dict[str, Any] = response.json()
    assert set(report) == {
        "report_version",
        "session",
        "versions",
        "outcome",
        "timings",
        "scores",
        "score_events",
        "actions",
        "alarms",
        "downstream_checks",
        "stages",
        "worst_parameters",
        "conclusions",
    }
    assert report["outcome"] in ("stabilized", "not_stabilized", "aborted")
    assert report["versions"]["scenario_code"] == "ELOU-AVT-FULL-RUN"
    assert report["conclusions"]


async def test_report_hides_the_root_cause(
    client: AsyncClient, database: Database, configuration: SeededConfiguration
) -> None:
    """Отчёт объясняет действия оператора, но остаётся операторским документом."""

    await prepared_scenario(database, configuration)
    session_id = await run_session(client, database, configuration, level_no=1)

    body = (await client.get(f"/api/v1/sessions/{session_id}/report")).text

    for leaked in ("random_seed", "hidden", "onset_delay_ms", "severity"):
        assert leaked not in body


async def test_report_is_rebuilt_identically(
    client: AsyncClient, database: Database, configuration: SeededConfiguration
) -> None:
    await prepared_scenario(database, configuration)
    session_id = await run_session(client, database, configuration, level_no=1)

    first = (await client.get(f"/api/v1/sessions/{session_id}/report")).json()
    second = (await client.get(f"/api/v1/sessions/{session_id}/report")).json()

    assert first == second


async def test_unknown_session_report_returns_stable_error(client: AsyncClient) -> None:
    response = await client.get("/api/v1/sessions/00000000-0000-0000-0000-000000000000/report")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


async def test_level_comparison_puts_levels_side_by_side(
    client: AsyncClient, database: Database, configuration: SeededConfiguration
) -> None:
    await prepared_scenario(database, configuration)
    for level_no in (1, 3):
        session_id = await run_session(client, database, configuration, level_no=level_no)
        await client.get(f"/api/v1/sessions/{session_id}/report")

    response = await client.get("/api/v1/operators/operator-1/level-comparison")

    assert response.status_code == 200
    comparison = response.json()
    assert [item["level_no"] for item in comparison["levels"]] == [1, 3]
    assert comparison["efficiency_retention"] is not None
    assert comparison["absolute_drop"] is not None


async def test_level_comparison_of_unknown_operator_is_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/operators/nobody/level-comparison")

    assert response.status_code == 200
    assert response.json() == {
        "operator_id": "nobody",
        "levels": [],
        "efficiency_retention": None,
        "absolute_drop": None,
    }
