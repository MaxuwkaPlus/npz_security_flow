"""Учётные записи, роли и журнал безопасности — рабочее место администратора ИБ."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import PrincipalDep, UnitOfWorkDep, require
from app.api.v1.schemas.identity import (
    ChangePasswordRequest,
    CreateUserRequest,
    RoleCatalogResponse,
    RoleRequest,
    SecurityEventResponse,
    SetActiveRequest,
    UserResponse,
)
from app.api.v1.tags import ACCESS, AUDIT
from app.application.accounts import (
    change_password,
    create_user,
    grant_role,
    list_security_events,
    list_users,
    revoke_role,
    set_active,
)
from app.core.logging import request_id_var
from app.domain.rbac import ROLE_PERMISSIONS, Permission, Principal, Role, is_assignable

router = APIRouter()

ManageAccounts = Annotated[Principal, require(Permission.ACCOUNT_MANAGE)]
ReadAudit = Annotated[Principal, require(Permission.AUDIT_READ)]


@router.get("/roles", response_model=list[RoleCatalogResponse], tags=[ACCESS], summary="Матрица ролей")
async def get_roles(_: PrincipalDep) -> list[RoleCatalogResponse]:
    """Роли и их права. Роли следующего цикла показаны, но пока не назначаются."""

    return [
        RoleCatalogResponse(
            role=role.value,
            assignable=is_assignable(role),
            permissions=sorted(permission.value for permission in ROLE_PERMISSIONS[role]),
        )
        for role in Role
    ]


@router.get("/users", response_model=list[UserResponse], tags=[ACCESS], summary="Учётные записи")
async def get_users(_: ManageAccounts, uow: UnitOfWorkDep) -> list[UserResponse]:
    """Список учётных записей с выданными ролями и временем последнего входа."""

    return [UserResponse.from_model(user) for user in await list_users(uow)]


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=[ACCESS],
    summary="Завести учётную запись",
)
async def post_user(
    payload: CreateUserRequest, principal: ManageAccounts, uow: UnitOfWorkDep
) -> UserResponse:
    """Создаёт учётную запись и выдаёт роли.

    Логин совпадает с идентификатором оператора в журнале прохождений, поэтому
    результаты обучения привязываются к учётной записи без отдельного справочника.
    """

    user = await create_user(
        uow,
        principal,
        username=payload.username,
        display_name=payload.display_name,
        password=payload.password,
        roles=payload.roles,
        request_id=request_id_var.get(),
    )
    await uow.flush()
    await uow.session.refresh(user, ["roles"])
    return UserResponse.from_model(user)


@router.post("/users/{user_id}/roles", response_model=UserResponse, tags=[ACCESS], summary="Выдать роль")
async def post_user_role(
    user_id: str, payload: RoleRequest, principal: ManageAccounts, uow: UnitOfWorkDep
) -> UserResponse:
    """Добавляет роль к учётной записи. Повторная выдача той же роли ничего не меняет."""

    user = await grant_role(
        uow, principal, user_id=user_id, role=payload.role, request_id=request_id_var.get()
    )
    await uow.flush()
    await uow.session.refresh(user, ["roles"])
    return UserResponse.from_model(user)


@router.delete(
    "/users/{user_id}/roles/{role}", response_model=UserResponse, tags=[ACCESS], summary="Отозвать роль"
)
async def delete_user_role(
    user_id: str, role: Role, principal: ManageAccounts, uow: UnitOfWorkDep
) -> UserResponse:
    """Отзыв роли немедленно обрывает выданные пользователю токены."""

    user = await revoke_role(uow, principal, user_id=user_id, role=role, request_id=request_id_var.get())
    await uow.flush()
    await uow.session.refresh(user, ["roles"])
    return UserResponse.from_model(user)


@router.post(
    "/users/{user_id}/active",
    response_model=UserResponse,
    tags=[ACCESS],
    summary="Включить или отключить учётную запись",
)
async def post_user_active(
    user_id: str, payload: SetActiveRequest, principal: ManageAccounts, uow: UnitOfWorkDep
) -> UserResponse:
    """Отключение немедленно обрывает сеансы: истечения токена ждать не нужно."""

    user = await set_active(
        uow, principal, user_id=user_id, is_active=payload.is_active, request_id=request_id_var.get()
    )
    await uow.flush()
    return UserResponse.from_model(user)


@router.post(
    "/users/{user_id}/password",
    response_model=UserResponse,
    tags=[ACCESS],
    summary="Задать пароль",
)
async def post_user_password(
    user_id: str, payload: ChangePasswordRequest, principal: ManageAccounts, uow: UnitOfWorkDep
) -> UserResponse:
    """Смена пароля обрывает все сеансы этой учётной записи."""

    user = await change_password(
        uow, principal, user_id=user_id, password=payload.password, request_id=request_id_var.get()
    )
    await uow.flush()
    return UserResponse.from_model(user)


@router.get(
    "/security-events",
    response_model=list[SecurityEventResponse],
    tags=[AUDIT],
    summary="Журнал событий безопасности",
)
async def get_security_events(
    _: ReadAudit,
    uow: UnitOfWorkDep,
    event_type: Annotated[str | None, Query(description="login | access_denied | role_granted …")] = None,
    actor_username: Annotated[str | None, Query(description="Фильтр по учётной записи")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SecurityEventResponse]:
    """Вход, отказы в доступе и изменения учётных записей — от новых к старым."""

    events = await list_security_events(
        uow, event_type=event_type, actor_username=actor_username, limit=limit
    )
    return [SecurityEventResponse.from_model(event) for event in events]
