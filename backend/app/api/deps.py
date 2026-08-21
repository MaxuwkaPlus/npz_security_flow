from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.params import Depends as DependsMarker
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth import resolve_principal
from app.core.errors import ForbiddenError, UnauthenticatedError
from app.domain.rbac import Permission, Principal
from app.infrastructure.db.engine import Database
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.runtime.session_runner import SessionRunner


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


DatabaseDep = Annotated[Database, Depends(get_database)]


async def get_session(database: DatabaseDep) -> AsyncIterator[AsyncSession]:
    async with database.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_unit_of_work(database: DatabaseDep) -> AsyncIterator[UnitOfWork]:
    """Транзакция на запрос: успех — commit, любое исключение — rollback."""

    async with UnitOfWork(database.session_factory) as uow:
        yield uow


UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_unit_of_work)]


def get_session_runner(request: Request) -> SessionRunner:
    runner: SessionRunner = request.app.state.session_runner
    return runner


SessionRunnerDep = Annotated[SessionRunner, Depends(get_session_runner)]


# Схема объявлена явно, а не читается из заголовка вручную: иначе требование токена
# не попадает в OpenAPI, и на странице /docs нет кнопки Authorize. `auto_error=False`
# оставляет форму ответа за обработчиками приложения.
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="Токен доступа",
    description="Значение access_token из POST /auth/login",
)
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


async def get_principal(request: Request, session: SessionDep, credentials: CredentialsDep) -> Principal:
    """Субъект запроса по токену из заголовка `Authorization: Bearer`.

    Кладётся в `request.state`, чтобы обработчик отказа мог записать в журнал
    безопасности, кому именно отказано.
    """

    token = credentials.credentials.strip() if credentials else ""
    if not token:
        raise UnauthenticatedError("MISSING_TOKEN", "Требуется вход в систему")

    principal = await resolve_principal(session, token)
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require(*permissions: Permission) -> DependsMarker:
    """Требует хотя бы одно из перечисленных прав.

    Проверка живёт в API-слое, но решение принимает домен: здесь только перевод
    отказа в HTTP-ответ. Отказ обязательно попадает в журнал — это делает
    обработчик `ForbiddenError`.
    """

    async def guard(principal: PrincipalDep) -> Principal:
        if principal.has_any(*permissions):
            return principal
        raise ForbiddenError(
            "FORBIDDEN",
            "Недостаточно прав для этого действия",
            {"required_any_of": sorted(permission.value for permission in permissions)},
        )

    # FastAPI типизирует Depends как Any; для строгого mypy возвращаем маркер явно.
    return cast(DependsMarker, Depends(guard))


def bearer_token(header: str | None) -> str | None:
    """Извлекает токен из заголовка Authorization. Схема сравнивается без регистра."""

    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()
