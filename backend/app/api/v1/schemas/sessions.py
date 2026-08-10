"""DTO сессии.

`random_seed`, `hidden_runtime_config_json` и скрытая причина возмущения не имеют
представления в этих схемах, поэтому не могут попасть в ответ.
"""

from pydantic import BaseModel, Field

from app.application.sessions import SessionState


class CreateSessionRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=36)
    operator_id: str = Field(min_length=1, max_length=64)
    scenario_version_id: str
    level_no: int = Field(ge=1, le=3)
    instructor_id: str | None = None
    # Инструкторское поле: фиксированный seed нужен для воспроизводимой демонстрации.
    random_seed: int | None = Field(default=None, ge=0)


class SessionCommandRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=36)
    expected_version: int | None = Field(default=None, ge=1)


class SessionResponse(BaseModel):
    id: str
    operator_id: str
    instructor_id: str | None
    scenario_version_id: str
    level_no: int
    status: str
    sim_time_ms: int
    sequence_no: int
    current_stage_code: str
    version_no: int
    final_outcome: str | None

    @classmethod
    def from_state(cls, state: SessionState) -> "SessionResponse":
        return cls(**state.to_json())
