from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import DatabaseDep
from app.api.v1.tags import SERVICE

router = APIRouter(tags=[SERVICE])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse, summary="Живость сервиса")
async def health() -> HealthResponse:
    """Живость процесса; внешние зависимости не проверяются."""

    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, summary="Готовность сервиса")
async def ready(database: DatabaseDep) -> HealthResponse:
    """Готовность обслуживать запросы: проверяется соединение с БД."""

    async with database.session_factory() as session:
        await session.execute(text("SELECT 1"))
    return HealthResponse(status="ready")
