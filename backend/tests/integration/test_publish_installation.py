from sqlalchemy import func, select

from app.application.configuration import publish_installation
from app.domain.versioning import PublicationStatus
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import Equipment, InstallationVersion, ProcessTag, TopologyEdge
from app.infrastructure.seed.installation import BRANCH_CONTROLLERS, build_installation_spec


async def test_publish_creates_equipment_tags_and_topology(database: Database) -> None:
    spec = build_installation_spec()

    async with database.session_factory() as session, session.begin():
        installation = await publish_installation(session, spec)

    async with database.session_factory() as session:
        equipment_count = await session.scalar(select(func.count()).select_from(Equipment))
        edge_count = await session.scalar(select(func.count()).select_from(TopologyEdge))
        tag_codes = set((await session.scalars(select(ProcessTag.code))).all())

    assert installation.status == PublicationStatus.PUBLISHED
    assert installation.published_at is not None
    assert equipment_count == len(spec.equipment)
    assert edge_count == len(spec.edges)
    assert {"branch_1_flow_tph", "branch_2_flow_tph", "branch_3_flow_tph"} <= tag_codes
    assert "elou_stage1_min_level_mm" in tag_codes


async def test_publish_is_idempotent(database: Database) -> None:
    spec = build_installation_spec()

    async with database.session_factory() as session, session.begin():
        first = await publish_installation(session, spec)
    async with database.session_factory() as session, session.begin():
        second = await publish_installation(session, spec)

    async with database.session_factory() as session:
        versions = await session.scalar(select(func.count()).select_from(InstallationVersion))
        equipment_count = await session.scalar(select(func.count()).select_from(Equipment))

    assert first.id == second.id
    assert versions == 1
    assert equipment_count == len(spec.equipment)


async def test_branch_controllers_are_linked_to_their_heat_exchanger_chains(database: Database) -> None:
    async with database.session_factory() as session, session.begin():
        await publish_installation(session, build_installation_spec())

    async with database.session_factory() as session:
        source = select(TopologyEdge).join(Equipment, TopologyEdge.from_equipment_id == Equipment.id)
        for branch_no, controller_code in BRANCH_CONTROLLERS.items():
            edges = (
                await session.scalars(
                    source.where(Equipment.code == controller_code, TopologyEdge.branch_no == branch_no)
                )
            ).all()
            assert len(edges) == 1
