"""Итоговый отчёт и сравнение уровней оператора."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import UnitOfWorkDep
from app.api.v1.tags import REPORTS
from app.application.reports import build_report, level_comparison

router = APIRouter(tags=[REPORTS])


@router.get("/sessions/{session_id}/report", summary="Отчёт по сессии")
async def get_session_report(session_id: str, uow: UnitOfWorkDep) -> dict[str, Any]:
    """Итог прохождения: оценка по составляющим, тайминги, разбор команд и тревог, пропущенные
    проверки последствий и словесные выводы.

    Отчёт пересобирается из журнала, поэтому всегда соответствует текущим правилам.
    """

    return await build_report(uow, session_id)


@router.get("/operators/{operator_id}/level-comparison", summary="Сравнение уровней оператора")
async def get_level_comparison(operator_id: str, uow: UnitOfWorkDep) -> dict[str, Any]:
    """Насколько просела результативность оператора при переходе с первого уровня на третий.

    Нужна инструктору: устойчивость навыка видна именно по разнице между лёгкими и сложными
    условиями, а не по одному прохождению.
    """

    return await level_comparison(uow, operator_id)
