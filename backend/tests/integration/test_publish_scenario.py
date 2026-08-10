from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.application.configuration import publish_installation, publish_scenario, publish_scoring_policy
from app.domain.rules import parse_rule
from app.domain.versioning import PublicationStatus
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import Equipment, ProcessTag, ScenarioVersion
from app.infrastructure.seed import scenario as scenario_seed
from app.infrastructure.seed.installation import build_installation_spec


async def publish_all(database: Database) -> None:
    async with database.session_factory() as session, session.begin():
        installation = await publish_installation(session, build_installation_spec())
        await publish_scenario(session, installation)
        await publish_scoring_policy(session)


async def load_scenario(database: Database) -> ScenarioVersion:
    async with database.session_factory() as session:
        scenario = await session.scalar(
            select(ScenarioVersion).options(
                selectinload(ScenarioVersion.levels),
                selectinload(ScenarioVersion.stages),
                selectinload(ScenarioVersion.alarm_rules),
                selectinload(ScenarioVersion.disturbance_templates),
                selectinload(ScenarioVersion.expected_action_rules),
            )
        )
    assert scenario is not None
    return scenario


async def test_published_scenario_contains_stages_levels_and_rules(database: Database) -> None:
    await publish_all(database)

    scenario = await load_scenario(database)

    assert scenario.status == PublicationStatus.PUBLISHED
    assert scenario.duration_ms == scenario_seed.SCENARIO_DURATION_MS
    assert [stage.code for stage in scenario.stages] == [stage.code for stage in scenario_seed.STAGES]
    assert {level.level_no for level in scenario.levels} == {1, 2, 3}
    assert {alarm.level for alarm in scenario.alarm_rules} == {"L1", "L2", "L3", "L4", "L5"}
    assert {template.cause_code for template in scenario.disturbance_templates} == {
        "pump_capacity_loss",
        "valve_stiction",
    }
    assert [action.order_no for action in scenario.expected_action_rules] == list(range(1, 10))


async def test_publish_is_idempotent(database: Database) -> None:
    await publish_all(database)
    await publish_all(database)

    async with database.session_factory() as session:
        scenarios = (await session.scalars(select(ScenarioVersion))).all()

    assert len(scenarios) == 1


async def test_rules_reference_existing_equipment_and_tags(database: Database) -> None:
    """Правила сценария опираются на каталог: неизвестный код тега сломал бы расчёт молча."""

    await publish_all(database)
    scenario = await load_scenario(database)

    async with database.session_factory() as session:
        equipment_codes = set((await session.scalars(select(Equipment.code))).all())
        tag_codes = set((await session.scalars(select(ProcessTag.code))).all())

    for alarm in scenario.alarm_rules:
        assert alarm.equipment_code in equipment_codes
        rules = [parse_rule(alarm.source_expression_json), parse_rule(alarm.clear_expression_json)]
        for parsed in rules:
            assert {item.metric for item in parsed.conditions} <= tag_codes

    for stage in scenario.stages:
        parsed = parse_rule(stage.success_rule_json)
        assert {item.metric for item in parsed.conditions} <= tag_codes


async def test_hidden_disturbance_configuration_is_stored_separately(database: Database) -> None:
    await publish_all(database)
    scenario = await load_scenario(database)

    for template in scenario.disturbance_templates:
        assert template.hidden_config_json != {}
        assert template.eligible_targets_json == [1, 2, 3]
