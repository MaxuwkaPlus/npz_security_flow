import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Ошибка прикладного уровня с машинным кодом и HTTP-статусом."""

    status_code = 400

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class UnauthenticatedError(AppError):
    """Запрос без действительного токена."""

    status_code = 401


class ForbiddenError(AppError):
    """Субъект известен, но права на действие у него нет."""

    status_code = 403


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    """Недопустимый переход состояния или конфликт версии."""

    status_code = 409


class PreconditionFailedError(AppError):
    """Запрос синтаксически корректен, но нарушены предусловия предметной области."""

    status_code = 422


def error_body(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id_var.get(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = {"errors": jsonable_encoder(exc.errors())}
        body = error_body("VALIDATION_ERROR", "Некорректные параметры запроса", details)
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=error_body("HTTP_ERROR", str(exc.detail), {})
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        # Наружу не отдаём тип исключения, трассировку и SQL: только код и request_id.
        logger.exception("unhandled_error")
        return JSONResponse(
            status_code=500, content=error_body("INTERNAL_ERROR", "Внутренняя ошибка сервиса", {})
        )
