from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.versioning import PublicationStatus
from app.infrastructure.db.models import Equipment, InstallationVersion, ScenarioVersion, TopologyEdge


class CatalogRepository:
    """Чтение опубликованных версий установки и сценария."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_published_scenarios(self) -> Sequence[ScenarioVersion]:
        query = (
            select(ScenarioVersion)
            .where(ScenarioVersion.status == PublicationStatus.PUBLISHED)
            .order_by(ScenarioVersion.scenario_code, ScenarioVersion.version)
        )
        return (await self._session.scalars(query)).all()

    async def get_scenario(self, scenario_version_id: str) -> ScenarioVersion | None:
        query = (
            select(ScenarioVersion)
            .where(ScenarioVersion.id == scenario_version_id)
            .options(selectinload(ScenarioVersion.levels), selectinload(ScenarioVersion.stages))
        )
        scenario: ScenarioVersion | None = await self._session.scalar(query)
        return scenario

    async def get_installation(self, installation_version_id: str) -> InstallationVersion | None:
        installation: InstallationVersion | None = await self._session.get(
            InstallationVersion, installation_version_id
        )
        return installation

    async def list_equipment(self, installation_version_id: str) -> Sequence[Equipment]:
        query = (
            select(Equipment)
            .where(Equipment.installation_version_id == installation_version_id)
            .options(selectinload(Equipment.tags))
            .order_by(Equipment.code)
        )
        return (await self._session.scalars(query)).all()

    async def list_topology_edges(self, installation_version_id: str) -> Sequence[TopologyEdge]:
        query = (
            select(TopologyEdge)
            .where(TopologyEdge.installation_version_id == installation_version_id)
            .order_by(TopologyEdge.stream_code)
        )
        return (await self._session.scalars(query)).all()
