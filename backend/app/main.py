from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.realtime import router as realtime_router
from app.api.v1.router import api_router
from app.api.v1.tags import TAGS_METADATA
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.infrastructure.db.engine import Database
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
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(realtime_router, prefix="/ws/v1")
    return app


app = create_app()
