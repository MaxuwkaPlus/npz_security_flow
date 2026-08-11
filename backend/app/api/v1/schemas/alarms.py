from pydantic import BaseModel, Field

from app.application.alarms import AlarmView


class AcknowledgeAlarmRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=36)


class AlarmResponse(BaseModel):
    id: str
    alarm_code: str
    level: str
    equipment_code: str
    message: str
    state: str
    started_sim_time_ms: int
    acknowledged_sim_time_ms: int | None
    cleared_sim_time_ms: int | None
    is_nuisance: bool

    @classmethod
    def from_view(cls, view: AlarmView) -> "AlarmResponse":
        return cls(
            id=view.id,
            alarm_code=view.alarm_code,
            level=view.level,
            equipment_code=view.equipment_code,
            message=view.message,
            state=view.state.value,
            started_sim_time_ms=view.started_sim_time_ms,
            acknowledged_sim_time_ms=view.acknowledged_sim_time_ms,
            cleared_sim_time_ms=view.cleared_sim_time_ms,
            is_nuisance=view.is_nuisance,
        )
