from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field

from app.application.observations import DiagnosisReceipt, ObservationReceipt


class RecordObservationRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=36)
    observation_type: str = Field(min_length=1, max_length=64)
    target_code: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class ObservationResponse(BaseModel):
    id: str
    request_id: str
    session_id: str
    sequence_no: int
    sim_time_ms: int
    observation_type: str
    target_code: str

    @classmethod
    def from_receipt(cls, receipt: ObservationReceipt) -> "ObservationResponse":
        return cls(**asdict(receipt))


class SubmitDiagnosisRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=36)
    affected_area_code: str = Field(min_length=1, max_length=64)
    deviation_code: str = Field(min_length=1, max_length=64)
    suspected_cause_code: str = Field(min_length=1, max_length=64)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DiagnosisResponse(BaseModel):
    """Правильность диагноза здесь отсутствует: она станет известна только в отчёте."""

    id: str
    request_id: str
    session_id: str
    sequence_no: int
    sim_time_ms: int
    affected_area_code: str
    deviation_code: str
    suspected_cause_code: str

    @classmethod
    def from_receipt(cls, receipt: DiagnosisReceipt) -> "DiagnosisResponse":
        return cls(**asdict(receipt))
