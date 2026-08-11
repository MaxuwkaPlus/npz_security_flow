from sqlalchemy import select

from app.application.actions import submit_action
from app.application.sessions import create_session, transition_session
from app.application.tick import run_tick
from app.domain.sessions import SessionCommand
from app.domain.twin import START_FEED_PUMP
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import SessionEvent, SessionStageHistory, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration


async def running_session(database: Database, configuration: SeededConfiguration) -> str:
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


async def tick(database: Database, session_id: str, times: int) -> None:
    for _ in range(times):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)


async def history_of(database: Database, session_id: str) -> list[SessionStageHistory]:
    async with database.session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(SessionStageHistory)
                    .where(SessionStageHistory.session_id == session_id)
                    .order_by(SessionStageHistory.entered_sim_time_ms)
                )
            ).all()
        )


async def current_stage(database: Database, session_id: str) -> str:
    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
    assert stored is not None
    return stored.current_stage_code


async def test_session_starts_on_the_first_stage(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(database, configuration)

    assert await current_stage(database, session_id) == "precheck"
    assert [entry.stage_code for entry in await history_of(database, session_id)] == ["precheck"]


async def test_stage_without_completed_checks_closes_by_timeout(
    database: Database, configuration: SeededConfiguration
) -> None:
    """precheck ждёт обязательных проверок оператора; они появятся вместе с наблюдениями."""

    session_id = await running_session(database, configuration)

    await tick(database, session_id, times=239)
    assert await current_stage(database, session_id) == "precheck"

    await tick(database, session_id, times=1)
    assert await current_stage(database, session_id) == "feed_preparation"

    entries = await history_of(database, session_id)
    assert entries[0].outcome == "timeout"
    assert entries[0].exited_sim_time_ms == 240_000
    assert entries[0].transition_reason_event_id is not None


async def test_running_pump_closes_feed_preparation_by_success(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(database, configuration)
    async with UnitOfWork(database.session_factory) as uow:
        await submit_action(
            uow, session_id, request_id="pump-1", action_type=START_FEED_PUMP, target_code="N-1"
        )

    # precheck закрывается по timeout, дальше этапы пуска закрываются по своим условиям.
    await tick(database, session_id, times=280)

    entries = {entry.stage_code: entry.outcome for entry in await history_of(database, session_id)}
    assert entries["precheck"] == "timeout"
    assert entries["feed_preparation"] == "success"
    assert entries["feed_startup"] == "success"
    assert await current_stage(database, session_id) not in ("precheck", "feed_preparation")


async def test_stage_change_is_recorded_as_event(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await running_session(database, configuration)

    await tick(database, session_id, times=240)

    async with database.session_factory() as session:
        events = (
            await session.scalars(select(SessionEvent).where(SessionEvent.event_type == "stage_changed"))
        ).all()
    assert len(events) == 1
    assert events[0].payload_json == {
        "from": "precheck",
        "to": "feed_preparation",
        "outcome": "timeout",
    }
