from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.repositories.catalog import CatalogRepository
from app.infrastructure.repositories.sessions import SessionRepository


class UnitOfWork:
    """Транзакционная граница одного прикладного сценария.

    Один tick или одна команда — одна короткая транзакция. Репозитории живут внутри
    неё и работают с общей SQLAlchemy-сессией.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "UnitOfWork":
        self._session = self._session_factory()
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self.session
        try:
            if exc_type is None:
                await session.commit()
            else:
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork используется вне контекстного менеджера")
        return self._session

    @property
    def sessions(self) -> SessionRepository:
        return SessionRepository(self.session)

    @property
    def catalog(self) -> CatalogRepository:
        return CatalogRepository(self.session)

    async def flush(self) -> None:
        await self.session.flush()
