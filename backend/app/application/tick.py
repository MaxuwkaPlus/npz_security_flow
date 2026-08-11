"""Один шаг симуляции.

Порядок шагов зафиксирован §12 технического задания. Текущее состояние двойника
хранится в самой сессии, поэтому после перезапуска симуляция продолжается с последнего
рассчитанного момента, а снимки остаются журналом для аудита и replay.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.application.alarms import load_alarm_rules, refresh_alarms
from app.application.runtime_config import disturbance_of, simulation_clock, twin_config
from app.core.errors import NotFoundError
from app.domain.clock import SimulationClock
from app.domain.commands import ActionStatus
from app.domain.metrics import derived_values, rule_metrics, visible_values
from app.domain.sessions import SessionCommand, SessionStatus, apply_command
from app.domain.twin import Command, PlantState, TwinConfig, initial_state, step
from app.infrastructure.db.models import OperatorAction, ScenarioVersion, TrainingSession
from app.infrastructure.db.types import utcnow
from app.infrastructure.db.unit_of_work import UnitOfWork

PLANT_KEY = "plant"
ALARMS_KEY = "alarms"
PENDING_KEY = "pending_since"


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

    scenario = await _load_scenario(uow, training_session)
    clock = simulation_clock(scenario)
    if SessionStatus(training_session.status) is not SessionStatus.RUNNING:
        return _result(training_session, clock, applied=False, snapshot_written=False)

    config = twin_config(scenario)
    before = plant_state(training_session, config)
    # 1–3. Принятые команды берутся в порядке поступления и применяются этим шагом.
    pending = await uow.sessions.accepted_actions(session_id)
    training_session.sim_time_ms = clock.advance(training_session.sim_time_ms)
    # 4–6. Скрытое возмущение, новое технологическое состояние и производные значения.
    plant = step(
        before,
        config,
        disturbance_of(training_session),
        sim_time_ms=training_session.sim_time_ms,
        dt_ms=clock.tick_interval_ms,
        commands=[
            Command(action.action_type, action.target_code, action.requested_value_json) for action in pending
        ],
    )
    _mark_applied(uow, training_session, pending, before, plant, config)
    # 7. Тревоги по правилам версии сценария.
    metrics = rule_metrics(plant, config)
    alarm_timers = await refresh_alarms(
        uow,
        training_session,
        await load_alarm_rules(uow, scenario.id),
        metrics,
        alarm_timers_of(training_session),
    )
    training_session.runtime_state_json = _runtime_state(plant, alarm_timers)
    # 8–9. Переход этапа и оценка эффекта команд — следующие шаги этапа 3.

    snapshot_written = clock.is_snapshot_due(training_session.sim_time_ms)
    if snapshot_written:
        uow.sessions.add_snapshot(
            training_session,
            visible_values=visible_values(plant, config),
            derived_values=derived_values(plant, config),
            internal_state=plant.to_json(),
        )

    if clock.is_finished(training_session.sim_time_ms):
        _complete(uow, training_session)

    return _result(training_session, clock, applied=True, snapshot_written=snapshot_written)


def _mark_applied(
    uow: UnitOfWork,
    training_session: TrainingSession,
    actions: Sequence[OperatorAction],
    before: PlantState,
    after: PlantState,
    config: TwinConfig,
) -> None:
    """Фиксирует применение команды и состояние установки до и после воздействия."""

    if not actions:
        return
    before_values = visible_values(before, config)
    after_values = visible_values(after, config)
    for action in actions:
        action.status = ActionStatus.APPLIED
        action.before_state_json = before_values
        action.after_state_json = after_values
        uow.sessions.append_event(
            training_session,
            "action_applied",
            "operator_action",
            {"action_type": action.action_type, "target_code": action.target_code},
            aggregate_id=action.id,
        )


def plant_state(training_session: TrainingSession, config: TwinConfig) -> PlantState:
    """Состояние двойника сессии; для новой сессии — исходное состояние установки."""

    stored = training_session.runtime_state_json.get(PLANT_KEY)
    return PlantState.from_json(stored) if stored else initial_state(config)


def alarm_timers_of(training_session: TrainingSession) -> dict[str, int]:
    """Сколько держится ещё не включённая тревога: таймеры живут между тиками."""

    alarms = training_session.runtime_state_json.get(ALARMS_KEY, {})
    return {code: int(since) for code, since in alarms.get(PENDING_KEY, {}).items()}


def initial_runtime_state(config: TwinConfig) -> dict[str, Any]:
    return _runtime_state(initial_state(config), {})


def _runtime_state(plant: PlantState, alarm_timers: Mapping[str, int]) -> dict[str, Any]:
    return {PLANT_KEY: plant.to_json(), ALARMS_KEY: {PENDING_KEY: dict(alarm_timers)}}


async def _load_scenario(uow: UnitOfWork, training_session: TrainingSession) -> ScenarioVersion:
    # Опубликованная версия сценария неизменяема, поэтому чтение безопасно кэшировать позже.
    scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария сессии не найдена")
    return scenario


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
