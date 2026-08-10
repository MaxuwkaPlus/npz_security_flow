from sqlalchemy import select

from app.application.sessions import create_session, transition_session
from app.application.tick import run_tick
from app.domain.sessions import SessionCommand, SessionStatus
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


async def tick(database: Database, session_id: str, times: int = 1) -> None:
    for _ in range(times):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)


async def test_tick_advances_simulation_time_by_one_second(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_session(database, configuration)

    await tick(database, session_id, times=3)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
    assert stored is not None
    assert stored.sim_time_ms == 3_000


async def test_paused_session_does_not_move_simulation_time(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_session(database, configuration)
    await tick(database, session_id, times=2)

    async with UnitOfWork(database.session_factory) as uow:
        await transition_session(uow, session_id, SessionCommand.PAUSE, request_id="pause-1")
    await tick(database, session_id, times=5)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
    assert stored is not None
    assert stored.sim_time_ms == 2_000

    async with UnitOfWork(database.session_factory) as uow:
        await transition_session(uow, session_id, SessionCommand.RESUME, request_id="resume-1")
    await tick(database, session_id, times=1)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
    assert stored is not None
    assert stored.sim_time_ms == 3_000


async def test_snapshots_are_written_on_configured_interval(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_session(database, configuration)

    await tick(database, session_id, times=11)

    async with database.session_factory() as session:
        snapshots = (
            await session.scalars(
                select(ProcessSnapshot)
                .where(ProcessSnapshot.session_id == session_id)
                .order_by(ProcessSnapshot.sim_time_ms)
            )
        ).all()

    assert [snapshot.sim_time_ms for snapshot in snapshots] == [5_000, 10_000]


async def test_sequence_numbers_increase_without_gaps(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_session(database, configuration)

    await tick(database, session_id, times=10)

    async with UnitOfWork(database.session_factory) as uow:
        events = await uow.sessions.events_after(session_id, after_sequence_no=0)
        snapshots_query = select(ProcessSnapshot.sequence_no).where(ProcessSnapshot.session_id == session_id)
        snapshot_numbers = list((await uow.session.scalars(snapshots_query)).all())

    numbers = sorted([event.sequence_no for event in events] + snapshot_numbers)
    assert numbers == list(range(1, len(numbers) + 1))


async def test_session_completes_when_scenario_duration_is_reached(
    database: Database, configuration: SeededConfiguration
) -> None:
    """Длительность сценария укорочена, чтобы проверить завершение без 3900 тиков."""

    async with database.session_factory() as session, session.begin():
        scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
        assert scenario is not None
        scenario.duration_ms = 3_000

    session_id = await start_session(database, configuration)
    await tick(database, session_id, times=5)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
    assert stored is not None
    assert stored.status == SessionStatus.COMPLETED
    assert stored.sim_time_ms == 3_000
    assert stored.completed_at is not None


async def test_tick_on_ready_session_changes_nothing(
    database: Database, configuration: SeededConfiguration
) -> None:
    async with UnitOfWork(database.session_factory) as uow:
        state = await create_session(
            uow,
            request_id="create-2",
            operator_id="operator-1",
            scenario_version_id=configuration.scenario_version_id,
            level_no=1,
            random_seed=1,
        )

    async with UnitOfWork(database.session_factory) as uow:
        result = await run_tick(uow, state.id)

    assert result.applied is False
    assert result.sim_time_ms == 0
