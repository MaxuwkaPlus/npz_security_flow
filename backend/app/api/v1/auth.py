"""Вход, выход и сведения о текущем субъекте."""

from fastapi import APIRouter, Request, status

from app.api.deps import DatabaseDep, PrincipalDep, SessionDep, UnitOfWorkDep, bearer_token
from app.api.v1.schemas.identity import CurrentUserResponse, LoginRequest, TokenResponse
from app.api.v1.tags import ACCESS
from app.application.auth import login, logout, start_guest
from app.core.errors import UnauthenticatedError
from app.core.logging import request_id_var
from app.infrastructure.repositories.identity import IdentityRepository
from app.settings import Settings

router = APIRouter(prefix="/auth", tags=[ACCESS])


@router.post("/login", response_model=TokenResponse, summary="Войти в систему")
async def post_login(
    payload: LoginRequest, request: Request, uow: UnitOfWorkDep, database: DatabaseDep
) -> TokenResponse:
    """Проверяет пароль и выдаёт токен доступа.

    Ответ одинаков для неизвестного логина, неверного пароля и отключённой учётной
    записи: подробность о причине остаётся в журнале безопасности.
    """

    settings: Settings = request.app.state.settings
    result = await login(
        uow,
        database,
        username=payload.username,
        password=payload.password,
        ttl_minutes=settings.auth_token_ttl_minutes,
        request_id=request_id_var.get(),
    )
    # Клиент пойдёт со свежим токеном сразу же, поэтому фиксируем сеанс до ответа.
    await uow.commit()
    return TokenResponse(
        access_token=result.token,
        expires_at=result.expires_at,
        user=CurrentUserResponse.build(result.principal, result.display_name),
    )


@router.post(
    "/guest",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Начать самостоятельное прохождение без входа",
)
async def post_guest(request: Request, uow: UnitOfWorkDep) -> TokenResponse:
    """Выдаёт токен обучаемому, который садится за пульт без учётной записи.

    Прав ровно на своё прохождение: завести, вести и пройти. Чужие сессии, отчёты,
    кабинет эксперта и журнал доступа остаются закрытыми — туда только по входу.
    Факт выдачи попадает в журнал безопасности отдельным кодом события.
    """

    settings: Settings = request.app.state.settings
    result = await start_guest(
        uow,
        enabled=settings.allow_guest_training,
        ttl_minutes=settings.guest_token_ttl_minutes,
        request_id=request_id_var.get(),
    )
    await uow.commit()
    return TokenResponse(
        access_token=result.token,
        expires_at=result.expires_at,
        user=CurrentUserResponse.build(result.principal, result.display_name),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Выйти из системы")
async def post_logout(request: Request, principal: PrincipalDep, uow: UnitOfWorkDep) -> None:
    """Отзывает предъявленный токен. Другие сеансы того же пользователя не затрагиваются."""

    token = bearer_token(request.headers.get("authorization"))
    if token is None:
        raise UnauthenticatedError("MISSING_TOKEN", "Требуется вход в систему")
    await logout(uow, principal, token, request_id=request_id_var.get())


@router.get("/me", response_model=CurrentUserResponse, summary="Текущий пользователь и его права")
async def get_me(principal: PrincipalDep, session: SessionDep) -> CurrentUserResponse:
    """Роли и полный список прав субъекта.

    Клиент использует его, чтобы не показывать заведомо недоступные разделы. Это
    удобство интерфейса, а не проверка доступа: каждая ручка проверяет права сама.
    """

    user = await IdentityRepository(session).get_user(principal.user_id)
    display_name = user.display_name if user else principal.subject_id
    return CurrentUserResponse.build(principal, display_name)
