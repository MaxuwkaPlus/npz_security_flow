"""Проверка доступа к конкретному прохождению.

Права на «любую сессию» проверяются зависимостью в API-слое, а здесь решается то,
что зависимость решить не может: принадлежит ли ресурс субъекту. Правило берётся из
домена, модуль лишь достаёт владельца прохождения и переводит отказ в ошибку.
"""

from app.core.errors import ForbiddenError, NotFoundError
from app.domain.rbac import (
    Permission,
    Principal,
    can_assign_session,
    can_control_session,
    can_operate_session,
    can_read_report,
    can_read_session,
)
from app.infrastructure.db.models import TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork


async def authorize_session_read(uow: UnitOfWork, principal: Principal, session_id: str) -> TrainingSession:
    """Читать прохождение может его оператор или тот, кому доступна любая сессия."""

    training_session = await _require_session(uow, session_id)
    if not can_read_session(principal, training_session.operator_id):
        raise _denied(Permission.SESSION_READ_ANY, session_id)
    return training_session


async def authorize_session_operate(
    uow: UnitOfWork, principal: Principal, session_id: str
) -> TrainingSession:
    """За пультом работает только тот обучаемый, которому назначена сессия.

    Инструктор ведёт прохождение командами жизненного цикла, но не подаёт команды
    на установку вместо оператора: иначе журнал перестанет отвечать, чей это навык.
    """

    training_session = await _require_session(uow, session_id)
    if not can_operate_session(principal, training_session.operator_id):
        raise _denied(Permission.SESSION_OPERATE, session_id)
    return training_session


async def authorize_session_control(
    uow: UnitOfWork, principal: Principal, session_id: str
) -> TrainingSession:
    """Ход прохождения ведёт инструктор, а самостоятельный обучаемый — только своё."""

    training_session = await _require_session(uow, session_id)
    if not can_control_session(principal, training_session.operator_id):
        raise _denied(Permission.SESSION_CONTROL, session_id)
    return training_session


def authorize_session_assign(principal: Principal, operator_id: str) -> None:
    """Завести прохождение чужим именем может только тот, кто ведёт чужое обучение."""

    if not can_assign_session(principal, operator_id):
        raise _denied(Permission.SESSION_CONTROL, operator_id)


async def authorize_report_read(uow: UnitOfWork, principal: Principal, session_id: str) -> TrainingSession:
    """Свой отчёт доступен обучаемому, чужой — по праву на любой отчёт."""

    training_session = await _require_session(uow, session_id)
    if not can_read_report(principal, training_session.operator_id):
        raise _denied(Permission.REPORT_READ_ANY, session_id)
    return training_session


def authorize_operator_reports(principal: Principal, operator_id: str) -> None:
    """Доступ к сводке по оператору целиком, а не по одному прохождению."""

    if not can_read_report(principal, operator_id):
        raise _denied(Permission.REPORT_READ_ANY, operator_id)


def _denied(permission: Permission, resource: str) -> ForbiddenError:
    # Существование чужой сессии не скрывается: идентификатор клиент и так знает,
    # а подмена 403 на 404 усложнила бы разбор инцидента.
    return ForbiddenError(
        "FORBIDDEN",
        "Недостаточно прав для этого действия",
        {"required_any_of": [permission.value], "resource": resource},
    )


async def _require_session(uow: UnitOfWork, session_id: str) -> TrainingSession:
    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    return training_session
