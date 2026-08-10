from collections.abc import Sequence

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.api.v1.schemas.catalog import (
    EquipmentResponse,
    ProcessTagResponse,
    ScenarioDetailResponse,
    ScenarioLevelResponse,
    ScenarioStageResponse,
    ScenarioSummaryResponse,
    TopologyEdgeResponse,
    TopologyResponse,
)
from app.core.errors import NotFoundError
from app.infrastructure.db.models import Equipment, ScenarioVersion, TopologyEdge
from app.infrastructure.repositories.catalog import CatalogRepository

router = APIRouter(tags=["catalog"])


@router.get("/scenarios", response_model=list[ScenarioSummaryResponse])
async def list_scenarios(session: SessionDep) -> list[ScenarioSummaryResponse]:
    scenarios = await CatalogRepository(session).list_published_scenarios()
    return [_summary(scenario) for scenario in scenarios]


@router.get("/scenarios/{scenario_version_id}", response_model=ScenarioDetailResponse)
async def get_scenario(scenario_version_id: str, session: SessionDep) -> ScenarioDetailResponse:
    scenario = await CatalogRepository(session).get_scenario(scenario_version_id)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария не найдена")
    return ScenarioDetailResponse(
        **_summary(scenario).model_dump(),
        levels=[
            ScenarioLevelResponse(
                level_no=level.level_no,
                sensor_delay_ms=level.sensor_delay_ms,
                nuisance_alarm_rate=level.nuisance_alarm_rate,
                reaction_deadline_ms=level.reaction_deadline_ms,
                development_speed_factor=level.development_speed_factor,
                hints_enabled=level.hints_enabled,
            )
            for level in sorted(scenario.levels, key=lambda level: level.level_no)
        ],
        stages=[
            ScenarioStageResponse(
                code=stage.code,
                order_no=stage.order_no,
                timeout_ms=stage.timeout_ms,
                required_checks=list(stage.required_checks_json),
            )
            for stage in scenario.stages
        ],
    )


@router.get("/installations/{installation_version_id}/topology", response_model=TopologyResponse)
async def get_topology(installation_version_id: str, session: SessionDep) -> TopologyResponse:
    repository = CatalogRepository(session)
    installation = await repository.get_installation(installation_version_id)
    if installation is None:
        raise NotFoundError("INSTALLATION_NOT_FOUND", "Версия установки не найдена")

    equipment = await repository.list_equipment(installation_version_id)
    edges = await repository.list_topology_edges(installation_version_id)
    return TopologyResponse(
        installation_version_id=installation.id,
        installation_code=installation.installation_code,
        version=installation.version,
        name=installation.name,
        equipment=_equipment_responses(equipment),
        edges=_edge_responses(edges, equipment),
    )


def _summary(scenario: ScenarioVersion) -> ScenarioSummaryResponse:
    return ScenarioSummaryResponse(
        id=scenario.id,
        scenario_code=scenario.scenario_code,
        version=scenario.version,
        name=scenario.name,
        description=scenario.description,
        duration_ms=scenario.duration_ms,
        installation_version_id=scenario.installation_version_id,
    )


def _equipment_responses(equipment: Sequence[Equipment]) -> list[EquipmentResponse]:
    code_by_id = {item.id: item.code for item in equipment}
    return [
        EquipmentResponse(
            code=item.code,
            equipment_type=item.equipment_type,
            display_name=item.display_name,
            parent_code=code_by_id.get(item.parent_equipment_id or ""),
            tags=[
                ProcessTagResponse(
                    code=tag.code,
                    unit=tag.unit,
                    value_type=tag.value_type,
                    normal_min=tag.normal_min,
                    normal_max=tag.normal_max,
                    warning_min=tag.warning_min,
                    warning_max=tag.warning_max,
                    critical_min=tag.critical_min,
                    critical_max=tag.critical_max,
                )
                for tag in sorted(item.tags, key=lambda tag: tag.code)
                if tag.visible_to_operator
            ],
        )
        for item in equipment
    ]


def _edge_responses(
    edges: Sequence[TopologyEdge], equipment: Sequence[Equipment]
) -> list[TopologyEdgeResponse]:
    code_by_id = {item.id: item.code for item in equipment}
    return [
        TopologyEdgeResponse(
            from_code=code_by_id[edge.from_equipment_id],
            to_code=code_by_id[edge.to_equipment_id],
            stream_code=edge.stream_code,
            stream_type=edge.stream_type,
            branch_no=edge.branch_no,
        )
        for edge in edges
    ]
