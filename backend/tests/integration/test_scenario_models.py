import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domain.versioning import PublicationStatus
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import InstallationVersion, ScenarioLevel, ScenarioStage, ScenarioVersion


def make_scenario(installation: InstallationVersion, version: int = 1) -> ScenarioVersion:
    return ScenarioVersion(
        scenario_code="ELOU-AVT-FULL-RUN",
        version=version,
        installation_version=installation,
        name="Сквозной сценарий ЭЛОУ-АВТ",
        duration_ms=3_900_000,
        status=PublicationStatus.DRAFT,
        config_json={},
    )


def make_installation() -> InstallationVersion:
    return InstallationVersion(
        installation_code="ELOU-AVT",
        version=1,
        name="Установка ЭЛОУ-АВТ",
        status=PublicationStatus.PUBLISHED,
        config_json={},
    )


def make_level(level_no: int) -> ScenarioLevel:
    return ScenarioLevel(
        level_no=level_no,
        sensor_delay_ms=0,
        nuisance_alarm_rate=0.4,
        reaction_deadline_ms=120_000,
        development_speed_factor=1.0,
        hints_enabled=True,
        reserve_config_json={},
    )


async def test_scenario_code_and_version_pair_is_unique(database: Database) -> None:
    async with database.session_factory() as session:
        installation = make_installation()
        session.add_all([make_scenario(installation), make_scenario(installation)])

        with pytest.raises(IntegrityError):
            await session.commit()


async def test_level_number_is_unique_inside_scenario_version(database: Database) -> None:
    async with database.session_factory() as session:
        scenario = make_scenario(make_installation())
        scenario.levels = [make_level(1), make_level(1)]
        session.add(scenario)

        with pytest.raises(IntegrityError):
            await session.commit()


async def test_deleting_scenario_version_removes_its_stages(database: Database) -> None:
    async with database.session_factory() as session:
        scenario = make_scenario(make_installation())
        scenario.stages = [
            ScenarioStage(
                code="precheck",
                order_no=1,
                entry_rule_json={},
                success_rule_json={},
                failure_rule_json={},
                timeout_ms=120_000,
                required_checks_json=["feed_pumps_ready"],
            )
        ]
        session.add(scenario)
        await session.commit()

        await session.delete(scenario)
        await session.commit()

        remaining = await session.scalars(select(ScenarioStage))
        assert remaining.all() == []
