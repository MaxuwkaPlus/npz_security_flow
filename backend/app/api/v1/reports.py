"""Итоговый отчёт и сравнение уровней оператора."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import UnitOfWorkDep
from app.application.reports import build_report, level_comparison

router = APIRouter(tags=["reports"])


@router.get("/sessions/{session_id}/report")
async def get_session_report(session_id: str, uow: UnitOfWorkDep) -> dict[str, Any]:
    """Отчёт пересобирается из журнала, поэтому всегда соответствует текущим правилам."""

    return await build_report(uow, session_id)


@router.get("/operators/{operator_id}/level-comparison")
async def get_level_comparison(operator_id: str, uow: UnitOfWorkDep) -> dict[str, Any]:
    return await level_comparison(uow, operator_id)
