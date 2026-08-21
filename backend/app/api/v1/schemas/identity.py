"""DTO входа, учётных записей и журнала безопасности.

Хеш пароля, хеш токена и внутренние идентификаторы сеанса представления здесь не
имеют, поэтому наружу попасть не могут.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.rbac import Principal, Role
from app.infrastructure.db.models import SecurityEvent, User


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: "CurrentUserResponse"


class CurrentUserResponse(BaseModel):
    """Кто вошёл и что ему доступно.

    Права передаются явным списком: фронтенд по нему прячет недоступное, но решение
    всё равно принимает сервер на каждом запросе.
    """

    user_id: str
    username: str
    display_name: str
    roles: list[str]
    permissions: list[str]

    @classmethod
    def build(cls, principal: Principal, display_name: str) -> "CurrentUserResponse":
        return cls(
            user_id=principal.user_id,
            username=principal.subject_id,
            display_name=display_name,
            roles=sorted(role.value for role in principal.roles),
            permissions=sorted(permission.value for permission in principal.permissions),
        )


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    roles: list[Role] = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class SetActiveRequest(BaseModel):
    is_active: bool


class RoleRequest(BaseModel):
    role: Role


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    is_active: bool
    roles: list[str]
    created_at: datetime
    last_login_at: datetime | None

    @classmethod
    def from_model(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            is_active=user.is_active,
            roles=sorted(assignment.role for assignment in user.roles),
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


class RoleCatalogResponse(BaseModel):
    """Матрица ролей и прав — то, что видит администратор ИБ при разборе доступа."""

    role: str
    assignable: bool
    permissions: list[str]


class SecurityEventResponse(BaseModel):
    id: str
    occurred_at: datetime
    event_type: str
    outcome: str
    actor_username: str | None
    target_type: str | None
    target_id: str | None
    request_id: str | None
    payload: dict[str, object]

    @classmethod
    def from_model(cls, event: SecurityEvent) -> "SecurityEventResponse":
        return cls(
            id=event.id,
            occurred_at=event.occurred_at,
            event_type=event.event_type,
            outcome=event.outcome,
            actor_username=event.actor_username,
            target_type=event.target_type,
            target_id=event.target_id,
            request_id=event.request_id,
            payload=dict(event.payload_json),
        )


__all__ = [
    "ChangePasswordRequest",
    "CreateUserRequest",
    "CurrentUserResponse",
    "LoginRequest",
    "RoleCatalogResponse",
    "RoleRequest",
    "SecurityEventResponse",
    "SetActiveRequest",
    "TokenResponse",
    "UserResponse",
]
