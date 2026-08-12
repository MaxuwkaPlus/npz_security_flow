from dataclasses import asdict

from pydantic import BaseModel, Field

from app.application.assessment import CheckpointResult, CheckpointView
from app.domain.nasa_tlx import SCALE_MAX, SCALE_MIN
from app.infrastructure.db.models import NasaTlxResponse


class SagatQuestionResponse(BaseModel):
    """Эталонного ответа здесь нет: он вычисляется на сервере при проверке."""

    code: str
    kind: str
    prompt: str
    options: list[str]


class SagatCheckpointResponse(BaseModel):
    id: str
    checkpoint_code: str
    status: str
    triggered_sim_time_ms: int
    answers_deadline_sim_time_ms: int
    questions: list[SagatQuestionResponse]

    @classmethod
    def from_view(cls, view: CheckpointView) -> "SagatCheckpointResponse":
        return cls(
            id=view.id,
            checkpoint_code=view.checkpoint_code,
            status=view.status,
            triggered_sim_time_ms=view.triggered_sim_time_ms,
            answers_deadline_sim_time_ms=view.answers_deadline_sim_time_ms,
            questions=[SagatQuestionResponse(**asdict(question)) for question in view.questions],
        )


class SubmitSagatAnswersRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=36)
    answers: dict[str, str]


class SagatResultResponse(BaseModel):
    id: str
    checkpoint_code: str
    status: str
    scores: dict[str, float]
    earned: float
    maximum: float

    @classmethod
    def from_result(cls, result: CheckpointResult) -> "SagatResultResponse":
        return cls(
            id=result.id,
            checkpoint_code=result.checkpoint_code,
            status=result.status,
            scores=result.scores,
            earned=result.earned,
            maximum=result.maximum,
        )


class NasaTlxRequest(BaseModel):
    mental_demand: float = Field(ge=SCALE_MIN, le=SCALE_MAX)
    physical_demand: float = Field(ge=SCALE_MIN, le=SCALE_MAX)
    temporal_demand: float = Field(ge=SCALE_MIN, le=SCALE_MAX)
    performance: float = Field(ge=SCALE_MIN, le=SCALE_MAX)
    effort: float = Field(ge=SCALE_MIN, le=SCALE_MAX)
    frustration: float = Field(ge=SCALE_MIN, le=SCALE_MAX)


class NasaTlxResponseSchema(BaseModel):
    session_id: str
    raw_tlx_score: float
    values: dict[str, float]

    @classmethod
    def from_model(cls, model: NasaTlxResponse) -> "NasaTlxResponseSchema":
        return cls(
            session_id=model.session_id,
            raw_tlx_score=model.raw_tlx_score,
            values=model.values_json,
        )
