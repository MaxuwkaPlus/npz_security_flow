import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domain.versioning import PublicationStatus
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import Equipment, InstallationVersion, ProcessTag


def make_installation(version: int = 1) -> InstallationVersion:
    return InstallationVersion(
        installation_code="ELOU-AVT",
        version=version,
        name="Установка ЭЛОУ-АВТ",
        status=PublicationStatus.DRAFT,
        config_json={},
    )


async def test_equipment_code_is_unique_inside_installation_version(database: Database) -> None:
    async with database.session_factory() as session:
        installation = make_installation()
        session.add(installation)
        await session.flush()
        session.add_all(
            [
                Equipment(
                    installation_version_id=installation.id,
                    code="T-4/1",
                    equipment_type="heat_exchanger",
                    display_name="Т-4/1",
                    metadata_json={},
                ),
                Equipment(
                    installation_version_id=installation.id,
                    code="T-4/1",
                    equipment_type="heat_exchanger",
                    display_name="Т-4/1 дубль",
                    metadata_json={},
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            await session.commit()


async def test_tag_with_unknown_equipment_is_rejected_by_foreign_key(database: Database) -> None:
    async with database.session_factory() as session:
        session.add(
            ProcessTag(
                equipment_id="00000000-0000-0000-0000-000000000000",
                code="FRC-405",
                value_type="float",
                unit="t/h",
                metadata_json={},
            )
        )

        with pytest.raises(IntegrityError):
            await session.commit()


async def test_deleting_equipment_removes_its_tags(database: Database) -> None:
    async with database.session_factory() as session:
        installation = make_installation()
        equipment = Equipment(
            installation_version=installation,
            code="FRC-405",
            equipment_type="flow_controller",
            display_name="Регулятор расхода ветви №2",
            metadata_json={},
            tags=[
                ProcessTag(
                    code="FRC-405.flow", value_type="float", unit="t/h", normal_min=95.0, metadata_json={}
                )
            ],
        )
        session.add(equipment)
        await session.commit()

        await session.delete(equipment)
        await session.commit()

        remaining = await session.scalars(select(ProcessTag))
        assert remaining.all() == []
