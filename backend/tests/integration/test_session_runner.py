import asyncio

from app.application.sessions import create_session, transition_session
from app.domain.sessions import SessionCommand
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.realtime.hub import RealtimeHub
from app.infrastructure.runtime.session_runner import SessionRunner
from tests.conftest import SeededConfiguration

# Симуляционное время идёт в 500 раз быстрее реального: тест не ждёт реальных секунд.
SPEED_FACTOR = 500.0


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


async def wait_until_sim_time(database: Database, session_id: str, sim_time_ms: int) -> int:
    async def poll() -> int:
        while True:
            async with database.session_factory() as session:
                stored = await session.get(TrainingSession, session_id)
                assert stored is not None
                if stored.sim_time_ms >= sim_time_ms:
                    return stored.sim_time_ms
            await asyncio.sleep(0.005)

    return await asyncio.wait_for(poll(), timeout=10)


async def test_runner_advances_simulation_time_in_background(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_session(database, configuration)
    runner = SessionRunner(database, SPEED_FACTOR, RealtimeHub())

    runner.start(session_id)
    try:
        reached = await wait_until_sim_time(database, session_id, 5_000)
    finally:
        await runner.stop(session_id)

    assert reached >= 5_000
    assert runner.running_sessions == frozenset()


async def test_repeated_start_does_not_create_second_task(
    database: Database, configuration: SeededConfiguration
) -> None:
    """Два тика одной сессии не должны выполняться параллельно."""

    session_id = await start_session(database, configuration)
    runner = SessionRunner(database, SPEED_FACTOR, RealtimeHub())

    runner.start(session_id)
    runner.start(session_id)
    try:
        assert runner.running_sessions == frozenset({session_id})
    finally:
        await runner.stop_all()

    assert runner.running_sessions == frozenset()


async def test_stopped_runner_freezes_simulation_time(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_session(database, configuration)
    runner = SessionRunner(database, SPEED_FACTOR, RealtimeHub())

    runner.start(session_id)
    await wait_until_sim_time(database, session_id, 2_000)
    await runner.stop(session_id)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
        assert stored is not None
        frozen = stored.sim_time_ms

    await asyncio.sleep(0.05)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
        assert stored is not None
        assert stored.sim_time_ms == frozen
