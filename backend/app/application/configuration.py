from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.versioning import PublicationStatus
from app.infrastructure.db.models import (
    AlarmRule,
    DisturbanceTemplate,
    Equipment,
    ExpectedActionRule,
    InstallationVersion,
    ProcessTag,
    ScenarioLevel,
    ScenarioStage,
    ScenarioVersion,
    ScoringPolicyVersion,
    TopologyEdge,
)
from app.infrastructure.db.types import utcnow
from app.infrastructure.seed import scenario as scenario_seed
from app.infrastructure.seed import scoring as scoring_seed
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


async def publish_scenario(session: AsyncSession, installation: InstallationVersion) -> ScenarioVersion:
    """Публикует версию сквозного сценария вместе с уровнями, этапами и правилами."""

    existing = await session.scalar(
        select(ScenarioVersion).where(
            ScenarioVersion.scenario_code == scenario_seed.SCENARIO_CODE,
            ScenarioVersion.version == scenario_seed.SCENARIO_VERSION,
        )
    )
    if existing is not None:
        return existing

    scenario = ScenarioVersion(
        scenario_code=scenario_seed.SCENARIO_CODE,
        version=scenario_seed.SCENARIO_VERSION,
        installation_version_id=installation.id,
        name="Сквозной сценарий ЭЛОУ-АВТ",
        description=(
            "Пуск установки, вывод в устойчивый режим, скрытое снижение расхода одной "
            "сырьевой ветви, диагностика, восстановление и downstream-проверки."
        ),
        duration_ms=scenario_seed.SCENARIO_DURATION_MS,
        status=PublicationStatus.PUBLISHED,
        config_json=dict(scenario_seed.SCENARIO_CONFIG),
        published_at=utcnow(),
    )
    scenario.levels = [
        ScenarioLevel(
            level_no=level.level_no,
            sensor_delay_ms=level.sensor_delay_ms,
            nuisance_alarm_rate=level.nuisance_alarm_rate,
            reaction_deadline_ms=level.reaction_deadline_ms,
            development_speed_factor=level.development_speed_factor,
            hints_enabled=level.hints_enabled,
            reserve_config_json={"standby_pump_start_delay_ms": level.standby_pump_start_delay_ms},
        )
        for level in scenario_seed.LEVELS
    ]
    scenario.stages = [
        ScenarioStage(
            code=stage.code,
            order_no=order_no,
            entry_rule_json={},
            success_rule_json=stage.success.to_json(),
            failure_rule_json=stage.failure.to_json(),
            timeout_ms=stage.timeout_ms,
            required_checks_json=list(stage.required_checks),
        )
        for order_no, stage in enumerate(scenario_seed.STAGES, start=1)
    ]
    scenario.alarm_rules = [
        AlarmRule(
            code=alarm.code,
            level=alarm.level,
            equipment_code=alarm.equipment_code,
            source_expression_json=alarm.trigger.to_json(),
            activation_delay_ms=alarm.activation_delay_ms,
            clear_expression_json=alarm.clear.to_json(),
            ack_required=alarm.ack_required,
            message_template=alarm.message_template,
        )
        for alarm in scenario_seed.ALARM_RULES
    ]
    scenario.disturbance_templates = [
        DisturbanceTemplate(
            code=disturbance.code,
            cause_code=disturbance.cause_code,
            eligible_targets_json=list(scenario_seed.DISTURBANCE_ELIGIBLE_BRANCHES),
            onset_rule_json=dict(scenario_seed.DISTURBANCE_ONSET),
            development_rule_json=dict(disturbance.development),
            recovery_rule_json=dict(disturbance.recovery),
            hidden_config_json={"provisional": True},
        )
        for disturbance in scenario_seed.DISTURBANCES
    ]
    scenario.expected_action_rules = [
        ExpectedActionRule(
            situation_code=str(scenario_seed.SCENARIO_CONFIG["situation_code"]),
            action_type=action.action_type,
            target_selector=action.target_selector,
            order_no=action.order_no,
            required_preconditions_json=list(action.preconditions),
            valid_window_ms=action.valid_window_ms,
            expected_effect_json=dict(action.expected_effect),
            verification_rule_json=dict(action.verification),
            criticality=action.criticality,
            weight=action.weight,
        )
        for action in scenario_seed.EXPECTED_ACTIONS
    ]
    session.add(scenario)
    await session.flush()
    return scenario


async def publish_scoring_policy(session: AsyncSession) -> ScoringPolicyVersion:
    """Публикует версию политики оценки. Опубликованная политика неизменяема."""

    existing = await session.scalar(
        select(ScoringPolicyVersion).where(
            ScoringPolicyVersion.code == scoring_seed.SCORING_POLICY_CODE,
            ScoringPolicyVersion.version == scoring_seed.SCORING_POLICY_VERSION,
        )
    )
    if existing is not None:
        return existing

    policy = ScoringPolicyVersion(
        code=scoring_seed.SCORING_POLICY_CODE,
        version=scoring_seed.SCORING_POLICY_VERSION,
        status=PublicationStatus.PUBLISHED,
        weights_json=dict(scoring_seed.WEIGHTS),
        penalties_json=dict(scoring_seed.PENALTIES),
        stability_rule_json=dict(scoring_seed.STABILITY_RULE),
        reaction_rule_json=dict(scoring_seed.REACTION_RULE),
        published_at=utcnow(),
    )
    session.add(policy)
    await session.flush()
    return policy


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
