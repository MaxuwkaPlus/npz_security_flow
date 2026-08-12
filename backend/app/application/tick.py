"""Один шаг симуляции.

Порядок шагов зафиксирован §12 технического задания. Текущее состояние двойника
хранится в самой сессии, поэтому после перезапуска симуляция продолжается с последнего
рассчитанного момента, а снимки остаются журналом для аудита и replay.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.application.alarms import load_alarm_rules, refresh_alarms
from app.application.assessment import open_checkpoint, snapshot_metrics_before
from app.application.classification import classify_applied, effect_rule, evaluate_pending_effects
from app.application.observations import completed_checks
from app.application.runtime_config import (
    checks_policy,
    disturbance_after_stage,
    disturbance_of,
    nuisance_policy,
    safety_policy,
    sagat_policy,
    simulation_clock,
    twin_config,
)
from app.application.scoring import calculate_scores
from app.application.stages import advance_stage, load_stages
from app.core.errors import NotFoundError
from app.domain.clock import SimulationClock
from app.domain.commands import ActionClassification, ActionStatus, Command
from app.domain.metrics import derived_values, rule_metrics, visible_values
from app.domain.safety import (
    DANGEROUS_HEAT_COMPENSATION,
    SafetyPolicy,
    is_dangerous_heat_compensation,
)
from app.domain.sessions import SessionCommand, SessionStatus, apply_command
from app.domain.stages import StageDecision, StageOutcome
from app.domain.twin import PlantState, TwinConfig, initial_state, step
from app.infrastructure.db.models import (
    OperatorAction,
    ScenarioLevel,
    ScenarioVersion,
    TrainingSession,
)
from app.infrastructure.db.types import utcnow
from app.infrastructure.db.unit_of_work import UnitOfWork

PLANT_KEY = "plant"
ALARMS_KEY = "alarms"
PENDING_KEY = "pending_since"
STAGE_KEY = "stage"
HOLDING_KEY = "holding_since_ms"
ARMED_KEY = "disturbance_armed_at_ms"


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
    current_stage = training_session.current_stage_code
    before = plant_state(training_session, config)
    # 1–3. Принятые команды берутся в порядке поступления и применяются этим шагом.
    pending = await uow.sessions.accepted_actions(session_id)
    training_session.sim_time_ms = clock.advance(training_session.sim_time_ms)
    # 4–6. Скрытое возмущение, новое технологическое состояние и производные значения.
    armed_at_ms = disturbance_armed_at(training_session)
    plant = step(
        before,
        config,
        disturbance_of(training_session, armed_at_ms),
        sim_time_ms=training_session.sim_time_ms,
        dt_ms=clock.tick_interval_ms,
        commands=[
            Command(action.action_type, action.target_code, action.requested_value_json) for action in pending
        ],
    )
    _mark_applied(uow, training_session, pending, before, plant, config, safety_policy(scenario))
    # 9. Классификация команд: часть определяется сразу, часть — по окончании окна эффекта.
    metrics = rule_metrics(plant, config)
    rule = await effect_rule(uow, scenario.id)
    has_diagnosis = await uow.sessions.has_diagnosis(session_id)
    await classify_applied(
        uow,
        training_session,
        pending,
        before,
        plant,
        disturbance_of(training_session, armed_at_ms).correct_action_type,
        rule,
        has_diagnosis,
    )
    await evaluate_pending_effects(uow, training_session, metrics, rule)
    # 7. Тревоги по правилам версии сценария.
    level = await uow.session.get(ScenarioLevel, training_session.scenario_level_id)
    alarm_timers = await refresh_alarms(
        uow,
        training_session,
        await load_alarm_rules(uow, scenario.id),
        metrics,
        alarm_timers_of(training_session),
        nuisance=nuisance_policy(scenario, level) if level is not None else None,
        tick_interval_ms=clock.tick_interval_ms,
    )
    # 8. Переход этапа. Оценка эффекта команд появится вместе с классификацией действий.
    stages = await load_stages(uow, scenario.id)
    decision = await advance_stage(
        uow,
        training_session,
        stages,
        metrics,
        stage_timer_of(training_session),
        await completed_checks(uow, session_id, checks_policy(scenario)),
    )
    if decision.outcome is StageOutcome.SUCCESS:
        await _open_sagat_checkpoint(uow, training_session, scenario, current_stage, metrics)
    if armed_at_ms is None and _confirms_stable_mode(training_session, decision, current_stage):
        # Устойчивый режим подтверждён — с этого момента отсчитывается скрытое возмущение.
        armed_at_ms = training_session.sim_time_ms
    training_session.runtime_state_json = _runtime_state(
        plant, alarm_timers, decision.holding_since_ms, armed_at_ms
    )

    snapshot_written = clock.is_snapshot_due(training_session.sim_time_ms)
    if snapshot_written:
        uow.sessions.add_snapshot(
            training_session,
            visible_values=visible_values(plant, config),
            derived_values=derived_values(plant, config),
            internal_state=plant.to_json(),
        )

    scenario_finished = decision.changed and decision.next_stage_code is None
    if scenario_finished or clock.is_finished(training_session.sim_time_ms):
        _complete(uow, training_session, scenario_finished)
        await calculate_scores(uow, session_id)

    return _result(training_session, clock, applied=True, snapshot_written=snapshot_written)


def _mark_applied(
    uow: UnitOfWork,
    training_session: TrainingSession,
    actions: Sequence[OperatorAction],
    before: PlantState,
    after: PlantState,
    config: TwinConfig,
    safety: SafetyPolicy,
) -> None:
    """Фиксирует применение команды и состояние установки до и после воздействия."""

    if not actions:
        return
    before_values = visible_values(before, config)
    after_values = visible_values(after, config)
    before_metrics = rule_metrics(before, config)
    after_metrics = rule_metrics(after, config)
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
        if is_dangerous_heat_compensation(action.action_type, before_metrics, after_metrics, safety):
            # Правило технолога, а не вывод оценки: класс проставляется сразу.
            action.classification = ActionClassification.DANGEROUS
            uow.sessions.append_event(
                training_session,
                DANGEROUS_HEAT_COMPENSATION,
                "operator_action",
                {
                    "action_type": action.action_type,
                    "min_branch_flow_ratio": before_metrics.get("min_branch_flow_ratio"),
                    "heat_to_feed_ratio": after_metrics.get("furnace_heat_to_feed_ratio"),
                },
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


async def _open_sagat_checkpoint(
    uow: UnitOfWork,
    training_session: TrainingSession,
    scenario: ScenarioVersion,
    stage_code: str,
    metrics: dict[str, float],
) -> None:
    """Контрольная точка ставится сразу после успешного завершения этапа-триггера."""

    policy = sagat_policy(scenario)
    spec = policy.triggered_by(stage_code)
    if spec is None:
        return
    earlier = await snapshot_metrics_before(
        uow, training_session.id, training_session.sim_time_ms - policy.trend_window_ms
    )
    await open_checkpoint(uow, training_session, spec, metrics, earlier)


def disturbance_armed_at(training_session: TrainingSession) -> int | None:
    """Момент подтверждения устойчивого режима; до него возмущения не существует."""

    armed = training_session.runtime_state_json.get(STAGE_KEY, {}).get(ARMED_KEY)
    return int(armed) if armed is not None else None


def _confirms_stable_mode(
    training_session: TrainingSession, decision: StageDecision, stage_code: str
) -> bool:
    return decision.outcome is StageOutcome.SUCCESS and stage_code == disturbance_after_stage(
        training_session
    )


def stage_timer_of(training_session: TrainingSession) -> int | None:
    """С какого момента условие успеха этапа держится непрерывно."""

    holding = training_session.runtime_state_json.get(STAGE_KEY, {}).get(HOLDING_KEY)
    return int(holding) if holding is not None else None


def initial_runtime_state(config: TwinConfig) -> dict[str, Any]:
    return _runtime_state(initial_state(config), {}, None, None)


def _runtime_state(
    plant: PlantState,
    alarm_timers: Mapping[str, int],
    stage_holding_since_ms: int | None,
    disturbance_armed_at_ms: int | None,
) -> dict[str, Any]:
    return {
        PLANT_KEY: plant.to_json(),
        ALARMS_KEY: {PENDING_KEY: dict(alarm_timers)},
        STAGE_KEY: {HOLDING_KEY: stage_holding_since_ms, ARMED_KEY: disturbance_armed_at_ms},
    }


async def _load_scenario(uow: UnitOfWork, training_session: TrainingSession) -> ScenarioVersion:
    # Опубликованная версия сценария неизменяема, поэтому чтение безопасно кэшировать позже.
    scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария сессии не найдена")
    return scenario


def _complete(uow: UnitOfWork, training_session: TrainingSession, all_stages_passed: bool) -> None:
    training_session.status = apply_command(SessionStatus.RUNNING, SessionCommand.COMPLETE).status
    training_session.completed_at = utcnow()
    # final_outcome заполняет оценка прохождения на этапе 5: сейчас итог ещё не определён.
    uow.sessions.append_event(
        training_session,
        "session_completed",
        "session",
        {"reason": "all_stages_passed" if all_stages_passed else "scenario_duration_reached"},
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
