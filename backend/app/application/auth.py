"""Вход, проверка токена и выход.

Решение о доступе принимает домен (`app.domain.rbac`), этот модуль лишь превращает
учётную запись в субъекта и фиксирует событие в журнале безопасности.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, UnauthenticatedError
from app.domain.audit import Outcome, SecurityEventType
from app.domain.rbac import Principal, Role
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import User
from app.infrastructure.db.types import utcnow
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.repositories.identity import IdentityRepository, to_principal
from app.infrastructure.security.passwords import hash_password, verify_password
from app.infrastructure.security.tokens import hash_token, issue_token

logger = logging.getLogger(__name__)

# Проверка пароля несуществующей учётной записи выполняется по этому образцу.
# Без неё время ответа выдавало бы, существует логин или нет.
_DUMMY_HASH = hash_password("несуществующая учётная запись")

# Префикс гостевого логина. По нему запись отличается от заведённой администратором
# и в журнале, и в списке учётных записей.
GUEST_USERNAME_PREFIX = "guest-"


@dataclass(frozen=True)
class LoginResult:
    token: str
    expires_at: datetime
    principal: Principal
    username: str
    display_name: str


async def login(
    uow: UnitOfWork,
    database: Database,
    *,
    username: str,
    password: str,
    ttl_minutes: int,
    request_id: str | None = None,
) -> LoginResult:
    """Проверяет пароль и выдаёт токен доступа.

    Причина отказа наружу не уточняется: «нет такого логина», «неверный пароль» и
    «учётная запись отключена» дают один и тот же ответ, а подробность остаётся в журнале.
    """

    repository = uow.identity
    user = await repository.get_user_by_username(username)

    if user is None or not user.is_active:
        verify_password(password, _DUMMY_HASH)
        await _record_failure(
            database,
            username=username,
            user_id=user.id if user else None,
            reason="inactive" if user else "unknown_user",
            request_id=request_id,
        )
        raise UnauthenticatedError("INVALID_CREDENTIALS", "Неверный логин или пароль")

    if not verify_password(password, user.password_hash):
        await _record_failure(
            database,
            username=username,
            user_id=user.id,
            reason="bad_password",
            request_id=request_id,
        )
        raise UnauthenticatedError("INVALID_CREDENTIALS", "Неверный логин или пароль")

    token, token_hash = issue_token()
    expires_at = utcnow() + timedelta(minutes=ttl_minutes)
    repository.add_auth_session(user, token_hash, expires_at)
    user.last_login_at = utcnow()

    principal = to_principal(user)
    repository.record_event(
        SecurityEventType.LOGIN,
        outcome=Outcome.SUCCESS,
        actor_user_id=user.id,
        actor_username=user.username,
        request_id=request_id,
        payload={"roles": sorted(role.value for role in principal.roles)},
    )
    return LoginResult(
        token=token,
        expires_at=expires_at,
        principal=principal,
        username=user.username,
        display_name=user.display_name,
    )


async def start_guest(
    uow: UnitOfWork,
    *,
    enabled: bool,
    ttl_minutes: int,
    request_id: str | None = None,
) -> LoginResult:
    """Выдаёт токен самостоятельного прохождения — вход без проверки личности.

    Учётная запись всё равно заводится: без неё прохождение не к кому привязать, а
    «своя сессия» перестала бы быть проверяемым понятием. Пароля у неё нет —
    хеш строится от случайного значения, которое никто не узнает, поэтому войти
    под гостем по логину нельзя, только по выданному здесь токену.
    """

    if not enabled:
        raise ForbiddenError(
            "GUEST_ACCESS_DISABLED",
            "Самостоятельное прохождение отключено, требуется вход по учётной записи",
        )

    username = f"{GUEST_USERNAME_PREFIX}{secrets.token_hex(4)}"
    user = User(
        username=username,
        display_name="Оператор (без входа)",
        password_hash=hash_password(secrets.token_urlsafe(32)),
    )
    uow.identity.add_user(user)
    await uow.flush()
    uow.identity.grant_role(user, Role.GUEST, granted_by=None)
    await uow.flush()
    await uow.session.refresh(user, ["roles"])

    token, token_hash = issue_token()
    expires_at = utcnow() + timedelta(minutes=ttl_minutes)
    uow.identity.add_auth_session(user, token_hash, expires_at)
    user.last_login_at = utcnow()

    principal = to_principal(user)
    uow.identity.record_event(
        SecurityEventType.GUEST_SESSION,
        outcome=Outcome.SUCCESS,
        actor_user_id=user.id,
        actor_username=user.username,
        request_id=request_id,
        payload={"roles": sorted(role.value for role in principal.roles)},
    )
    return LoginResult(
        token=token,
        expires_at=expires_at,
        principal=principal,
        username=user.username,
        display_name=user.display_name,
    )


async def _record_failure(
    database: Database,
    *,
    username: str,
    user_id: str | None,
    reason: str,
    request_id: str | None,
) -> None:
    """Пишет неудачный вход отдельной транзакцией.

    Транзакция запроса откатится вместе с исключением и унесла бы запись с собой, а
    именно эти события нужны для разбора подбора пароля. Пароль в журнал не попадает.
    """

    async with UnitOfWork(database.session_factory) as failure_uow:
        failure_uow.identity.record_event(
            SecurityEventType.LOGIN,
            outcome=Outcome.FAILURE,
            actor_user_id=user_id,
            actor_username=username,
            request_id=request_id,
            payload={"reason": reason},
        )


async def resolve_principal(session: AsyncSession, token: str) -> Principal:
    """Возвращает субъекта по токену; истёкший и отозванный токен недействительны."""

    repository = IdentityRepository(session)
    auth_session = await repository.get_active_auth_session(hash_token(token))
    if auth_session is None:
        raise UnauthenticatedError("INVALID_TOKEN", "Токен недействителен или истёк")

    user = await repository.get_user(auth_session.user_id)
    if user is None or not user.is_active:
        raise UnauthenticatedError("INVALID_TOKEN", "Токен недействителен или истёк")
    return to_principal(user)


async def logout(uow: UnitOfWork, principal: Principal, token: str, *, request_id: str | None = None) -> None:
    """Отзывает текущий токен. Повторный выход не считается ошибкой."""

    revoked = await uow.identity.revoke_auth_session(hash_token(token))
    if revoked:
        uow.identity.record_event(
            SecurityEventType.LOGOUT,
            outcome=Outcome.SUCCESS,
            actor_user_id=principal.user_id,
            actor_username=principal.subject_id,
            request_id=request_id,
        )
