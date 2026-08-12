"""Тревоги сессии: расчёт по правилам версии сценария и подтверждение оператором."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError
from app.domain.alarms import AlarmRule, AlarmState, evaluate
from app.domain.nuisance import NuisancePolicy
from app.domain.rules import parse_rule
from app.domain.sessions import SessionStatus, accepts_operator_input
from app.infrastructure.db.models import AlarmRule as AlarmRuleRow
from app.infrastructure.db.models import SessionAlarm, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork

ALARM_RUNTIME_KEY = "alarms"


@dataclass(frozen=True, slots=True)
class AlarmView:
    id: str
    alarm_code: str
    level: str
    equipment_code: str
    message: str
    state: AlarmState
    started_sim_time_ms: int
    acknowledged_sim_time_ms: int | None
    cleared_sim_time_ms: int | None
    is_nuisance: bool


async def load_alarm_rules(uow: UnitOfWork, scenario_version_id: str) -> list[tuple[str, AlarmRule]]:
    """Правила тревог опубликованной версии сценария вместе с их идентификаторами."""

    query = (
        select(AlarmRuleRow)
        .where(AlarmRuleRow.scenario_version_id == scenario_version_id)
        .order_by(AlarmRuleRow.code)
    )
    rows = (await uow.session.scalars(query)).all()
    return [
        (
            row.id,
            AlarmRule(
                code=row.code,
                level=row.level,
                equipment_code=row.equipment_code,
                trigger=parse_rule(row.source_expression_json),
                clear=parse_rule(row.clear_expression_json),
                activation_delay_ms=row.activation_delay_ms,
                ack_required=row.ack_required,
                message=row.message_template,
            ),
        )
        for row in rows
    ]


async def refresh_alarms(
    uow: UnitOfWork,
    training_session: TrainingSession,
    rules: Sequence[tuple[str, AlarmRule]],
    metrics: Mapping[str, float],
    pending_since: Mapping[str, int],
    nuisance: NuisancePolicy | None = None,
    tick_interval_ms: int = 1_000,
) -> dict[str, int]:
    """Включает и снимает тревоги по правилам. Возвращает новое состояние таймеров."""

    active = await uow.sessions.active_alarms(training_session.id)
    _clear_expired_nuisance(uow, training_session, active, nuisance)
    decision = evaluate(
        [rule for _, rule in rules],
        metrics,
        active_codes={alarm.alarm_code for alarm in active},
        pending_since=pending_since,
        sim_time_ms=training_session.sim_time_ms,
    )

    rules_by_code = {rule.code: (rule_id, rule) for rule_id, rule in rules}
    for code in decision.raised:
        rule_id, rule = rules_by_code[code]
        alarm = uow.sessions.raise_alarm(
            training_session,
            alarm_rule_id=rule_id,
            alarm_code=rule.code,
            level=rule.level,
            equipment_code=rule.equipment_code,
            message=rule.message,
            ack_required=rule.ack_required,
        )
        event = uow.sessions.append_event(
            training_session,
            "alarm_raised",
            "alarm",
            {"alarm_code": rule.code, "level": rule.level, "equipment_code": rule.equipment_code},
        )
        await uow.flush()
        alarm.source_event_id = event.id

    active_by_code = {alarm.alarm_code: alarm for alarm in active}
    for code in decision.cleared:
        # Вторичная тревога снимается физикой процесса, а не удалением записи.
        alarm = active_by_code[code]
        alarm.cleared_sim_time_ms = training_session.sim_time_ms
        uow.sessions.append_event(
            training_session,
            "alarm_cleared",
            "alarm",
            {"alarm_code": code},
            aggregate_id=alarm.id,
        )

    if nuisance is not None:
        _raise_due_nuisance(uow, training_session, active, nuisance, tick_interval_ms)
    return dict(decision.pending_since)


def _clear_expired_nuisance(
    uow: UnitOfWork,
    training_session: TrainingSession,
    active: Sequence[SessionAlarm],
    nuisance: NuisancePolicy | None,
) -> None:
    """Второстепенная тревога живёт заданное время и гаснет сама."""

    if nuisance is None:
        return
    for alarm in active:
        if not alarm.is_nuisance or alarm.cleared_sim_time_ms is not None:
            continue
        if training_session.sim_time_ms - alarm.started_sim_time_ms >= nuisance.duration_ms:
            alarm.cleared_sim_time_ms = training_session.sim_time_ms
            uow.sessions.append_event(
                training_session,
                "alarm_cleared",
                "alarm",
                {"alarm_code": alarm.alarm_code, "is_nuisance": True},
                aggregate_id=alarm.id,
            )


def _raise_due_nuisance(
    uow: UnitOfWork,
    training_session: TrainingSession,
    active: Sequence[SessionAlarm],
    nuisance: NuisancePolicy,
    tick_interval_ms: int,
) -> None:
    active_codes = [
        alarm.alarm_code for alarm in active if alarm.is_nuisance and alarm.cleared_sim_time_ms is None
    ]
    due = nuisance.due(
        training_session.random_seed, training_session.sim_time_ms, tick_interval_ms, active_codes
    )
    if due is None:
        return
    alarm = uow.sessions.raise_alarm(
        training_session,
        alarm_rule_id=None,
        alarm_code=due.code,
        level=nuisance.level,
        equipment_code=due.equipment_code,
        message=due.message,
        ack_required=True,
        is_nuisance=True,
    )
    event = uow.sessions.append_event(
        training_session,
        "alarm_raised",
        "alarm",
        {"alarm_code": due.code, "level": nuisance.level, "is_nuisance": True},
    )
    alarm.source_event_id = event.id


async def acknowledge_alarm(
    uow: UnitOfWork, session_id: str, alarm_id: str, *, operator_id: str
) -> AlarmView:
    """Подтверждение идемпотентно: повтор не меняет момент подтверждения."""

    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    status = SessionStatus(training_session.status)
    if not accepts_operator_input(status):
        raise ConflictError(
            "SESSION_NOT_RUNNING",
            "Тревоги подтверждаются только на идущей сессии",
            {"status": status.value},
        )

    alarm = await uow.sessions.get_alarm(alarm_id)
    if alarm is None or alarm.session_id != session_id:
        raise NotFoundError("ALARM_NOT_FOUND", "Тревога не найдена")

    if alarm.acknowledged_sim_time_ms is None:
        alarm.acknowledged_sim_time_ms = training_session.sim_time_ms
        alarm.acknowledged_by_operator_id = operator_id
        uow.sessions.append_event(
            training_session,
            "alarm_acknowledged",
            "alarm",
            {"alarm_code": alarm.alarm_code},
            aggregate_id=alarm.id,
        )
    return alarm_view(alarm)


async def list_alarms(uow: UnitOfWork, session_id: str) -> list[AlarmView]:
    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    return [alarm_view(alarm) for alarm in await uow.sessions.active_alarms(session_id)]


def alarm_view(alarm: SessionAlarm) -> AlarmView:
    if alarm.cleared_sim_time_ms is not None:
        state = AlarmState.CLEARED
    elif alarm.acknowledged_sim_time_ms is not None:
        state = AlarmState.ACTIVE_ACKNOWLEDGED
    else:
        state = AlarmState.ACTIVE_UNACKNOWLEDGED
    return AlarmView(
        id=alarm.id,
        alarm_code=alarm.alarm_code,
        level=alarm.level,
        equipment_code=alarm.equipment_code,
        message=alarm.message,
        state=state,
        started_sim_time_ms=alarm.started_sim_time_ms,
        acknowledged_sim_time_ms=alarm.acknowledged_sim_time_ms,
        cleared_sim_time_ms=alarm.cleared_sim_time_ms,
        is_nuisance=alarm.is_nuisance,
    )
