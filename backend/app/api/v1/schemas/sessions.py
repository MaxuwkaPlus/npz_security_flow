"""DTO сессии.

`random_seed`, `hidden_runtime_config_json` и скрытая причина возмущения не имеют
представления в этих схемах, поэтому не могут попасть в ответ.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.application.sessions import SessionState


class CreateSessionRequest(BaseModel):
    # instructor_id в запросе нет: он берётся из токена, иначе сессию можно было бы
    # назначить от чужого имени.
    request_id: str = Field(
        min_length=1, max_length=36, description="Уникальный идентификатор запроса, свой на каждый вызов"
    )
    operator_id: str = Field(min_length=1, max_length=64)
    scenario_version_id: str
    level_no: int = Field(ge=1, le=3)
    # Инструкторское поле: фиксированный seed нужен для воспроизводимой демонстрации.
    random_seed: int | None = Field(default=None, ge=0)


class SessionCommandRequest(BaseModel):
    # Пример задан явно: иначе Swagger подставляет в `expected_version` минимум схемы,
    # и запрос из готового примера падает с SESSION_VERSION_MISMATCH.
    model_config = ConfigDict(json_schema_extra={"example": {"request_id": "start-1"}})

    request_id: str = Field(
        min_length=1, max_length=36, description="Уникальный идентификатор запроса, свой на каждый вызов"
    )
    expected_version: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Необязательно. Текущий version_no сессии из GET /sessions/{id}/state — "
            "защита от одновременной работы двух клиентов. Пропустите поле, если клиент один."
        ),
    )


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
