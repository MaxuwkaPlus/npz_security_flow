"""Владелец симуляции сессии.

Технические требования §12: у одной сессии должен быть один последовательный поток
изменения состояния. Здесь это обеспечено двумя средствами: на сессию приходится ровно
одна asyncio-задача тиков, и любая запись — тик или команда жизненного цикла — идёт
внутри блокировки сессии, вместе с транзакцией. Логика шага остаётся в application-слое
и одинаково доступна тестам и replay.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.application.tick import TickResult, run_tick
from app.core.logging import session_id_var
from app.domain.sessions import is_terminal
from app.infrastructure.db.engine import Database
from app.infrastructure.db.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class SessionRunner:
    """Реестр фоновых задач симуляции и блокировок записи по сессиям."""

    def __init__(self, database: Database, speed_factor: float) -> None:
        if speed_factor <= 0:
            raise ValueError("Множитель скорости симуляции должен быть положительным")
        self._database = database
        self._speed_factor = speed_factor
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def exclusive(self, session_id: str) -> AsyncIterator[UnitOfWork]:
        """Транзакция единственного писателя сессии: тик и команда не пересекаются."""

        async with self._lock_for(session_id), UnitOfWork(self._database.session_factory) as uow:
            yield uow

    def start(self, session_id: str) -> None:
        """Идемпотентно: повторный запуск уже идущей сессии не создаёт вторую задачу."""

        existing = self._tasks.get(session_id)
        if existing is not None and not existing.done():
            return
        self._tasks[session_id] = asyncio.create_task(
            self._run(session_id), name=f"session-tick:{session_id}"
        )

    async def stop(self, session_id: str) -> None:
        task = self._tasks.pop(session_id, None)
        self._locks.pop(session_id, None)
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def stop_all(self) -> None:
        for session_id in list(self._tasks):
            await self.stop(session_id)

    @property
    def running_sessions(self) -> frozenset[str]:
        return frozenset(session_id for session_id, task in self._tasks.items() if not task.done())

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    async def _run(self, session_id: str) -> None:
        token = session_id_var.set(session_id)
        try:
            while True:
                result = await self._tick_once(session_id)
                if result is None or is_terminal(result.status):
                    return
                # Пауза не двигает симуляционное время, но задача остаётся живой,
                # чтобы продолжение не требовало перезапуска симуляции.
                await asyncio.sleep(result.tick_interval_ms / 1000 / self._speed_factor)
        except asyncio.CancelledError:
            logger.info("session_runner_cancelled")
            raise
        finally:
            session_id_var.reset(token)

    async def _tick_once(self, session_id: str) -> TickResult | None:
        """None означает сбой шага: симуляция останавливается, сессия остаётся за инструктором."""

        try:
            async with self.exclusive(session_id) as uow:
                return await run_tick(uow, session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("session_tick_failed")
            return None
