"""Прикладные сценарии жизненного цикла сессии.

Каждый переход — одна короткая транзакция: проверка предусловий, доменный переход,
запись события и обновление сессии. Логика перехода живёт в домене, транспорт о ней
не знает.
"""

import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.application.runtime_config import twin_config
from app.core.errors import ConflictError, NotFoundError, PreconditionFailedError
from app.domain.disturbance import DisturbanceOption, select_disturbance
from app.domain.sessions import (
    InvalidSessionTransition,
    SessionCommand,
    SessionStatus,
    apply_command,
    is_terminal,
)
from app.domain.twin import initial_state
from app.domain.versioning import PublicationStatus
from app.infrastructure.db.models import ScenarioLevel, ScenarioVersion, ScoringPolicyVersion, TrainingSession
from app.infrastructure.db.types import utcnow
from app.infrastructure.db.unit_of_work import UnitOfWork

FIRST_STAGE_FALLBACK = "precheck"

# Событие фиксируется на каждый реально произошедший переход.
COMMAND_EVENTS = {
    SessionCommand.CONFIRM_CONFIGURATION: "session_ready",
    SessionCommand.START: "session_started",
    SessionCommand.PAUSE: "session_paused",
    SessionCommand.RESUME: "session_resumed",
    SessionCommand.COMPLETE: "session_completed",
    SessionCommand.FAIL: "session_failed",
    SessionCommand.ABORT: "session_aborted",
}


@dataclass(frozen=True)
class SessionState:
    """Безопасное представление сессии: скрытая конфигурация сюда не попадает."""

    id: str
    operator_id: str
    instructor_id: str | None
    scenario_version_id: str
    level_no: int
    status: SessionStatus
    sim_time_ms: int
    sequence_no: int
    current_stage_code: str
    version_no: int
    final_outcome: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operator_id": self.operator_id,
            "instructor_id": self.instructor_id,
            "scenario_version_id": self.scenario_version_id,
            "level_no": self.level_no,
            "status": self.status.value,
            "sim_time_ms": self.sim_time_ms,
            "sequence_no": self.sequence_no,
            "current_stage_code": self.current_stage_code,
            "version_no": self.version_no,
            "final_outcome": self.final_outcome,
        }


async def create_session(
    uow: UnitOfWork,
    *,
    request_id: str,
    operator_id: str,
    scenario_version_id: str,
    level_no: int,
    instructor_id: str | None = None,
    random_seed: int | None = None,
) -> SessionState:
    """Создаёт сессию и фиксирует скрытые параметры возмущения из seed."""

    stored = await uow.sessions.find_command_request(request_id)
    if stored is not None:
        return _state_from_json(stored.response_json)

    scenario = await _load_scenario(uow, scenario_version_id)
    level = _require_level(scenario, level_no)
    policy = await _load_scoring_policy(uow)
    seed = random_seed if random_seed is not None else secrets.randbelow(2**31)

    disturbance = select_disturbance(
        [_to_option(template) for template in scenario.disturbance_templates],
        random_seed=seed,
        development_speed_factor=level.development_speed_factor,
    )
    training_session = TrainingSession(
        operator_id=operator_id,
        instructor_id=instructor_id,
        scenario_version_id=scenario.id,
        scenario_level_id=level.id,
        scoring_policy_version_id=policy.id,
        status=SessionStatus.CREATED,
        current_stage_code=_first_stage_code(scenario),
        random_seed=seed,
        hidden_runtime_config_json={"disturbance": disturbance.to_json()},
        runtime_state_json=initial_state(twin_config(scenario)).to_json(),
    )
    uow.sessions.add(training_session)
    await uow.flush()
    uow.sessions.append_event(
        training_session,
        "session_created",
        "session",
        {"operator_id": operator_id, "scenario_version_id": scenario.id, "level_no": level.level_no},
        correlation_id=request_id,
    )
    # Версии сценария, уровня и политики оценки зафиксированы прямо здесь,
    # поэтому сессия сразу переходит в ready и ждёт запуска инструктором.
    training_session.status = apply_command(
        SessionStatus.CREATED, SessionCommand.CONFIRM_CONFIGURATION
    ).status
    uow.sessions.append_event(
        training_session,
        COMMAND_EVENTS[SessionCommand.CONFIRM_CONFIGURATION],
        "session",
        {"from": SessionStatus.CREATED.value, "to": training_session.status},
        correlation_id=request_id,
    )
    state = _state(training_session, level.level_no)
    uow.sessions.add_command_request(request_id, training_session.id, "create_session", state.to_json())
    return state


async def transition_session(
    uow: UnitOfWork,
    session_id: str,
    command: SessionCommand,
    *,
    request_id: str,
    expected_version: int | None = None,
) -> SessionState:
    """Выполняет переход жизненного цикла. Повторный `request_id` возвращает прежний ответ."""

    stored = await uow.sessions.find_command_request(request_id)
    if stored is not None:
        if stored.session_id != session_id or stored.command != command.value:
            raise ConflictError(
                "REQUEST_ID_ALREADY_USED",
                "Этот request_id уже использован для другой команды",
                {"request_id": request_id},
            )
        return _state_from_json(stored.response_json)

    training_session = await _load_session(uow, session_id)
    _check_expected_version(training_session, expected_version)
    current = SessionStatus(training_session.status)

    try:
        transition = apply_command(current, command)
    except InvalidSessionTransition as error:
        raise ConflictError(
            "SESSION_TRANSITION_NOT_ALLOWED",
            "Команда недопустима в текущем состоянии сессии",
            {"status": current.value, "command": command.value},
        ) from error

    if transition.changed:
        training_session.status = transition.status
        _apply_timestamps(training_session, command)
        uow.sessions.append_event(
            training_session,
            COMMAND_EVENTS[command],
            "session",
            {"from": current.value, "to": transition.status.value},
            correlation_id=request_id,
        )
        if command is SessionCommand.START:
            uow.sessions.open_stage(training_session, training_session.current_stage_code)

    level_no = await _level_no(uow, training_session)
    state = _state(training_session, level_no)
    uow.sessions.add_command_request(request_id, session_id, command.value, state.to_json())
    return state


async def get_session_state(uow: UnitOfWork, session_id: str) -> SessionState:
    training_session = await _load_session(uow, session_id)
    return _state(training_session, await _level_no(uow, training_session))


async def _load_session(uow: UnitOfWork, session_id: str) -> TrainingSession:
    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    return training_session


async def _load_scenario(uow: UnitOfWork, scenario_version_id: str) -> ScenarioVersion:
    query = (
        select(ScenarioVersion)
        .where(ScenarioVersion.id == scenario_version_id)
        .options(
            selectinload(ScenarioVersion.levels),
            selectinload(ScenarioVersion.stages),
            selectinload(ScenarioVersion.disturbance_templates),
        )
    )
    scenario = await uow.session.scalar(query)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария не найдена")
    if scenario.status != PublicationStatus.PUBLISHED:
        raise PreconditionFailedError(
            "SCENARIO_NOT_PUBLISHED", "Сессию можно создать только по опубликованной версии сценария"
        )
    return scenario


async def _load_scoring_policy(uow: UnitOfWork) -> ScoringPolicyVersion:
    query = (
        select(ScoringPolicyVersion)
        .where(ScoringPolicyVersion.status == PublicationStatus.PUBLISHED)
        .order_by(ScoringPolicyVersion.version.desc())
        .limit(1)
    )
    policy = await uow.session.scalar(query)
    if policy is None:
        raise PreconditionFailedError("SCORING_POLICY_NOT_PUBLISHED", "Нет опубликованной политики оценки")
    return policy


def _require_level(scenario: ScenarioVersion, level_no: int) -> ScenarioLevel:
    for level in scenario.levels:
        if level.level_no == level_no:
            return level
    raise NotFoundError("SCENARIO_LEVEL_NOT_FOUND", "Уровень сложности не найден", {"level_no": level_no})


def _first_stage_code(scenario: ScenarioVersion) -> str:
    stages = sorted(scenario.stages, key=lambda stage: stage.order_no)
    return stages[0].code if stages else FIRST_STAGE_FALLBACK


def _to_option(template: Any) -> DisturbanceOption:
    onset = template.onset_rule_json
    return DisturbanceOption(
        code=template.code,
        cause_code=template.cause_code,
        eligible_branches=tuple(template.eligible_targets_json),
        earliest_sim_time_ms=int(onset["earliest_sim_time_ms"]),
        latest_sim_time_ms=int(onset["latest_sim_time_ms"]),
        development=dict(template.development_rule_json),
        recovery=dict(template.recovery_rule_json),
    )


def _check_expected_version(training_session: TrainingSession, expected_version: int | None) -> None:
    if expected_version is not None and expected_version != training_session.version_no:
        raise ConflictError(
            "SESSION_VERSION_MISMATCH",
            "Состояние сессии изменилось: обновите данные и повторите",
            {"expected_version": expected_version, "actual_version": training_session.version_no},
        )


def _apply_timestamps(training_session: TrainingSession, command: SessionCommand) -> None:
    now = utcnow()
    if command is SessionCommand.START:
        training_session.started_at = now
    elif command is SessionCommand.PAUSE:
        training_session.paused_at = now
    elif command is SessionCommand.RESUME:
        training_session.paused_at = None
    elif is_terminal(SessionStatus(training_session.status)):
        training_session.completed_at = now


async def _level_no(uow: UnitOfWork, training_session: TrainingSession) -> int:
    level = await uow.session.get(ScenarioLevel, training_session.scenario_level_id)
    return level.level_no if level is not None else 0


def _state(training_session: TrainingSession, level_no: int) -> SessionState:
    return SessionState(
        id=training_session.id,
        operator_id=training_session.operator_id,
        instructor_id=training_session.instructor_id,
        scenario_version_id=training_session.scenario_version_id,
        level_no=level_no,
        status=SessionStatus(training_session.status),
        sim_time_ms=training_session.sim_time_ms,
        sequence_no=training_session.last_sequence_no,
        current_stage_code=training_session.current_stage_code,
        version_no=training_session.version_no,
        final_outcome=training_session.final_outcome,
    )


def _state_from_json(payload: dict[str, Any]) -> SessionState:
    return SessionState(
        id=payload["id"],
        operator_id=payload["operator_id"],
        instructor_id=payload["instructor_id"],
        scenario_version_id=payload["scenario_version_id"],
        level_no=payload["level_no"],
        status=SessionStatus(payload["status"]),
        sim_time_ms=payload["sim_time_ms"],
        sequence_no=payload["sequence_no"],
        current_stage_code=payload["current_stage_code"],
        version_no=payload["version_no"],
        final_outcome=payload["final_outcome"],
    )
