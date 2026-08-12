"""Приём команд оператора.

Команда только принимается или отклоняется. Применение выполняет следующий tick —
единственный последовательный владелец состояния сессии (§12). Оценка эффекта
появляется ещё позже, поэтому синтаксически допустимая команда не считается правильной.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.application.runtime_config import control_policy
from app.core.errors import ConflictError, NotFoundError
from app.domain.commands import ActionClassification, ActionStatus, RejectionReason
from app.domain.sessions import SessionStatus, accepts_operator_input
from app.infrastructure.db.models import OperatorAction, ScenarioVersion, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    """Ответ подтверждает только принятие или отклонение, но не правильность команды."""

    id: str
    request_id: str
    session_id: str
    sequence_no: int
    sim_time_ms: int
    action_type: str
    target_code: str
    value: dict[str, float]
    status: ActionStatus
    rejection_reason: str | None


async def submit_action(
    uow: UnitOfWork,
    session_id: str,
    *,
    request_id: str,
    action_type: str,
    target_code: str,
    value: Mapping[str, float] | None = None,
) -> ActionReceipt:
    existing = await uow.sessions.find_action(request_id)
    if existing is not None:
        if existing.session_id != session_id:
            raise ConflictError(
                "REQUEST_ID_ALREADY_USED",
                "Этот request_id уже использован в другой сессии",
                {"request_id": request_id},
            )
        return _receipt(existing)

    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    status = SessionStatus(training_session.status)
    if not accepts_operator_input(status):
        raise ConflictError(
            "SESSION_NOT_RUNNING",
            "Команды оператора принимаются только на идущей сессии",
            {"status": status.value},
        )

    requested_value = dict(value or {})
    scenario = await _load_scenario(uow, training_session)
    rejection = control_policy(scenario).check(action_type, target_code, requested_value)

    action = uow.sessions.add_action(
        training_session,
        action_type=action_type,
        target_code=target_code,
        request_id=request_id,
        requested_value=requested_value,
        status=ActionStatus.REJECTED if rejection else ActionStatus.ACCEPTED,
        rejection_reason=rejection.value if rejection else None,
    )
    # Идентификатор нужен событию как aggregate_id, поэтому действие сбрасывается в БД сразу.
    await uow.flush()
    uow.sessions.append_event(
        training_session,
        "action_rejected" if rejection else "action_accepted",
        "operator_action",
        _event_payload(action, rejection),
        aggregate_id=action.id,
        correlation_id=request_id,
    )
    action.sequence_no = training_session.last_sequence_no
    return _receipt(action)


async def cancel_action(uow: UnitOfWork, session_id: str, action_id: str) -> ActionReceipt:
    """Отменяет принятую команду. Применённую отменить уже нельзя — только скомпенсировать."""

    action = await uow.sessions.get_action(action_id)
    if action is None or action.session_id != session_id:
        raise NotFoundError("ACTION_NOT_FOUND", "Команда не найдена")
    if action.status == ActionStatus.CANCELLED:
        return _receipt(action)
    if action.status != ActionStatus.ACCEPTED:
        raise ConflictError(
            "ACTION_ALREADY_RESOLVED",
            "Команду можно отменить только до её применения",
            {"status": action.status},
        )

    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    action.status = ActionStatus.CANCELLED
    action.classification = ActionClassification.CANCELLED
    uow.sessions.append_event(
        training_session,
        "action_cancelled",
        "operator_action",
        {"action_type": action.action_type, "target_code": action.target_code},
        aggregate_id=action.id,
    )
    return _receipt(action)


async def _load_scenario(uow: UnitOfWork, training_session: TrainingSession) -> ScenarioVersion:
    scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария сессии не найдена")
    return scenario


def _event_payload(action: OperatorAction, rejection: RejectionReason | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action_type": action.action_type,
        "target_code": action.target_code,
        "value": action.requested_value_json,
    }
    if rejection is not None:
        payload["rejection_reason"] = rejection.value
    return payload


def _receipt(action: OperatorAction) -> ActionReceipt:
    return ActionReceipt(
        id=action.id,
        request_id=action.request_id,
        session_id=action.session_id,
        sequence_no=action.sequence_no,
        sim_time_ms=action.sim_time_ms,
        action_type=action.action_type,
        target_code=action.target_code,
        # Значение возвращается оператору обратно: так видно, каким сервер его принял.
        value={name: float(value) for name, value in action.requested_value_json.items()},
        status=ActionStatus(action.status),
        rejection_reason=action.rejection_reason,
    )
