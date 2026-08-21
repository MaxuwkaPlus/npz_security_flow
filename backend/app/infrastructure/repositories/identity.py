"""Доступ к учётным записям, ролям, сеансам и журналу безопасности."""

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.rbac import Principal, Role
from app.infrastructure.db.models import AuthSession, SecurityEvent, User, UserRoleAssignment
from app.infrastructure.db.types import utcnow

logger = logging.getLogger(__name__)


class IdentityRepository:
    """Учётные записи и всё, что относится к доступу."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- учётные записи -------------------------------------------------

    def add_user(self, user: User) -> None:
        self._session.add(user)

    async def get_user(self, user_id: str) -> User | None:
        user: User | None = await self._session.get(User, user_id)
        return user

    async def get_user_by_username(self, username: str) -> User | None:
        statement = select(User).where(User.username == username)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_users(self) -> Sequence[User]:
        statement = select(User).order_by(User.username)
        return (await self._session.execute(statement)).scalars().all()

    # --- роли -----------------------------------------------------------

    def grant_role(self, user: User, role: Role, *, granted_by: str | None) -> UserRoleAssignment:
        assignment = UserRoleAssignment(user_id=user.id, role=role.value, granted_by=granted_by)
        self._session.add(assignment)
        return assignment

    async def revoke_role(self, user: User, role: Role) -> bool:
        statement = select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user.id, UserRoleAssignment.role == role.value
        )
        assignment = (await self._session.execute(statement)).scalar_one_or_none()
        if assignment is None:
            return False
        await self._session.delete(assignment)
        return True

    # --- сеансы ---------------------------------------------------------

    def add_auth_session(self, user: User, token_hash: str, expires_at: datetime) -> AuthSession:
        auth_session = AuthSession(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
        self._session.add(auth_session)
        return auth_session

    async def get_active_auth_session(
        self, token_hash: str, *, now: datetime | None = None
    ) -> AuthSession | None:
        moment = now or utcnow()
        statement = select(AuthSession).where(AuthSession.token_hash == token_hash)
        auth_session = (await self._session.execute(statement)).scalar_one_or_none()
        if auth_session is None:
            return None
        if auth_session.revoked_at is not None or auth_session.expires_at <= moment:
            return None
        return auth_session

    async def revoke_auth_session(self, token_hash: str) -> bool:
        statement = select(AuthSession).where(AuthSession.token_hash == token_hash)
        auth_session = (await self._session.execute(statement)).scalar_one_or_none()
        if auth_session is None or auth_session.revoked_at is not None:
            return False
        auth_session.revoked_at = utcnow()
        return True

    async def revoke_user_sessions(self, user: User) -> int:
        statement = select(AuthSession).where(
            AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
        )
        moment = utcnow()
        revoked = 0
        for auth_session in (await self._session.execute(statement)).scalars().all():
            auth_session.revoked_at = moment
            revoked += 1
        return revoked

    # --- журнал безопасности --------------------------------------------

    def record_event(
        self,
        event_type: str,
        *,
        outcome: str,
        actor_user_id: str | None = None,
        actor_username: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        request_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> SecurityEvent:
        event = SecurityEvent(
            event_type=event_type,
            outcome=outcome,
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            payload_json=payload or {},
        )
        self._session.add(event)
        return event

    async def list_events(
        self,
        *,
        event_type: str | None = None,
        actor_username: str | None = None,
        limit: int = 100,
    ) -> Sequence[SecurityEvent]:
        statement = select(SecurityEvent).order_by(SecurityEvent.occurred_at.desc(), SecurityEvent.id.desc())
        if event_type is not None:
            statement = statement.where(SecurityEvent.event_type == event_type)
        if actor_username is not None:
            statement = statement.where(SecurityEvent.actor_username == actor_username)
        return (await self._session.execute(statement.limit(limit))).scalars().all()


def to_principal(user: User) -> Principal:
    """Переводит запись из базы в доменного субъекта.

    Неизвестное значение роли пропускается, а не роняет запрос: снятая из матрицы роль
    не должна закрывать вход, но и прав по ней не будет.
    """

    roles: set[Role] = set()
    for assignment in user.roles:
        try:
            roles.add(Role(assignment.role))
        except ValueError:
            logger.warning("unknown_role_skipped", extra={"role": assignment.role, "user_id": user.id})
    return Principal(user_id=user.id, subject_id=user.username, roles=frozenset(roles))
