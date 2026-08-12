"""Нагрузочная проверка одновременных сессий (§18 ТЗ).

Ориентир проектирования — 20 одновременных прохождений. Тест измеряет фактическое
время шага и проверяет, что запись в одну файловую SQLite не рассыпается: у каждой
сессии свой последовательный поток изменений, разные сессии конкурируют за общий файл.

Измеренные числа печатаются, но подтверждённым SLA не являются: они зависят от машины.
"""

import asyncio
import time

from sqlalchemy import func, select

from app.application.actions import submit_action
from app.application.sessions import create_session, transition_session
from app.application.tick import run_tick
from app.domain.sessions import SessionCommand, SessionStatus
from app.domain.twin import START_FEED_PUMP
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ProcessSnapshot, SessionEvent, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.realtime.hub import RealtimeHub
from app.infrastructure.runtime.session_runner import SessionRunner
from tests.conftest import SeededConfiguration

CONCURRENT_SESSIONS = 20
TARGET_SIM_TIME_MS = 30_000
# Симуляция идёт быстрее реального времени, иначе тест ждал бы полминуты.
SPEED_FACTOR = 300.0


async def create_running_session(database: Database, configuration: SeededConfiguration, index: int) -> str:
    async with UnitOfWork(database.session_factory) as uow:
        state = await create_session(
            uow,
            request_id=f"create-{index}",
            operator_id=f"operator-{index}",
            scenario_version_id=configuration.scenario_version_id,
            level_no=1,
            random_seed=index,
        )
    async with UnitOfWork(database.session_factory) as uow:
        await transition_session(uow, state.id, SessionCommand.START, request_id=f"start-{index}")
    return state.id


async def sim_time_of(database: Database, session_id: str) -> int:
    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
    assert stored is not None
    return stored.sim_time_ms


async def wait_for_all(database: Database, session_ids: list[str], target_ms: int) -> None:
    async def reached() -> None:
        while True:
            times = [await sim_time_of(database, session_id) for session_id in session_ids]
            if min(times) >= target_ms:
                return
            await asyncio.sleep(0.02)

    await asyncio.wait_for(reached(), timeout=60)


async def test_twenty_sessions_advance_without_write_conflicts(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_ids = [
        await create_running_session(database, configuration, index) for index in range(CONCURRENT_SESSIONS)
    ]
    runner = SessionRunner(database, SPEED_FACTOR, RealtimeHub())

    started = time.perf_counter()
    for session_id in session_ids:
        runner.start(session_id)
    try:
        await wait_for_all(database, session_ids, TARGET_SIM_TIME_MS)
    finally:
        await runner.stop_all()
    elapsed = time.perf_counter() - started

    ticks = CONCURRENT_SESSIONS * TARGET_SIM_TIME_MS // 1000
    print(
        f"\n{CONCURRENT_SESSIONS} сессий, {ticks} шагов за {elapsed:.1f} с "
        f"({ticks / elapsed:.0f} шагов/с, {elapsed / ticks * 1000:.1f} мс на шаг)"
    )

    async with database.session_factory() as session:
        statuses = set((await session.scalars(select(TrainingSession.status))).all())
    assert statuses == {SessionStatus.RUNNING}


async def test_each_session_keeps_its_own_gapless_sequence(
    database: Database, configuration: SeededConfiguration
) -> None:
    """Общий файл БД не смешивает нумерацию: у каждой сессии свой монотонный счётчик."""

    session_ids = [await create_running_session(database, configuration, index) for index in range(5)]

    await asyncio.gather(*(_tick_many(database, session_id, 30) for session_id in session_ids))

    for session_id in session_ids:
        async with UnitOfWork(database.session_factory) as uow:
            events = await uow.sessions.events_after(session_id, 0)
            snapshots = list(
                (
                    await uow.session.scalars(
                        select(ProcessSnapshot.sequence_no).where(ProcessSnapshot.session_id == session_id)
                    )
                ).all()
            )
        numbers = sorted([event.sequence_no for event in events] + snapshots)
        assert numbers == list(range(1, len(numbers) + 1))


async def test_parallel_writes_do_not_lose_events(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_ids = [await create_running_session(database, configuration, index) for index in range(8)]

    await asyncio.gather(
        *(_start_pump_and_tick(database, session_id, index) for index, session_id in enumerate(session_ids))
    )

    async with database.session_factory() as session:
        applied = await session.scalar(
            select(func.count()).select_from(SessionEvent).where(SessionEvent.event_type == "action_applied")
        )
    assert applied == len(session_ids)


async def _tick_many(database: Database, session_id: str, times: int) -> None:
    for _ in range(times):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)


async def _start_pump_and_tick(database: Database, session_id: str, index: int) -> None:
    async with UnitOfWork(database.session_factory) as uow:
        await submit_action(
            uow,
            session_id,
            request_id=f"pump-{index}",
            action_type=START_FEED_PUMP,
            target_code="N-1",
        )
    await _tick_many(database, session_id, 10)
