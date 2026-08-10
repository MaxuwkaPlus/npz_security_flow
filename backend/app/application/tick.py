"""Один шаг симуляции.

Порядок шагов зафиксирован §12 технического задания. На этапе 2 работают время,
нумерация, снимки и завершение по длительности; расчёт технологического состояния,
возмущение и тревоги подключаются в отмеченных точках расширения на этапе 3.
"""

from dataclasses import dataclass

from app.core.errors import NotFoundError
from app.domain.clock import SimulationClock
from app.domain.sessions import SessionCommand, SessionStatus, apply_command
from app.infrastructure.db.models import ScenarioVersion, TrainingSession
from app.infrastructure.db.types import utcnow
from app.infrastructure.db.unit_of_work import UnitOfWork

DEFAULT_TICK_INTERVAL_MS = 1_000
DEFAULT_SNAPSHOT_INTERVAL_MS = 5_000


@dataclass(frozen=True, slots=True)
class TickResult:
    session_id: str
    applied: bool
    status: SessionStatus
    sim_time_ms: int
    sequence_no: int
    snapshot_written: bool
    # Шаг сценария возвращается наружу, чтобы runtime не хранил собственную копию настройки.
    tick_interval_ms: int


async def run_tick(uow: UnitOfWork, session_id: str) -> TickResult:
    """Продвигает сессию на один шаг. На паузе и в терминальном состоянии ничего не делает."""

    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")

    clock = await _load_clock(uow, training_session)
    status = SessionStatus(training_session.status)
    if status is not SessionStatus.RUNNING:
        return _result(training_session, clock, applied=False, snapshot_written=False)

    # 1–4. Команды оператора, скрытое возмущение и расчёт состояния — этап 3.
    training_session.sim_time_ms = clock.advance(training_session.sim_time_ms)
    # 5–9. Производные значения, тревоги, переход этапа и оценка эффекта — этап 3.

    snapshot_written = clock.is_snapshot_due(training_session.sim_time_ms)
    if snapshot_written:
        uow.sessions.add_snapshot(training_session, visible_values={}, derived_values={}, internal_state={})

    if clock.is_finished(training_session.sim_time_ms):
        _complete(uow, training_session)

    return _result(training_session, clock, applied=True, snapshot_written=snapshot_written)


async def _load_clock(uow: UnitOfWork, training_session: TrainingSession) -> SimulationClock:
    # Опубликованная версия сценария неизменяема, поэтому чтение безопасно кэшировать позже.
    scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария сессии не найдена")
    config = scenario.config_json
    return SimulationClock(
        tick_interval_ms=int(config.get("tick_interval_ms", DEFAULT_TICK_INTERVAL_MS)),
        snapshot_interval_ms=int(config.get("snapshot_interval_ms", DEFAULT_SNAPSHOT_INTERVAL_MS)),
        duration_ms=scenario.duration_ms,
    )


def _complete(uow: UnitOfWork, training_session: TrainingSession) -> None:
    training_session.status = apply_command(SessionStatus.RUNNING, SessionCommand.COMPLETE).status
    training_session.completed_at = utcnow()
    # final_outcome заполняет оценка прохождения на этапе 5: сейчас итог ещё не определён.
    uow.sessions.append_event(
        training_session,
        "session_completed",
        "session",
        {"reason": "scenario_duration_reached"},
    )


def _result(
    training_session: TrainingSession,
    clock: SimulationClock,
    *,
    applied: bool,
    snapshot_written: bool,
) -> TickResult:
    return TickResult(
        session_id=training_session.id,
        applied=applied,
        status=SessionStatus(training_session.status),
        sim_time_ms=training_session.sim_time_ms,
        sequence_no=training_session.last_sequence_no,
        snapshot_written=snapshot_written,
        tick_interval_ms=clock.tick_interval_ms,
    )
