from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

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
