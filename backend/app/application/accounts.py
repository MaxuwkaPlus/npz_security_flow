"""Управление учётными записями, ролями и чтение журнала безопасности.

Право `account.manage` даёт заводить учётные записи и раздавать роли, но не даёт
читать результаты обучения: это разные разрешения и разные ручки.
"""

from collections.abc import Iterable, Sequence

from app.core.errors import ConflictError, NotFoundError, PreconditionFailedError
from app.domain.audit import Outcome, SecurityEventType
from app.domain.rbac import Principal, Role, is_assignable
from app.infrastructure.db.models import SecurityEvent, User
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.security.passwords import (
    WeakPasswordError,
    hash_password,
    validate_password_policy,
)


async def create_user(
    uow: UnitOfWork,
    actor: Principal,
    *,
    username: str,
    display_name: str,
    password: str,
    roles: Iterable[Role],
    request_id: str | None = None,
) -> User:
    """Заводит учётную запись и сразу выдаёт роли."""

    requested = _assignable(roles)
    if await uow.identity.get_user_by_username(username) is not None:
        raise ConflictError("USERNAME_TAKEN", "Учётная запись с таким логином уже есть")

    _check_password(password)
    user = User(username=username, display_name=display_name, password_hash=hash_password(password))
    uow.identity.add_user(user)
    await uow.flush()

    for role in sorted(requested):
        uow.identity.grant_role(user, role, granted_by=actor.subject_id)

    uow.identity.record_event(
        SecurityEventType.USER_CREATED,
        outcome=Outcome.SUCCESS,
        actor_user_id=actor.user_id,
        actor_username=actor.subject_id,
        target_type="user",
        target_id=user.id,
        request_id=request_id,
        payload={"username": username, "roles": sorted(role.value for role in requested)},
    )
    return user


async def grant_role(
    uow: UnitOfWork,
    actor: Principal,
    *,
    user_id: str,
    role: Role,
    request_id: str | None = None,
) -> User:
    user = await _require_user(uow, user_id)
    _assignable([role])

    if role in {Role(assignment.role) for assignment in user.roles if _known(assignment.role)}:
        return user

    uow.identity.grant_role(user, role, granted_by=actor.subject_id)
    uow.identity.record_event(
        SecurityEventType.ROLE_GRANTED,
        outcome=Outcome.SUCCESS,
        actor_user_id=actor.user_id,
        actor_username=actor.subject_id,
        target_type="user",
        target_id=user.id,
        request_id=request_id,
        payload={"role": role.value},
    )
    return user


async def revoke_role(
    uow: UnitOfWork,
    actor: Principal,
    *,
    user_id: str,
    role: Role,
    request_id: str | None = None,
) -> User:
    """Отзывает роль и обрывает выданные токены.

    Без отзыва токенов снятая роль действовала бы до истечения срока: решение о доступе
    принимается по ролям учётной записи в момент запроса, но кэшировать это нельзя.
    """

    user = await _require_user(uow, user_id)
    if not await uow.identity.revoke_role(user, role):
        return user

    await uow.identity.revoke_user_sessions(user)
    uow.identity.record_event(
        SecurityEventType.ROLE_REVOKED,
        outcome=Outcome.SUCCESS,
        actor_user_id=actor.user_id,
        actor_username=actor.subject_id,
        target_type="user",
        target_id=user.id,
        request_id=request_id,
        payload={"role": role.value},
    )
    return user


async def set_active(
    uow: UnitOfWork,
    actor: Principal,
    *,
    user_id: str,
    is_active: bool,
    request_id: str | None = None,
) -> User:
    """Включает или отключает учётную запись. Отключение немедленно обрывает сеансы."""

    user = await _require_user(uow, user_id)
    if user.is_active == is_active:
        return user

    user.is_active = is_active
    if not is_active:
        await uow.identity.revoke_user_sessions(user)
        uow.identity.record_event(
            SecurityEventType.USER_DEACTIVATED,
            outcome=Outcome.SUCCESS,
            actor_user_id=actor.user_id,
            actor_username=actor.subject_id,
            target_type="user",
            target_id=user.id,
            request_id=request_id,
        )
    return user


async def change_password(
    uow: UnitOfWork,
    actor: Principal,
    *,
    user_id: str,
    password: str,
    request_id: str | None = None,
) -> User:
    """Задаёт новый пароль и обрывает старые сеансы."""

    user = await _require_user(uow, user_id)
    _check_password(password)
    user.password_hash = hash_password(password)
    await uow.identity.revoke_user_sessions(user)
    uow.identity.record_event(
        SecurityEventType.PASSWORD_CHANGED,
        outcome=Outcome.SUCCESS,
        actor_user_id=actor.user_id,
        actor_username=actor.subject_id,
        target_type="user",
        target_id=user.id,
        request_id=request_id,
    )
    return user


async def list_users(uow: UnitOfWork) -> Sequence[User]:
    return await uow.identity.list_users()


async def list_security_events(
    uow: UnitOfWork,
    *,
    event_type: str | None = None,
    actor_username: str | None = None,
    limit: int = 100,
) -> Sequence[SecurityEvent]:
    return await uow.identity.list_events(event_type=event_type, actor_username=actor_username, limit=limit)


async def record_access_denied(
    uow: UnitOfWork,
    principal: Principal | None,
    *,
    permission: str,
    resource: str,
    request_id: str | None = None,
) -> None:
    """Фиксирует отказ в доступе: это основной материал расследования."""

    uow.identity.record_event(
        SecurityEventType.ACCESS_DENIED,
        outcome=Outcome.FAILURE,
        actor_user_id=principal.user_id if principal else None,
        actor_username=principal.subject_id if principal else None,
        target_type="endpoint",
        target_id=resource,
        request_id=request_id,
        payload={"permission": permission},
    )


def _assignable(roles: Iterable[Role]) -> set[Role]:
    requested = set(roles)
    if not requested:
        raise PreconditionFailedError("ROLES_REQUIRED", "Учётной записи нужна хотя бы одна роль")

    postponed = sorted(role.value for role in requested if not is_assignable(role))
    if postponed:
        raise PreconditionFailedError(
            "ROLE_NOT_AVAILABLE",
            "Роль не реализована на текущем этапе",
            {"roles": postponed},
        )
    return requested


def _check_password(password: str) -> None:
    try:
        validate_password_policy(password)
    except WeakPasswordError as error:
        raise PreconditionFailedError("WEAK_PASSWORD", str(error)) from error


def _known(role: str) -> bool:
    return role in {item.value for item in Role}


async def _require_user(uow: UnitOfWork, user_id: str) -> User:
    user = await uow.identity.get_user(user_id)
    if user is None:
        raise NotFoundError("USER_NOT_FOUND", "Учётная запись не найдена")
    return user


__all__ = [
    "change_password",
    "create_user",
    "grant_role",
    "list_security_events",
    "list_users",
    "record_access_denied",
    "revoke_role",
    "set_active",
]
