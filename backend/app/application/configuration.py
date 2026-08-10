from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.versioning import PublicationStatus
from app.infrastructure.db.models import Equipment, InstallationVersion, ProcessTag, TopologyEdge
from app.infrastructure.db.types import utcnow
from app.infrastructure.seed.specs import EquipmentSpec, InstallationSpec


async def publish_installation(session: AsyncSession, spec: InstallationSpec) -> InstallationVersion:
    """Публикует версию установки. Повторный вызов возвращает существующую версию без изменений."""

    existing = await session.scalar(
        select(InstallationVersion).where(
            InstallationVersion.installation_code == spec.code,
            InstallationVersion.version == spec.version,
        )
    )
    if existing is not None:
        return existing

    installation = InstallationVersion(
        installation_code=spec.code,
        version=spec.version,
        name=spec.name,
        status=PublicationStatus.PUBLISHED,
        config_json=dict(spec.config),
        published_at=utcnow(),
    )
    session.add(installation)
    await session.flush()

    equipment_by_code = {item.code: _build_equipment(installation.id, item) for item in spec.equipment}
    session.add_all(equipment_by_code.values())
    await session.flush()

    # Родитель может быть объявлен позже потомка, поэтому связи проставляются вторым проходом.
    for item in spec.equipment:
        if item.parent_code is not None:
            parent = _require(equipment_by_code, item.parent_code)
            equipment_by_code[item.code].parent_equipment_id = parent.id

    session.add_all(
        TopologyEdge(
            installation_version_id=installation.id,
            from_equipment_id=_require(equipment_by_code, edge.from_code).id,
            to_equipment_id=_require(equipment_by_code, edge.to_code).id,
            stream_code=edge.stream_code,
            branch_no=edge.branch_no,
            stream_type=edge.stream_type,
            metadata_json=dict(edge.metadata),
        )
        for edge in spec.edges
    )
    await session.flush()
    return installation


def _build_equipment(installation_version_id: str, spec: EquipmentSpec) -> Equipment:
    return Equipment(
        installation_version_id=installation_version_id,
        code=spec.code,
        equipment_type=spec.equipment_type,
        display_name=spec.display_name,
        metadata_json=dict(spec.metadata),
        tags=[
            ProcessTag(
                code=tag.code,
                value_type=tag.value_type,
                unit=tag.unit,
                normal_min=tag.normal_min,
                normal_max=tag.normal_max,
                warning_min=tag.warning_min,
                warning_max=tag.warning_max,
                critical_min=tag.critical_min,
                critical_max=tag.critical_max,
                visible_to_operator=tag.visible_to_operator,
                metadata_json={},
            )
            for tag in spec.tags
        ],
    )


def _require(equipment_by_code: dict[str, Equipment], code: str) -> Equipment:
    equipment = equipment_by_code.get(code)
    if equipment is None:
        raise ValueError(f"Конфигурация ссылается на неизвестное оборудование: {code}")
    return equipment
