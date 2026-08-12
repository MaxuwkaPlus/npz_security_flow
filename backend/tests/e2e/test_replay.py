"""Воспроизводимость прохождения (§18 ТЗ).

Одинаковые версия сценария, уровень, seed и журнал действий должны давать одинаковый
расчёт. Проверяется по `state_hash` снимков: он считается от видимого и внутреннего
состояния двойника, поэтому расхождение в любой величине будет замечено.
"""

from collections.abc import Sequence
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.application.tick import run_tick
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ProcessSnapshot, ScenarioVersion
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration
from tests.support import speed_up_process_model

SCRIPT = (
    (0, "start_feed_pump", "N-1", {}),
    (0, "set_wash_water", "ELOU", {"ratio": 0.075}),
    (0, "start_transfer_pump", "N-20", {}),
    (200, "set_furnace_heat_load", "FURNACES", {"heat_load_pct": 100.0}),
    (500, "set_control_valve", "FRC-405", {"opening_pct": 90.0}),
)
TOTAL_SECONDS = 900


async def run_scripted_session(
    client: AsyncClient,
    database: Database,
    configuration: SeededConfiguration,
    *,
    random_seed: int,
) -> str:
    """Прогоняет один и тот же журнал действий на одинаковых версиях конфигурации."""

    created = await client.post(
        "/api/v1/sessions",
        json={
            "request_id": str(uuid4()),
            "operator_id": "replay-operator",
            "scenario_version_id": configuration.scenario_version_id,
            "level_no": 1,
            "random_seed": random_seed,
        },
    )
    session_id: str = created.json()["id"]
    await client.post(f"/api/v1/sessions/{session_id}/start", json={"request_id": str(uuid4())})

    pending = list(SCRIPT)
    for second in range(TOTAL_SECONDS):
        while pending and pending[0][0] == second:
            _, action_type, target, value = pending.pop(0)
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
    return session_id


async def state_hashes(database: Database, session_id: str) -> Sequence[str]:
    async with database.session_factory() as session:
        snapshots = (
            await session.scalars(
                select(ProcessSnapshot)
                .where(ProcessSnapshot.session_id == session_id)
                .order_by(ProcessSnapshot.sim_time_ms)
            )
        ).all()
    return [snapshot.state_hash for snapshot in snapshots]


async def prepare(database: Database, configuration: SeededConfiguration) -> None:
    async with database.session_factory() as session, session.begin():
        scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
        assert scenario is not None
        scenario.config_json = speed_up_process_model(scenario.config_json)


async def test_same_seed_and_action_log_reproduce_the_run(
    client: AsyncClient, database: Database, configuration: SeededConfiguration
) -> None:
    await prepare(database, configuration)

    first = await run_scripted_session(client, database, configuration, random_seed=2024)
    second = await run_scripted_session(client, database, configuration, random_seed=2024)

    first_hashes = await state_hashes(database, first)
    second_hashes = await state_hashes(database, second)
    assert first_hashes
    assert first_hashes == second_hashes


async def test_different_seed_changes_the_run(
    client: AsyncClient, database: Database, configuration: SeededConfiguration
) -> None:
    """Seed выбирает скрытое возмущение, поэтому расчёт обязан отличаться."""

    await prepare(database, configuration)

    first = await run_scripted_session(client, database, configuration, random_seed=2024)
    other = await run_scripted_session(client, database, configuration, random_seed=99)

    assert await state_hashes(database, first) != await state_hashes(database, other)


async def test_reports_of_identical_runs_match(
    client: AsyncClient, database: Database, configuration: SeededConfiguration
) -> None:
    """Отчёт выводится из журнала, поэтому два одинаковых прохождения дают один документ."""

    await prepare(database, configuration)
    first = await run_scripted_session(client, database, configuration, random_seed=2024)
    second = await run_scripted_session(client, database, configuration, random_seed=2024)

    first_report = (await client.get(f"/api/v1/sessions/{first}/report")).json()
    second_report = (await client.get(f"/api/v1/sessions/{second}/report")).json()

    for report in (first_report, second_report):
        # Идентификаторы у сессий разные — сравнивается содержательная часть.
        report.pop("session")
        report.pop("versions")
    assert first_report == second_report


async def test_snapshot_hash_changes_with_the_state(
    client: AsyncClient, database: Database, configuration: SeededConfiguration
) -> None:
    """Хеш покрывает и скрытое состояние, поэтому разные моменты дают разные хеши."""

    await prepare(database, configuration)
    session_id = await run_scripted_session(client, database, configuration, random_seed=2024)

    async with database.session_factory() as session:
        snapshots = (
            await session.scalars(
                select(ProcessSnapshot)
                .where(ProcessSnapshot.session_id == session_id)
                .order_by(ProcessSnapshot.sim_time_ms)
            )
        ).all()

    assert all("severity" in snapshot.internal_state_json for snapshot in snapshots)
    hashes = [snapshot.state_hash for snapshot in snapshots]
    assert all(hashes)
    # Установка всё время меняется, поэтому повторов быть не должно.
    assert len(set(hashes)) == len(hashes)
