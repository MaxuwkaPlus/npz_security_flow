"""DTO каталога и сценария.

Поля перечислены явным белым списком: скрытые шаблоны возмущения, эталонные действия
и `hidden_config` не имеют представления в этих схемах и не могут попасть в ответ.
"""

from pydantic import BaseModel


class ScenarioLevelResponse(BaseModel):
    level_no: int
    sensor_delay_ms: int
    nuisance_alarm_rate: float
    reaction_deadline_ms: int
    development_speed_factor: float
    hints_enabled: bool


class ScenarioStageResponse(BaseModel):
    code: str
    order_no: int
    timeout_ms: int
    required_checks: list[str]


class ScenarioSummaryResponse(BaseModel):
    id: str
    scenario_code: str
    version: int
    name: str
    description: str
    duration_ms: int
    installation_version_id: str


class ScenarioDetailResponse(ScenarioSummaryResponse):
    levels: list[ScenarioLevelResponse]
    stages: list[ScenarioStageResponse]


class ProcessTagResponse(BaseModel):
    code: str
    unit: str
    value_type: str
    normal_min: float | None
    normal_max: float | None
    warning_min: float | None
    warning_max: float | None
    critical_min: float | None
    critical_max: float | None


class EquipmentResponse(BaseModel):
    code: str
    equipment_type: str
    display_name: str
    parent_code: str | None
    tags: list[ProcessTagResponse]


class TopologyEdgeResponse(BaseModel):
    from_code: str
    to_code: str
    stream_code: str
    stream_type: str
    branch_no: int | None


class TopologyResponse(BaseModel):
    installation_version_id: str
    installation_code: str
    version: int
    name: str
    equipment: list[EquipmentResponse]
    edges: list[TopologyEdgeResponse]
