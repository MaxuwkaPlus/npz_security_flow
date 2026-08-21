import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.realtime import router as realtime_router
from app.api.v1.router import api_router
from app.api.v1.tags import TAGS_METADATA
from app.application.accounts import record_access_denied
from app.core.errors import ForbiddenError, error_body, register_exception_handlers
from app.core.logging import configure_logging, request_id_var
from app.core.middleware import RequestContextMiddleware
from app.infrastructure.db.engine import Database
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.realtime.hub import RealtimeHub
from app.infrastructure.runtime.session_runner import SessionRunner
from app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    hub = RealtimeHub()
    runner = SessionRunner(database, settings.simulation_speed_factor, hub)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Фоновые задачи симуляции отменяются до закрытия пула соединений.
        await runner.stop_all()
        await database.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        openapi_tags=TAGS_METADATA,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.realtime_hub = hub
    app.state.session_runner = runner
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.exception_handler(ForbiddenError)
    async def handle_forbidden(request: Request, exc: ForbiddenError) -> JSONResponse:
        """Отказ в доступе — материал расследования, поэтому он всегда попадает в журнал.

        Запись идёт отдельной транзакцией: транзакция самого запроса откатывается вместе
        с исключением и унесла бы событие с собой.
        """

        try:
            async with UnitOfWork(database.session_factory) as uow:
                await record_access_denied(
                    uow,
                    getattr(request.state, "principal", None),
                    permission=",".join(exc.details.get("required_any_of", [])),
                    resource=f"{request.method} {request.url.path}",
                    request_id=request_id_var.get(),
                )
        # Отказ клиенту важнее, чем запись о нём: сбой журнала не должен открывать доступ.
        except Exception:
            logging.getLogger(__name__).exception("access_denied_not_recorded")
        return JSONResponse(
            status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details)
        )

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(realtime_router, prefix="/ws/v1")
    return app


app = create_app()
