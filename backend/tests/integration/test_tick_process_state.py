from sqlalchemy import select

from app.application.runtime_config import disturbance_of, twin_config
from app.application.sessions import create_session, transition_session
from app.application.tick import plant_state, run_tick
from app.domain.sessions import SessionCommand
from app.domain.twin import START_FEED_PUMP, Command, TwinConfig, step
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ProcessSnapshot, ScenarioVersion, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration


async def start_session(database: Database, configuration: SeededConfiguration) -> str:
    async with UnitOfWork(database.session_factory) as uow:
        state = await create_session(
            uow,
            request_id="create-1",
            operator_id="operator-1",
            scenario_version_id=configuration.scenario_version_id,
            level_no=1,
            random_seed=42,
        )
    async with UnitOfWork(database.session_factory) as uow:
        await transition_session(uow, state.id, SessionCommand.START, request_id="start-1")
    return state.id


async def start_feed_pump(database: Database, session_id: str) -> None:
    """Команды оператора появятся на следующем шаге этапа; здесь насос пускается напрямую."""

    async with UnitOfWork(database.session_factory) as uow:
        training_session = await uow.sessions.get(session_id)
        assert training_session is not None
        scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
        assert scenario is not None
        config = twin_config(scenario)
        plant = step(
            plant_state(training_session, config),
            config,
            disturbance_of(training_session),
            sim_time_ms=training_session.sim_time_ms,
            dt_ms=0,
            commands=[Command(START_FEED_PUMP, "N-1")],
        )
        training_session.runtime_state_json = plant.to_json()


async def tick(database: Database, session_id: str, times: int) -> None:
    for _ in range(times):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)


async def latest_snapshot(database: Database, session_id: str) -> ProcessSnapshot:
    async with database.session_factory() as session:
        snapshot = await session.scalar(
            select(ProcessSnapshot)
            .where(ProcessSnapshot.session_id == session_id)
            .order_by(ProcessSnapshot.sim_time_ms.desc())
            .limit(1)
        )
    assert snapshot is not None
    return snapshot


async def test_new_session_starts_from_prepared_plant(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_session(database, configuration)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
    assert stored is not None
    plant = plant_state(stored, TwinConfig())
    assert plant.pump_running is False
    assert all(branch.flow_tph == 0.0 for branch in plant.branches)


async def test_snapshot_contains_catalog_tag_values(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_session(database, configuration)
    await start_feed_pump(database, session_id)

    await tick(database, session_id, times=60)
    snapshot = await latest_snapshot(database, session_id)

    assert snapshot.visible_values_json["branch_1_flow_tph"] > 40.0
    assert snapshot.visible_values_json["feed_pump_state"] == "RUNNING"
    assert snapshot.derived_values_json["total_feed_flow_tph"] > 120.0
    assert snapshot.derived_values_json["min_branch_flow_ratio"] > 0.4


async def test_process_state_survives_between_ticks(
    database: Database, configuration: SeededConfiguration
) -> None:
    """Состояние двойника хранится в сессии, поэтому расчёт продолжается, а не начинается заново."""

    session_id = await start_session(database, configuration)
    await start_feed_pump(database, session_id)

    await tick(database, session_id, times=30)
    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
        assert stored is not None
        after_thirty = plant_state(stored, TwinConfig()).branches[0].flow_tph

    await tick(database, session_id, times=30)
    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
        assert stored is not None
        after_sixty = plant_state(stored, TwinConfig()).branches[0].flow_tph

    assert after_sixty > after_thirty


async def test_snapshot_hides_process_internals_from_visible_values(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_session(database, configuration)
    await start_feed_pump(database, session_id)
    await tick(database, session_id, times=10)

    snapshot = await latest_snapshot(database, session_id)

    assert "severity" not in snapshot.visible_values_json
    assert "severity" not in snapshot.derived_values_json
    # Скрытая интенсивность возмущения доступна только аудиту и replay.
    assert "severity" in snapshot.internal_state_json
    assert snapshot.state_hash != ""


async def test_same_seed_gives_the_same_state_hash(
    database: Database, configuration: SeededConfiguration
) -> None:
    first_id = await start_session(database, configuration)
    await start_feed_pump(database, first_id)
    await tick(database, first_id, times=20)

    async with UnitOfWork(database.session_factory) as uow:
        state = await create_session(
            uow,
            request_id="create-2",
            operator_id="operator-1",
            scenario_version_id=configuration.scenario_version_id,
            level_no=1,
            random_seed=42,
        )
    async with UnitOfWork(database.session_factory) as uow:
        await transition_session(uow, state.id, SessionCommand.START, request_id="start-2")
    await start_feed_pump(database, state.id)
    await tick(database, state.id, times=20)

    first = await latest_snapshot(database, first_id)
    second = await latest_snapshot(database, state.id)
    assert first.state_hash == second.state_hash
